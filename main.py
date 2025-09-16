import os
import json
from dotenv import load_dotenv

# Cargar variables de entorno PRIMERO
load_dotenv()

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import PlainTextResponse
import logging
from typing import Optional
from chatbot.rules import ChatbotRules
from chatbot.states import conversation_manager
from chatbot.models import EstadoConversacion
from services.slack_service import slack_service
from services.twilio_service import twilio_service
from services.email_service import email_service
from services.error_reporter import error_reporter, ErrorTrigger
from services.metrics_service import metrics_service

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear la aplicación FastAPI
app = FastAPI(
    title="Argenfuego Chatbot API",
    description="Chatbot basado en reglas para WhatsApp usando Twilio",
    version="1.0.0"
)

TTL_MINUTES = int(os.getenv("HANDOFF_TTL_MINUTES", "120"))

@app.get("/")
async def root():
    return {
        "message": "Argenfuego Chatbot API",
        "status": "active",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "argenfuego-chatbot"
    }

@app.post("/handoff/ttl-sweep")
async def handoff_ttl_sweep(token: str = Form(...)):
    """Job idempotente para cerrar conversaciones en handoff por inactividad.
    Ejecutar cada 15 minutos con cron. TTL por env (default 120 min)."""
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    from datetime import datetime, timedelta
    ahora = datetime.utcnow()
    cerradas = 0
    for conv in list(conversation_manager.conversaciones.values()):
        if conv.atendido_por_humano or conv.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
            last_ts = conv.last_client_message_at or conv.handoff_started_at
            if last_ts and (ahora - last_ts) > timedelta(minutes=TTL_MINUTES):
                try:
                    twilio_service.send_whatsapp_message(conv.numero_telefono, "Esta conversación se finalizará por inactividad. ¡Muchas gracias por contactarnos! 🕒")
                except Exception:
                    pass
                conversation_manager.finalizar_conversacion(conv.numero_telefono)
                cerradas += 1
    return {"closed": cerradas}

@app.post("/webhook")
async def webhook_whatsapp(request: Request):
    try:
        # Obtener datos del formulario de Twilio
        form_data = await request.form()
        form_dict = dict(form_data)
        
        logger.info(f"Webhook recibido: {form_dict}")
        
        # Extraer datos del mensaje
        numero_telefono, mensaje_usuario, message_sid, profile_name = twilio_service.extract_message_data(form_dict)
        
        if not numero_telefono or not mensaje_usuario:
            logger.warning("Datos incompletos en el webhook")
            return PlainTextResponse("OK", status_code=200)
        
        logger.info(f"Procesando mensaje de {numero_telefono} ({profile_name or 'sin nombre'}): {mensaje_usuario}")
        
        # Si está en handoff, reenviar a Slack y no responder con bot
        conversacion_actual = conversation_manager.get_conversacion(numero_telefono)
        if conversacion_actual.atendido_por_humano or conversacion_actual.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
            # Publicar en Slack (canal configurado) en thread asociado o crear uno
            channel = conversacion_actual.slack_channel_id or os.getenv("SLACK_CHANNEL_ID", "")
            
            # Si es el primer mensaje del handoff, incluir contexto
            if conversacion_actual.mensaje_handoff_contexto and not conversacion_actual.slack_thread_ts:
                header = f"🔄 *Nueva solicitud de agente humano*\nCliente: {profile_name or ''} ({numero_telefono})\n\n📝 *Mensaje que disparó el handoff:*\n{conversacion_actual.mensaje_handoff_contexto}\n\n💬 *Último mensaje:*\n{mensaje_usuario}"
            else:
                header = f"Nuevo mensaje del cliente {profile_name or ''} ({numero_telefono}):\n{mensaje_usuario}"
            
            # Botones condicionales: "Responder al cliente" solo si no está activo
            elements = []
            
            # Solo mostrar "Responder al cliente" si el modo conversación no está activo
            if not conversacion_actual.modo_conversacion_activa:
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Responder al cliente"},
                    "action_id": "respond_to_client",
                    "style": "primary"
                })
            
            # Botón "Resuelto" siempre visible
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Resuelto"},
                "action_id": "mark_resolved",
                "style": "danger"
            })
            
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": header}
                },
                {
                    "type": "actions",
                    "elements": elements
                }
            ]
            
            ts = slack_service.post_message(channel, header, thread_ts=conversacion_actual.slack_thread_ts, blocks=blocks)
            if not conversacion_actual.slack_thread_ts and ts:
                conversacion_actual.slack_thread_ts = ts
                conversacion_actual.slack_channel_id = channel
            try:
                from datetime import datetime
                conversacion_actual.last_client_message_at = datetime.utcnow()
            except Exception:
                pass
            return PlainTextResponse("", status_code=200)

        # Procesar el mensaje con el chatbot (incluyendo nombre del perfil)
        respuesta = ChatbotRules.procesar_mensaje(numero_telefono, mensaje_usuario, profile_name)
        
        # Enviar respuesta via WhatsApp
        mensaje_enviado = twilio_service.send_whatsapp_message(numero_telefono, respuesta)
        
        if not mensaje_enviado:
            logger.error(f"Error enviando mensaje a {numero_telefono}")
        
        # Verificar si necesitamos enviar email
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        if conversacion.estado == EstadoConversacion.ENVIANDO:
            # Enviar email con los datos del lead
            email_enviado = email_service.enviar_lead_email(conversacion)
            
            if email_enviado:
                try:
                    metrics_service.on_lead_sent()
                except Exception:
                    pass
                # Enviar mensaje de confirmación
                mensaje_final = ChatbotRules.get_mensaje_final_exito()
                twilio_service.send_whatsapp_message(numero_telefono, mensaje_final)
                
                # Finalizar la conversación
                conversation_manager.finalizar_conversacion(numero_telefono)
                
                logger.info(f"Lead procesado exitosamente para {numero_telefono}")
            else:
                # Error enviando email
                error_msg = "❌ Hubo un error procesando tu solicitud. Por favor intenta nuevamente más tarde."
                twilio_service.send_whatsapp_message(numero_telefono, error_msg)
                logger.error(f"Error enviando email para {numero_telefono}")
        
        return PlainTextResponse("", status_code=200)
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        # Reporte estructurado de excepción
        try:
            form_data = await request.form()
            form_dict = dict(form_data)
        except Exception:
            form_dict = {}
        try:
            error_reporter.capture_exception(
                e,
                {
                    "conversation_id": form_dict.get('From', ''),
                    "numero_telefono": form_dict.get('From', ''),
                    "estado_actual": "webhook",
                    "estado_anterior": "",
                    "stack": "",
                }
            )
        except Exception:
            pass
        return PlainTextResponse("Error", status_code=500)


@app.post("/slack/commands")
async def slack_commands(request: Request):
    # Verificar firma Slack
    timestamp = request.headers.get("X-Slack-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    body = await request.body()
    body_text = body.decode("utf-8")
    if not slack_service.verify_signature(timestamp, signature, body_text):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form = await request.form()
    command = form.get("command", "")
    text = (form.get("text", "") or "").strip()
    channel_id = form.get("channel_id", "")
    thread_ts = form.get("thread_ts", "")

    try:
        if command == "/responder":
            # Soporta dos modos:
            # 1) Dentro de un hilo: usar thread_ts para mapear al número
            # 2) Fuera de hilo: /responder <whatsapp:+549...> <mensaje>
            to = None
            body_msg = None
            if thread_ts:
                # Buscar conversación por thread_ts
                for conv in conversation_manager.conversaciones.values():
                    if conv.slack_thread_ts == thread_ts and conv.slack_channel_id == channel_id:
                        to = conv.numero_telefono
                        break
                if not to:
                    # Fallback a formato con número si no encontramos hilo
                    if not text:
                        return PlainTextResponse("No se encontró el hilo. Uso: /responder <whatsapp:+549...> <mensaje>")
            if not to:
                if not text:
                    return PlainTextResponse("Uso: /responder <whatsapp:+549...> <mensaje>")
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    return PlainTextResponse("Uso: /responder <whatsapp:+549...> <mensaje>")
                to, body_msg = parts[0], parts[1]
            else:
                body_msg = text or ""
            sent = twilio_service.send_whatsapp_message(to, body_msg)
            if sent:
                return PlainTextResponse("Enviado ✅")
            return PlainTextResponse("Error enviando ❌")

        if command in ["/resuelto", "/finalizar", "/cerrar"]:
            if not text:
                return PlainTextResponse("Uso: /resuelto <whatsapp:+549...>")
            to = text.split()[0]
            conversation_manager.finalizar_conversacion(to)
            cierre_msg = "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
            twilio_service.send_whatsapp_message(to, cierre_msg)
            return PlainTextResponse("Conversación finalizada ✅")

        return PlainTextResponse("Comando no soportado")
    except Exception as e:
        logger.error(f"/slack/commands error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/slack/actions")
async def slack_actions(request: Request):
    
    # Verificar firma Slack
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    body = await request.body()
    body_text = body.decode("utf-8")
    if not slack_service.verify_signature(timestamp, signature, body_text):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))
    
    try:
        # Detectar tipo de request: block_actions (botones) o view_submission (modal)
        request_type = payload.get("type", "")
        logger.info(f"=== SLACK REQUEST TYPE: {request_type} ===")
        
        if request_type == "view_submission":
            # Manejar envío de modal
            logger.info("=== PROCESSING MODAL SUBMISSION ===")
            return await handle_modal_submission(payload)
        elif request_type == "block_actions":
            # Manejar clics de botones
            logger.info("=== PROCESSING BUTTON CLICK ===")
            return await handle_button_click(payload)
        else:
            logger.error(f"❌ Tipo de request no reconocido: {request_type}")
            return PlainTextResponse("Tipo de request no reconocido", status_code=400)
    except Exception as e:
        logger.error(f"/slack/actions error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

async def handle_modal_submission(payload: dict):
    """Maneja el envío de modales"""
    try:
        # Procesar envío del modal
        values = payload.get("view", {}).get("state", {}).get("values", {})
        message = values.get("message_input", {}).get("message", {}).get("value", "")
        private_metadata = payload.get("view", {}).get("private_metadata", "{}")
        
        logger.info(f"Message from modal: '{message}'")
        logger.info(f"Private metadata: '{private_metadata}'")
        
        if not message.strip():
            logger.error("❌ Mensaje vacío en modal")
            return PlainTextResponse("Mensaje vacío", status_code=400)
        
        # Extraer thread_ts y channel_id del private_metadata
        try:
            metadata = json.loads(private_metadata)
            thread_ts = metadata.get("thread_ts", "")
            channel_id = metadata.get("channel_id", "")
            logger.info(f"Extracted thread_ts: '{thread_ts}', channel_id: '{channel_id}'")
        except Exception as e:
            logger.error(f"❌ Error parsing private_metadata: {e}")
            thread_ts = ""
            channel_id = ""
        
        # Buscar conversación por thread_ts y channel_id
        logger.info(f"=== SEARCHING CONVERSATION ===")
        logger.info(f"Total conversaciones: {len(conversation_manager.conversaciones)}")
        
        to = None
        for numero, conv in conversation_manager.conversaciones.items():
            logger.info(f"Conv {numero}: slack_thread_ts='{conv.slack_thread_ts}', slack_channel_id='{conv.slack_channel_id}', atendido_por_humano={conv.atendido_por_humano}")
            if conv.slack_thread_ts == thread_ts and conv.slack_channel_id == channel_id:
                to = conv.numero_telefono
                logger.info(f"✅ MATCH encontrado: {to}")
                break
        
        if to:
            logger.info(f"=== ENVIANDO MENSAJE VIA TWILIO ===")
            logger.info(f"Destino: {to}")
            logger.info(f"Mensaje: {message}")
            sent = twilio_service.send_whatsapp_message(to, message)
            logger.info(f"Resultado Twilio: {sent}")
            if sent:
                logger.info("✅ Mensaje enviado exitosamente a WhatsApp")
                return PlainTextResponse("")
            else:
                logger.error("❌ Error enviando mensaje via Twilio")
                return PlainTextResponse("Error enviando mensaje", status_code=500)
        else:
            logger.error(f"❌ No se encontró conversación para thread_ts='{thread_ts}', channel_id='{channel_id}'")
            return PlainTextResponse("No se encontró conversación activa", status_code=400)
    except Exception as e:
        logger.error(f"Error en handle_modal_submission: {e}")
        return PlainTextResponse("Error interno", status_code=500)

async def handle_button_click(payload: dict):
    """Maneja los clics de botones"""
    try:
        action_id = payload.get("actions", [{}])[0].get("action_id", "")
        trigger_id = payload.get("trigger_id", "")
        response_url = payload.get("response_url", "")
        channel_id = payload.get("channel", {}).get("id", "")
        
        # Extraer thread_ts del payload de Slack
        # En block_actions, el thread_ts está en message.ts o container.message_ts
        thread_ts = (
            payload.get("message", {}).get("ts", "") or
            payload.get("container", {}).get("message_ts", "") or
            ""
        )
        
        if action_id == "respond_to_client":
            logger.info("=== ACTIVATING CONVERSATION MODE ===")
            logger.info(f"thread_ts: {thread_ts}")
            logger.info(f"channel_id: {channel_id}")
            
            # Buscar conversación y activar modo conversación activa
            to = None
            for conv in conversation_manager.conversaciones.values():
                if conv.slack_thread_ts == thread_ts and conv.slack_channel_id == channel_id:
                    to = conv.numero_telefono
                    conv.modo_conversacion_activa = True
                    logger.info(f"✅ Modo conversación activa activado para {to}")
                    break
            
            if to:
                # Solo responder al botón, sin mensaje de confirmación al hilo
                slack_service.respond_interaction(response_url, "✅ Modo conversación activa activado. Responde directamente en el hilo.")
                return PlainTextResponse("")
            else:
                logger.error(f"❌ No se encontró conversación para thread_ts={thread_ts}, channel_id={channel_id}")
                slack_service.respond_interaction(response_url, "❌ No se encontró la conversación")
                return PlainTextResponse("No se encontró conversación", status_code=400)
                
        elif action_id == "mark_resolved":
            # Marcar como resuelto y cerrar modo conversación activa
            to = None
            for conv in conversation_manager.conversaciones.values():
                if conv.slack_thread_ts == thread_ts and conv.slack_channel_id == channel_id:
                    to = conv.numero_telefono
                    conv.modo_conversacion_activa = False  # Cerrar modo conversación activa
                    logger.info(f"✅ Modo conversación activa cerrado para {to}")
                    break
            
            if to:
                conversation_manager.finalizar_conversacion(to)
                cierre_msg = "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
                twilio_service.send_whatsapp_message(to, cierre_msg)
                
                # Enviar mensaje de confirmación al hilo
                confirmation_msg = "🔒 *Conversación finalizada* - El modo conversación activa ha sido cerrado."
                slack_service.post_message(channel_id, confirmation_msg, thread_ts=thread_ts)
                
                slack_service.respond_interaction(response_url, "Conversación finalizada ✅")
            else:
                slack_service.respond_interaction(response_url, "No se encontró la conversación ❌")
            
            return PlainTextResponse("")
        
        return PlainTextResponse("Acción no reconocida")
    except Exception as e:
        logger.error(f"Error en handle_button_click: {e}")
        return PlainTextResponse("Error interno", status_code=500)



@app.post("/agent/reply")
async def agent_reply(to: str = Form(...), body: str = Form(...), token: str = Form(...)):
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        sent = twilio_service.send_whatsapp_message(to, body)
        if not sent:
            raise HTTPException(status_code=500, detail="Failed to send message")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"agent_reply error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/slack/events")
async def slack_events(request: Request):
    """Maneja eventos de Slack (mensajes del canal)"""
    try:
        body = await request.body()
        data = json.loads(body.decode())
        
        # Verificar challenge de Slack
        if data.get("type") == "url_verification":
            return PlainTextResponse(data.get("challenge", ""))
        
        # Verificar firma de Slack
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not slack_service.verify_signature(timestamp, signature, body.decode()):
            logger.error("❌ Invalid Slack signature in /slack/events")
            raise HTTPException(status_code=401, detail="Invalid Slack signature")
        
        # Procesar evento
        event = data.get("event", {})
        if event.get("type") == "message":
            await handle_slack_message(event)
        
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f"/slack/events error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

async def handle_slack_message(event: dict):
    """Maneja mensajes de Slack en hilos con modo conversación activa"""
    try:
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts", "")
        user = event.get("user", "")
        text = event.get("text", "").strip()
        
        # Solo procesar mensajes en hilos
        if not thread_ts:
            return
        
        # Buscar conversación con modo conversación activa
        for conv in conversation_manager.conversaciones.values():
            if (conv.slack_thread_ts == thread_ts and 
                conv.slack_channel_id == channel and 
                conv.modo_conversacion_activa):
                
                # Verificar que no sea un mensaje del bot
                bot_user_id = slack_service.get_bot_user_id()
                if user == bot_user_id:
                    continue
                
                logger.info(f"=== AGENT MESSAGE DETECTED ===")
                logger.info(f"Channel: {channel}, Thread: {thread_ts}")
                logger.info(f"User: {user}, Message: {text}")
                logger.info(f"Target WhatsApp: {conv.numero_telefono}")
                
                # Enviar mensaje a WhatsApp
                sent = twilio_service.send_whatsapp_message(conv.numero_telefono, text)
                if sent:
                    logger.info("✅ Mensaje del agente enviado a WhatsApp")
                else:
                    logger.error("❌ Error enviando mensaje del agente a WhatsApp")
                break
                
    except Exception as e:
        logger.error(f"Error en handle_slack_message: {e}")

@app.post("/agent/close")
async def agent_close(to: str = Form(...), token: str = Form(...)):
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        conversation_manager.finalizar_conversacion(to)
        cierre_msg = "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
        twilio_service.send_whatsapp_message(to, cierre_msg)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"agent_close error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@app.get("/stats")
async def get_stats():
    """Endpoint para obtener estadísticas básicas del chatbot"""
    total_conversaciones = len(conversation_manager.conversaciones)
    conversaciones_por_estado = {}
    
    for conversacion in conversation_manager.conversaciones.values():
        estado = conversacion.estado
        conversaciones_por_estado[estado] = conversaciones_por_estado.get(estado, 0) + 1
    
    return {
        "total_conversaciones_activas": total_conversaciones,
        "conversaciones_por_estado": conversaciones_por_estado,
        "timestamp": "2024-01-01T00:00:00Z"  # Placeholder timestamp
    }

@app.post("/reset-conversation")
async def reset_conversation(numero_telefono: str = Form(...)):
    """Endpoint para resetear una conversación específica (útil para debugging)"""
    try:
        conversation_manager.reset_conversacion(numero_telefono)
        return {"message": f"Conversación resetada para {numero_telefono}"}
    except Exception as e:
        logger.error(f"Error reseteando conversación: {str(e)}")
        raise HTTPException(status_code=500, detail="Error reseteando conversación")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)