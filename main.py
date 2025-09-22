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
from services.whatsapp_handoff_service import whatsapp_handoff_service
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
    resolution_timeout_minutes = 10  # Timeout para preguntas de resolución
    
    for conv in list(conversation_manager.conversaciones.values()):
        if conv.atendido_por_humano or conv.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
            should_close = False
            close_reason = ""
            
            # Verificar timeout de pregunta de resolución (10 minutos)
            if conv.resolution_question_sent and conv.resolution_question_sent_at:
                if (ahora - conv.resolution_question_sent_at) > timedelta(minutes=resolution_timeout_minutes):
                    should_close = True
                    close_reason = "Pregunta de resolución sin respuesta"
            
            # Verificar TTL general (120 minutos)
            elif conv.last_client_message_at or conv.handoff_started_at:
                last_ts = conv.last_client_message_at or conv.handoff_started_at
                if last_ts and (ahora - last_ts) > timedelta(minutes=TTL_MINUTES):
                    should_close = True
                    close_reason = "Inactividad general"
            
            if should_close:
                try:
                    if close_reason == "Pregunta de resolución sin respuesta":
                        twilio_service.send_whatsapp_message(conv.numero_telefono, "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅")
                    else:
                        twilio_service.send_whatsapp_message(conv.numero_telefono, "Esta conversación se finalizará por inactividad. ¡Muchas gracias por contactarnos! 🕒")
                except Exception:
                    pass
                conversation_manager.finalizar_conversacion(conv.numero_telefono)
                cerradas += 1
                logger.info(f"Conversación {conv.numero_telefono} cerrada por: {close_reason}")
    
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

        # Fallback unificado para contenidos no-texto (audio/imagen/video/documento/etc.)
        try:
            num_media = int(form_dict.get('NumMedia', '0') or '0')
        except Exception:
            num_media = 0

        message_type = (form_dict.get('MessageType') or '').lower().strip()

        if not whatsapp_handoff_service.is_agent_message(numero_telefono):
            if num_media > 0 or message_type in ['image', 'audio', 'video', 'document', 'file', 'sticker', 'media', 'location']:
                try:
                    from config.company_profiles import get_active_company_profile
                    email_contacto = (get_active_company_profile() or {}).get('email', '')
                except Exception:
                    email_contacto = ''

                fallback_email = f" También podés enviarnos toda la información por email a {email_contacto}." if email_contacto else ""
                fallback_msg = (
                    "Recibí tu mensaje, pero lamentablemente el contenido no es compatible con mis herramientas actuales. "
                    "Por este canal solo puedo procesar texto. Por favor, escribí en 1–2 frases lo que necesitás y te ayudo enseguida." + fallback_email
                )
                twilio_service.send_whatsapp_message(numero_telefono, fallback_msg)
                return PlainTextResponse("", status_code=200)
        
        # Verificar si el mensaje viene del agente
        if whatsapp_handoff_service.is_agent_message(numero_telefono):
            # Procesar mensaje del agente
            await handle_agent_message(numero_telefono, mensaje_usuario, profile_name)
            return PlainTextResponse("", status_code=200)
        
        # Si está en handoff, reenviar a WhatsApp del agente y no responder con bot
        conversacion_actual = conversation_manager.get_conversacion(numero_telefono)
        if conversacion_actual.atendido_por_humano or conversacion_actual.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
            # Notificar al agente vía WhatsApp
            if conversacion_actual.mensaje_handoff_contexto and not conversacion_actual.handoff_notified:
                # Es el primer mensaje del handoff, incluir contexto completo con botones
                success = whatsapp_handoff_service.send_agent_buttons(
                    numero_telefono,
                    profile_name or '',
                    conversacion_actual.mensaje_handoff_contexto,
                    mensaje_usuario
                )
                if success:
                    conversacion_actual.handoff_notified = True
            else:
                # Es un mensaje posterior durante el handoff
                whatsapp_handoff_service.notify_agent_new_message(
                    numero_telefono,
                    profile_name or '',
                    mensaje_usuario
                )
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
        
        # Si durante el procesamiento se activó el handoff, notificar al agente vía WhatsApp
        try:
            conversacion_post = conversation_manager.get_conversacion(numero_telefono)
            if (
                (conversacion_post.atendido_por_humano or conversacion_post.estado == EstadoConversacion.ATENDIDO_POR_HUMANO)
                and not conversacion_post.handoff_notified
            ):
                # Notificar al agente sobre el nuevo handoff
                success = whatsapp_handoff_service.notify_agent_new_handoff(
                    numero_telefono,
                    profile_name or '',
                    conversacion_post.mensaje_handoff_contexto or mensaje_usuario,
                    mensaje_usuario
                )
                if success:
                    conversacion_post.handoff_notified = True
                    logger.info(f"✅ Handoff notificado al agente para cliente {numero_telefono}")
        except Exception as e:
            logger.error(f"Error notificando handoff al agente: {e}")

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
        
        # Extraer root thread_ts del payload de Slack
        # Preferir message.thread_ts (raíz del hilo), luego container.message_ts (raíz),
        # y por último message.ts (puede ser el ts del propio mensaje hijo)
        thread_ts = (
            payload.get("message", {}).get("thread_ts", "") or
            payload.get("container", {}).get("message_ts", "") or
            payload.get("message", {}).get("ts", "") or
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
                # Abrir modal para escribir respuesta y enviar a WhatsApp
                try:
                    private_metadata = json.dumps({
                        "thread_ts": thread_ts,
                        "channel_id": channel_id
                    })
                    view = {
                        "type": "modal",
                        "callback_id": "reply_to_client_modal",
                        "title": {"type": "plain_text", "text": "Responder al cliente"},
                        "submit": {"type": "plain_text", "text": "Enviar"},
                        "close": {"type": "plain_text", "text": "Cancelar"},
                        "private_metadata": private_metadata,
                        "blocks": [
                            {
                                "type": "input",
                                "block_id": "message_input",
                                "element": {
                                    "type": "plain_text_input",
                                    "action_id": "message",
                                    "multiline": True,
                                    "placeholder": {"type": "plain_text", "text": "Escribe tu respuesta para WhatsApp"}
                                },
                                "label": {"type": "plain_text", "text": "Mensaje"}
                            }
                        ]
                    }
                    slack_service.open_modal(trigger_id, view)
                    slack_service.respond_interaction(response_url, "✍️ Modal abierto para responder al cliente")
                except Exception as e:
                    logger.error(f"❌ Error abriendo modal: {e}")
                    slack_service.respond_interaction(response_url, "❌ No se pudo abrir el modal")
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
        bot_id = event.get("bot_id")
        subtype = event.get("subtype")
        text = event.get("text", "").strip()
        
        # Solo procesar mensajes en hilos
        if not thread_ts:
            return
        
        # Ignorar mensajes generados por bots (incluyendo este bot) o actualizaciones del sistema
        # Slack envía mensajes de bots con bot_id o con subtype=bot_message
        if bot_id or subtype in ("bot_message", "message_changed", "message_deleted"):
            return

        # Buscar conversación con modo conversación activa
        for conv in conversation_manager.conversaciones.values():
            if (conv.slack_thread_ts == thread_ts and 
                conv.slack_channel_id == channel and 
                conv.modo_conversacion_activa):
                
                # Verificar que no sea un mensaje del bot por user id
                bot_user_id = slack_service.get_bot_user_id()
                if user == bot_user_id:
                    continue
                
                # Safety: no reenviar a WhatsApp los mensajes de contexto publicados por nosotros
                if text.startswith("Nuevo mensaje del cliente") or text.startswith("🔄 *Nueva solicitud de agente humano*"):
                    return
                
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

async def handle_agent_message(agent_phone: str, message: str, profile_name: str = ""):
    """
    Maneja mensajes del agente humano.
    
    Args:
        agent_phone: Número de teléfono del agente
        message: Mensaje del agente
        profile_name: Nombre del perfil del agente (si está disponible)
    """
    try:
        # Import local para evitar NameError
        from datetime import datetime
        logger.info(f"Procesando mensaje del agente {agent_phone}: {message}")
        
        # Verificar si es un comando de resolución
        if whatsapp_handoff_service.is_resolution_command(message):
            # Buscar conversaciones activas en handoff
            resolved_count = 0
            # Tomar snapshot para evitar "dictionary changed size during iteration"
            for phone, conv in list(conversation_manager.conversaciones.items()):
                if conv.atendido_por_humano or conv.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
                    # En lugar de cerrar inmediatamente, enviar pregunta de resolución
                    if not conv.resolution_question_sent:
                        success = whatsapp_handoff_service.send_resolution_question_to_client(phone)
                        if success:
                            conv.resolution_question_sent = True
                            conv.resolution_question_sent_at = datetime.utcnow()
                            resolved_count += 1
                            
                            # Notificar al agente
                            confirmation_msg = f"✅ Pregunta de resolución enviada al cliente {phone}. Se cerrará automáticamente si no responde en 10 minutos."
                            twilio_service.send_whatsapp_message(agent_phone, confirmation_msg)
                    else:
                        # Si ya se envió la pregunta, finalizar directamente
                        conversation_manager.finalizar_conversacion(phone)
                        cierre_msg = "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
                        twilio_service.send_whatsapp_message(phone, cierre_msg)
                        whatsapp_handoff_service.notify_handoff_resolved(phone, conv.nombre_usuario or "")
                        resolved_count += 1
            
            if resolved_count == 0:
                no_handoff_msg = "ℹ️ No hay conversaciones activas en handoff para finalizar."
                twilio_service.send_whatsapp_message(agent_phone, no_handoff_msg)
            return
        
        # Si no es comando de resolución, buscar conversaciones en handoff para responder
        # El agente debe especificar a qué cliente responder
        # Por ahora, asumimos que el agente está respondiendo a la conversación más reciente en handoff
        
        # Buscar la conversación más reciente en handoff
        latest_handoff_conv = None
        latest_timestamp = None
        
        for phone, conv in conversation_manager.conversaciones.items():
            if conv.atendido_por_humano or conv.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
                if conv.handoff_started_at and (latest_timestamp is None or conv.handoff_started_at > latest_timestamp):
                    latest_handoff_conv = conv
                    latest_timestamp = conv.handoff_started_at
        
        if latest_handoff_conv:
            # Enviar respuesta del agente al cliente
            success = whatsapp_handoff_service.send_agent_response_to_client(
                latest_handoff_conv.numero_telefono, 
                message
            )
            
            if success:
                # Confirmar al agente que el mensaje se envió
                confirmation_msg = f"✅ Mensaje enviado al cliente {latest_handoff_conv.numero_telefono}"
                twilio_service.send_whatsapp_message(agent_phone, confirmation_msg)
            else:
                # Notificar error al agente
                error_msg = f"❌ Error enviando mensaje al cliente {latest_handoff_conv.numero_telefono}"
                twilio_service.send_whatsapp_message(agent_phone, error_msg)
        else:
            # No hay conversaciones en handoff
            no_handoff_msg = "ℹ️ No hay conversaciones activas en handoff. Para finalizar conversaciones, usa: /resuelto"
            twilio_service.send_whatsapp_message(agent_phone, no_handoff_msg)
            
    except Exception as e:
        logger.error(f"Error en handle_agent_message: {e}")
        # Enviar mensaje de error al agente
        try:
            error_msg = f"❌ Error procesando tu mensaje: {str(e)}"
            twilio_service.send_whatsapp_message(agent_phone, error_msg)
        except Exception:
            pass

@app.post("/reset-conversation")
async def reset_conversation(numero_telefono: str = Form(...)):
    """Endpoint para resetear una conversación específica (útil para debugging)"""
    try:
        conversation_manager.reset_conversacion(numero_telefono)
        return {"message": f"Conversación resetada para {numero_telefono}"}
    except Exception as e:
        logger.error(f"Error reseteando conversación: {str(e)}")
        raise HTTPException(status_code=500, detail="Error reseteando conversación")

@app.post("/debug/test-handoff")
async def debug_test_handoff(token: str = Form(...)):
    """Endpoint temporal para debuggear el handoff - ENVIAR MENSAJE DIRECTO AL AGENTE"""
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Obtener número del agente
        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
        if not agent_number:
            return {"error": "AGENT_WHATSAPP_NUMBER no configurado"}
        
        # Mensaje de prueba
        from datetime import datetime
        test_message = f"""🧪 *TEST DE HANDOFF - DEBUG*

Este es un mensaje de prueba para verificar que el sistema de handoff funciona correctamente.

Si recibes este mensaje, el sistema está funcionando ✅

Cliente de prueba: +5491123456789
Mensaje: 'quiero hablar con un humano'

Timestamp: {datetime.utcnow().isoformat()}"""

        # Enviar mensaje directo al agente
        success = twilio_service.send_whatsapp_message(agent_number, test_message)
        
        if success:
            return {
                "status": "success",
                "message": f"Mensaje de prueba enviado a {agent_number}",
                "agent_number": agent_number
            }
        else:
            return {
                "status": "error", 
                "message": f"Error enviando mensaje a {agent_number}",
                "agent_number": agent_number
            }
            
    except Exception as e:
        logger.error(f"Error en debug test handoff: {e}")
        return {"error": f"Error interno: {str(e)}"}

@app.post("/debug/test-handoff-full")
async def debug_test_handoff_full(token: str = Form(...)):
    """Endpoint temporal para debuggear el handoff completo - SIMULAR CONVERSACIÓN REAL"""
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Simular una conversación completa
        test_phone = "+5491123456789"
        test_name = "Cliente Test"
        test_message = "quiero hablar con un humano"
        
        # 1. Procesar mensaje como si fuera del cliente
        respuesta = ChatbotRules.procesar_mensaje(test_phone, test_message, test_name)
        
        # 2. Verificar si se activó el handoff
        conversacion = conversation_manager.get_conversacion(test_phone)
        handoff_activated = conversacion.atendido_por_humano or conversacion.estado == EstadoConversacion.ATENDIDO_POR_HUMANO
        
        # 3. Si se activó, notificar al agente
        if handoff_activated and not conversacion.handoff_notified:
            success = whatsapp_handoff_service.notify_agent_new_handoff(
                test_phone,
                test_name,
                conversacion.mensaje_handoff_contexto or test_message,
                test_message
            )
            if success:
                conversacion.handoff_notified = True
        
        return {
            "status": "success",
            "handoff_activated": handoff_activated,
            "handoff_notified": conversacion.handoff_notified,
            "bot_response": respuesta,
            "conversation_state": conversacion.estado,
            "agent_number": os.getenv("AGENT_WHATSAPP_NUMBER", "")
        }
        
    except Exception as e:
        logger.error(f"Error en debug test handoff full: {e}")
        return {"error": f"Error interno: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)