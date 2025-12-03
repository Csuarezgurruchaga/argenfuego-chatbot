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
from chatbot.models import EstadoConversacion, ConversacionData
from services.meta_whatsapp_service import meta_whatsapp_service
from services.whatsapp_handoff_service import whatsapp_handoff_service
from services.email_service import email_service
from services.error_reporter import error_reporter, ErrorTrigger
from services.metrics_service import metrics_service
from services.otel_metrics_service import init_metrics, otel_metrics
from services.otel_middleware import OTelMetricsMiddleware

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear la aplicación FastAPI
app = FastAPI(
    title="Argenfuego Chatbot API",
    description="Chatbot basado en reglas para WhatsApp Cloud API",
    version="1.0.0"
)

# Inicializar OpenTelemetry metrics (envía a Datadog)
init_metrics()

# Agregar middleware para métricas HTTP automáticas
app.add_middleware(OTelMetricsMiddleware)

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

            # Verificar timeout de oferta de encuesta (2 minutos)
            if conv.estado == EstadoConversacion.ESPERANDO_RESPUESTA_ENCUESTA and conv.survey_offer_sent_at:
                if (ahora - conv.survey_offer_sent_at) > timedelta(minutes=2):
                    should_close = True
                    close_reason = "Oferta de encuesta sin respuesta"

            # Verificar timeout de encuesta de satisfacción (15 minutos)
            elif conv.estado == EstadoConversacion.ENCUESTA_SATISFACCION and conv.survey_sent_at:
                if (ahora - conv.survey_sent_at) > timedelta(minutes=15):
                    should_close = True
                    close_reason = "Encuesta de satisfacción sin completar"

            # Verificar timeout de pregunta de resolución (10 minutos)
            elif conv.resolution_question_sent and conv.resolution_question_sent_at:
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
                    # Enviar mensaje de cierre al cliente
                    if close_reason == "Oferta de encuesta sin respuesta":
                        # Cierre silencioso cuando no responde a oferta de encuesta (no enviar mensaje)
                        conv.survey_accepted = None  # Registrar como timeout
                        logger.info(f"⏱️ Timeout de oferta de encuesta para {conv.numero_telefono}")
                    elif close_reason == "Encuesta de satisfacción sin completar":
                        meta_whatsapp_service.send_text_message(conv.numero_telefono, "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅")
                    elif close_reason == "Pregunta de resolución sin respuesta":
                        meta_whatsapp_service.send_text_message(conv.numero_telefono, "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅")
                    else:
                        meta_whatsapp_service.send_text_message(conv.numero_telefono, "Esta conversación se finalizará por inactividad. ¡Muchas gracias por contactarnos! 🕒")
                except Exception:
                    pass

                # Verificar si es la conversación activa en la cola
                active_phone = conversation_manager.get_active_handoff()
                if active_phone == conv.numero_telefono:
                    # Era la conversación activa, usar close_active_handoff
                    next_phone = conversation_manager.close_active_handoff()
                    cerradas += 1

                    # Si hay siguiente conversación, notificar al agente
                    if next_phone:
                        try:
                            next_conv = conversation_manager.get_conversacion(next_phone)
                            position = 1
                            total = conversation_manager.get_queue_size()
                            notification = _format_handoff_activated_notification(next_conv, position, total)
                            agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                            meta_whatsapp_service.send_text_message(agent_number, notification)
                        except Exception as e:
                            logger.error(f"Error notificando siguiente handoff después de TTL: {e}")
                else:
                    # No es la activa, solo remover de cola
                    conversation_manager.remove_from_handoff_queue(conv.numero_telefono)
                    conversation_manager.finalizar_conversacion(conv.numero_telefono)
                    cerradas += 1

                logger.info(f"Conversación {conv.numero_telefono} cerrada por: {close_reason}")
    
    return {"closed": cerradas}

@app.get("/webhook/whatsapp")
async def webhook_whatsapp_verify(request: Request):
    """
    Webhook GET para verificación de WhatsApp Cloud API (Meta).
    Meta envía este request para validar el webhook durante la configuración inicial.
    """
    try:
        # Extraer parámetros de query
        params = request.query_params
        mode = params.get('hub.mode', '')
        token = params.get('hub.verify_token', '')
        challenge = params.get('hub.challenge', '')
        
        logger.info(f"=== WEBHOOK VERIFICATION REQUEST ===")
        logger.info(f"Mode: {mode}")
        logger.info(f"Token provided: {token[:10]}..." if token else "Token: None")
        logger.info(f"Challenge: {challenge}")
        
        # Verificar con el servicio
        verified_challenge = meta_whatsapp_service.verify_webhook_token(mode, token, challenge)
        
        if verified_challenge:
            # Retornar el challenge como texto plano
            logger.info("✅ Webhook verificado exitosamente")
            return PlainTextResponse(verified_challenge, status_code=200)
        else:
            # Verificación fallida
            logger.error("❌ Verificación de webhook fallida")
            return PlainTextResponse("Forbidden", status_code=403)
            
    except Exception as e:
        logger.error(f"Error en verificación de webhook: {str(e)}")
        return PlainTextResponse("Error", status_code=500)

@app.post("/webhook/whatsapp")
async def webhook_whatsapp_receive(request: Request):
    """
    Webhook POST para recibir mensajes y actualizaciones de WhatsApp Cloud API (Meta).
    """
    try:
        # Leer el cuerpo del request como bytes (necesario para validar firma)
        body_bytes = await request.body()
        
        # Obtener firma del header
        signature = request.headers.get('X-Hub-Signature-256', '')
        
        client_ip = request.client.host if request.client else "unknown"
        logger.info("Webhook recibido desde %s", client_ip)
        logger.debug("Headers: %s", dict(request.headers))

        # Validar firma HMAC
        if not meta_whatsapp_service.validate_webhook_signature(body_bytes, signature):
            logger.error("❌ Firma de webhook inválida - request rechazado (client=%s)", client_ip)
            return PlainTextResponse("Forbidden", status_code=403)
        
        # Parsear JSON
        webhook_data = json.loads(body_bytes.decode('utf-8'))
        
        logger.info("=== WEBHOOK WHATSAPP RECIBIDO ===")
        logger.debug("Payload completo: %s", json.dumps(webhook_data))
        
        # Extraer datos de mensaje
        message_data = meta_whatsapp_service.extract_message_data(webhook_data)
        
        if message_data:
            numero_telefono, mensaje_usuario, message_id, profile_name, message_type = message_data

            logger.info(
                f"Mensaje recibido de {numero_telefono} ({profile_name or 'sin nombre'}): {mensaje_usuario}"
            )

            # Verificar si el mensaje viene del agente humano
            if whatsapp_handoff_service.is_agent_message(numero_telefono):
                await handle_agent_message(numero_telefono, mensaje_usuario, profile_name)
                return PlainTextResponse("", status_code=200)

            # Manejar botones/listas interactivos nativos de Meta
            if message_type == 'interactive':
                if not mensaje_usuario:
                    logger.warning(
                        f"Interacción sin ID de botón/lista desde {numero_telefono}: {message_id}"
                    )
                    return PlainTextResponse("", status_code=200)

                respuesta_interactiva = await handle_interactive_button(
                    numero_telefono,
                    mensaje_usuario,
                    profile_name
                )

                if respuesta_interactiva:
                    meta_whatsapp_service.send_text_message(numero_telefono, respuesta_interactiva)

                return PlainTextResponse("", status_code=200)

            # Fallback para contenidos no-texto
            if not mensaje_usuario or not mensaje_usuario.strip():
                logger.info(
                    f"Mensaje de tipo {message_type or 'desconocido'} sin texto manejable de {numero_telefono}"
                )
                meta_whatsapp_service.send_text_message(
                    numero_telefono,
                    "Recibi tu mensaje, pero actualmente este canal solo procesa texto. Por favor, escribi tu consulta."
                )
                return PlainTextResponse("", status_code=200)
            
            # Manejar mensajes posteriores a cierre reciente (agradecimientos)
            if conversation_manager.was_finalized_recently(numero_telefono):
                if ChatbotRules.es_mensaje_agradecimiento(mensaje_usuario):
                    mensaje_gracias = ChatbotRules.get_mensaje_post_finalizado_gracias()
                    if mensaje_gracias:
                        meta_whatsapp_service.send_text_message(numero_telefono, mensaje_gracias)
                    logger.info(f"🙏 Mensaje de agradecimiento ignorado para {numero_telefono}")
                    return PlainTextResponse("", status_code=200)
                else:
                    conversation_manager.clear_recently_finalized(numero_telefono)
            
            # Obtener conversación actual
            conversacion_actual = conversation_manager.get_conversacion(numero_telefono)
            
            # Verificar si está esperando respuesta de encuesta (PRIORIDAD MUY ALTA)
            if conversacion_actual.estado == EstadoConversacion.ESPERANDO_RESPUESTA_ENCUESTA:
                from services.survey_service import survey_service
                from datetime import datetime
                
                # Parsear respuesta (1=sí, 2=no)
                respuesta = mensaje_usuario.strip().lower()
                
                # Keywords de aceptación
                acepta_keywords = ['1', '1️⃣', 'si', 'sí', 'yes', 'ok', 'dale', 'con gusto', 'acepto']
                # Keywords de rechazo
                rechaza_keywords = ['2', '2️⃣', 'no', 'nope', 'no gracias', 'no quiero', 'paso']
                
                if any(kw in respuesta for kw in acepta_keywords):
                    # Cliente acepta la encuesta
                    conversacion_actual.survey_accepted = True
                    
                    # Iniciar encuesta
                    success = survey_service.send_survey(numero_telefono, conversacion_actual)
                    
                    if success:
                        logger.info(f"✅ Cliente {numero_telefono} aceptó encuesta, primera pregunta enviada")
                    else:
                        logger.error(f"❌ Error enviando primera pregunta de encuesta a {numero_telefono}")
                        # Fallback: cerrar conversación
                        meta_whatsapp_service.send_text_message(
                            numero_telefono,
                            "¡Gracias por tu tiempo! Que tengas un buen día. ✅"
                        )
                        
                        # Verificar si esta conversación es la activa antes de cerrar
                        active_phone = conversation_manager.get_active_handoff()
                        if active_phone == numero_telefono:
                            conversation_manager.close_active_handoff()
                        else:
                            conversation_manager.remove_from_handoff_queue(numero_telefono)
                            conversation_manager.finalizar_conversacion(numero_telefono)
                    
                    return PlainTextResponse("", status_code=200)
                
                elif any(kw in respuesta for kw in rechaza_keywords):
                    # Cliente rechaza la encuesta
                    conversacion_actual.survey_accepted = False
                    
                    # Enviar mensaje de agradecimiento y cerrar
                    meta_whatsapp_service.send_text_message(
                        numero_telefono,
                        "¡Gracias por tu tiempo! Que tengas un buen día. ✅"
                    )
                    
                    # Verificar si esta conversación es la activa
                    active_phone = conversation_manager.get_active_handoff()
                    
                    if active_phone == numero_telefono:
                        # Es la conversación activa, usar close_active_handoff
                        next_phone = conversation_manager.close_active_handoff()
                        
                        logger.info(f"✅ Cliente {numero_telefono} rechazó encuesta, conversación cerrada (era activa)")
                        
                        # Notificar al agente si hay siguiente conversación
                        if next_phone:
                            agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                            if agent_number:
                                next_conv = conversation_manager.get_conversacion(next_phone)
                                position = 1
                                total = conversation_manager.get_queue_size()
                                notification = _format_handoff_activated_notification(next_conv, position, total)
                                meta_whatsapp_service.send_text_message(agent_number, notification)
                    else:
                        # NO es la conversación activa, solo removerla de la cola sin afectar la activa
                        conversation_manager.remove_from_handoff_queue(numero_telefono)
                        conversation_manager.finalizar_conversacion(numero_telefono)
                        
                        logger.info(f"✅ Cliente {numero_telefono} rechazó encuesta, conversación cerrada (NO era activa)")
                    
                    return PlainTextResponse("", status_code=200)
                else:
                    # Respuesta no reconocida, pedir que responda con 1 o 2
                    meta_whatsapp_service.send_text_message(
                        numero_telefono,
                        "Por favor responde con:\n1️⃣ para aceptar la encuesta\n2️⃣ para omitirla"
                    )
                    return PlainTextResponse("", status_code=200)
            
            # Verificar si está en encuesta de satisfacción (PRIORIDAD ALTA)
            if conversacion_actual.estado == EstadoConversacion.ENCUESTA_SATISFACCION:
                # Procesar respuesta de encuesta
                from services.survey_service import survey_service
                
                survey_complete, next_message = survey_service.process_survey_response(
                    numero_telefono, mensaje_usuario, conversacion_actual
                )
                
                if next_message:
                    # Enviar siguiente pregunta o mensaje de finalización
                    meta_whatsapp_service.send_text_message(numero_telefono, next_message)
                
                if survey_complete:
                    # Encuesta completada, finalizar conversación
                    # Verificar si esta conversación es la activa
                    active_phone = conversation_manager.get_active_handoff()
                    
                    if active_phone == numero_telefono:
                        # Es la conversación activa, cerrar y activar siguiente
                        next_phone = conversation_manager.close_active_handoff()
                        logger.info(f"✅ Encuesta completada y conversación finalizada para {numero_telefono} (era activa)")
                        
                        # Notificar al agente si hay siguiente conversación
                        if next_phone:
                            agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                            if agent_number:
                                try:
                                    next_conv = conversation_manager.get_conversacion(next_phone)
                                    position = 1
                                    total = conversation_manager.get_queue_size()
                                    notification = _format_handoff_activated_notification(next_conv, position, total)
                                    meta_whatsapp_service.send_text_message(agent_number, notification)
                                except Exception as e:
                                    logger.error(f"Error notificando siguiente handoff después de encuesta: {e}")
                    else:
                        # NO es la conversación activa, solo removerla de la cola sin afectar la activa
                        conversation_manager.remove_from_handoff_queue(numero_telefono)
                        conversation_manager.finalizar_conversacion(numero_telefono)
                        logger.info(f"✅ Encuesta completada y conversación finalizada para {numero_telefono} (NO era activa)")
                
                return PlainTextResponse("", status_code=200)
            
            # Si está en handoff, reenviar al agente
            if conversacion_actual.atendido_por_humano or conversacion_actual.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
                # Notificar al agente vía WhatsApp con indicación de posición en cola
                active_phone = conversation_manager.get_active_handoff()
                is_active = (active_phone == numero_telefono)
                
                if conversacion_actual.mensaje_handoff_contexto and not conversacion_actual.handoff_notified:
                    # Es el primer mensaje del handoff, incluir contexto completo
                    # TODO: Implementar envío de botones con Meta API si es necesario
                    # Por ahora, enviar notificación simple
                    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                    if agent_number:
                        notification = f"""🔄 *Solicitud de handoff*

Cliente: {profile_name or 'Sin nombre'} ({numero_telefono})

📝 *Mensaje que disparó el handoff:*
{conversacion_actual.mensaje_handoff_contexto or mensaje_usuario}

ℹ️ *Instrucciones:*
• Responde en este mismo chat y enviaremos tu mensaje al cliente automáticamente.
• No es necesario escribirle al número del cliente.
• Para cerrar la conversación, responde con: /resuelto"""
                        
                        meta_whatsapp_service.send_text_message(agent_number, notification)
                        conversacion_actual.handoff_notified = True
                else:
                    # Es un mensaje posterior durante el handoff
                    # Obtener posición si no es activo
                    position = None if is_active else conversation_manager.get_queue_position(numero_telefono)
                    
                    # Guardar mensaje del cliente en historial
                    conversation_manager.add_message_to_history(numero_telefono, "client", mensaje_usuario)
                    
                    # Enviar notificación de mensaje con indicador de posición
                    notification = _format_client_message_notification(
                        numero_telefono,
                        profile_name or '',
                        mensaje_usuario,
                        is_active,
                        position
                    )
                    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                    meta_whatsapp_service.send_text_message(agent_number, notification)
                    
                    # Si no es activo, agregar recordatorio
                    if not is_active and position:
                        reminder = f"ℹ️ Este mensaje es del cliente en posición #{position}. Los mensajes que escribas irán al cliente activo. Usa /next para cambiar o /queue para ver la cola completa."
                        meta_whatsapp_service.send_text_message(agent_number, reminder)
                
                try:
                    from datetime import datetime
                    conversacion_actual.last_client_message_at = datetime.utcnow()
                except Exception:
                    pass
                
                return PlainTextResponse("", status_code=200)
            
            # Procesar el mensaje con el chatbot (incluyendo nombre del perfil)
            respuesta = ChatbotRules.procesar_mensaje(numero_telefono, mensaje_usuario, profile_name)
            
            # Enviar respuesta via WhatsApp solo si no está vacía
            if respuesta and respuesta.strip():
                mensaje_enviado = meta_whatsapp_service.send_text_message(numero_telefono, respuesta)
                
                if not mensaje_enviado:
                    logger.error(f"Error enviando mensaje a {numero_telefono}")
            else:
                logger.info(f"Respuesta vacía, no se envía mensaje a {numero_telefono}")
            
            # Si durante el procesamiento se activó el handoff, agregar a cola y notificar al agente
            try:
                conversacion_post = conversation_manager.get_conversacion(numero_telefono)
                if (
                    (conversacion_post.atendido_por_humano or conversacion_post.estado == EstadoConversacion.ATENDIDO_POR_HUMANO)
                    and not conversacion_post.handoff_notified
                ):
                    # Agregar a la cola (esto activa automáticamente si no hay activo)
                    position = conversation_manager.add_to_handoff_queue(numero_telefono)
                    total = conversation_manager.get_queue_size()
                    otel_metrics.set_handoff_queue_size(total)
                    
                    # Determinar tipo de notificación
                    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                    
                    if position == 1:
                        # Es el activo, notificar como activado
                        notification = _format_handoff_activated_notification(
                            conversacion_post,
                            position,
                            total
                        )
                        success = meta_whatsapp_service.send_text_message(agent_number, notification)
                    else:
                        # Está en cola, notificar con contexto
                        active_phone = conversation_manager.get_active_handoff()
                        active_conv = conversation_manager.get_conversacion(active_phone)
                        
                        notification = _format_handoff_queued_notification(
                            conversacion_post,
                            position,
                            total,
                            active_conv
                        )
                        success = meta_whatsapp_service.send_text_message(agent_number, notification)
                    
                    if success:
                        conversacion_post.handoff_notified = True
                        logger.info(f"✅ Handoff notificado para cliente {numero_telefono} (posición {position}/{total})")
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
                        otel_metrics.record_lead_processed()
                    except Exception:
                        pass
                    # Enviar mensaje de confirmación
                    mensaje_final = ChatbotRules.get_mensaje_final_exito()
                    meta_whatsapp_service.send_text_message(numero_telefono, mensaje_final)
                    
                    # Finalizar la conversación
                    conversation_manager.finalizar_conversacion(numero_telefono)
                    
                    logger.info(f"Lead procesado exitosamente para {numero_telefono}")
                else:
                    # Error enviando email
                    error_msg = "❌ Hubo un error procesando tu solicitud. Por favor intenta nuevamente más tarde."
                    meta_whatsapp_service.send_text_message(numero_telefono, error_msg)
                    logger.error(f"Error enviando email para {numero_telefono}")
        
        # Extraer datos de estado de mensaje (opcional, para métricas)
        status_data = meta_whatsapp_service.extract_status_data(webhook_data)
        
        if status_data:
            message_status = status_data.get('status', '')
            message_id = status_data.get('message_id', '')
            
            logger.info(f"Status update recibido - ID: {message_id}, Status: {message_status}")
            
            # Registrar métricas
            if message_status == 'sent':
                metrics_service.on_message_sent()
            elif message_status == 'delivered':
                metrics_service.on_message_delivered()
            elif message_status == 'failed':
                metrics_service.on_message_failed()
            elif message_status == 'read':
                metrics_service.on_message_read()
        
        # Siempre retornar 200 para que Meta no reintente
        return PlainTextResponse("", status_code=200)
        
    except Exception as e:
        logger.error(f"Error en webhook de WhatsApp: {str(e)}")
        # Reporte estructurado de excepción
        try:
            error_reporter.capture_exception(
                e,
                {
                    "webhook_type": "whatsapp_meta",
                    "error": str(e)
                }
            )
        except Exception:
            pass
        return PlainTextResponse("Error", status_code=500)

@app.post("/agent/reply")
async def agent_reply(to: str = Form(...), body: str = Form(...), token: str = Form(...)):
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        sent = meta_whatsapp_service.send_text_message(to, body)
        if not sent:
            raise HTTPException(status_code=500, detail="Failed to send message")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"agent_reply error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/agent/close")
async def agent_close(to: str = Form(...), token: str = Form(...)):
    if token != os.getenv("AGENT_API_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        conversation_manager.finalizar_conversacion(to)
        cierre_msg = "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
        meta_whatsapp_service.send_text_message(to, cierre_msg)
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

def _format_handoff_activated_notification(conversacion: ConversacionData, position: int, total: int) -> str:
    """
    Genera notificación cuando se activa un handoff.

    Args:
        conversacion: Datos de la conversación
        position: Posición en la cola (1-indexed)
        total: Total de conversaciones en cola

    Returns:
        str: Mensaje formateado
    """
    nombre = conversacion.nombre_usuario or "Sin nombre"
    mensaje_contexto = conversacion.mensaje_handoff_contexto or "N/A"

    # Truncar mensaje si es muy largo
    if len(mensaje_contexto) > 100:
        mensaje_contexto = mensaje_contexto[:100] + "..."

    return f"""💬 *HANDOFF ACTIVADO* [{position}/{total}]

*Cliente:* {nombre}
*Tel:* {conversacion.numero_telefono}
*Mensaje inicial:* "{mensaje_contexto}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💬 Escribe tu mensaje para responder a {nombre}.

*Comandos disponibles:*
• `/done` - Finalizar y pasar al siguiente
• `/queue` - Ver cola completa
• `/help` - Ver todos los comandos"""


def _format_handoff_queued_notification(conversacion: ConversacionData, position: int, total: int, active_conv: ConversacionData) -> str:
    """
    Genera notificación cuando un handoff entra en cola.

    Args:
        conversacion: Conversación que entra en cola
        position: Posición en cola (1-indexed)
        total: Total de conversaciones
        active_conv: Conversación actualmente activa

    Returns:
        str: Mensaje formateado
    """
    nombre = conversacion.nombre_usuario or "Sin nombre"
    mensaje_contexto = conversacion.mensaje_handoff_contexto or "N/A"

    # Truncar mensaje si es muy largo
    if len(mensaje_contexto) > 50:
        mensaje_contexto = mensaje_contexto[:50] + "..."

    nombre_activo = active_conv.nombre_usuario or "Cliente actual"

    return f"""💬 *NUEVO HANDOFF EN COLA* [#{position}/{total}]

*Cliente:* {nombre}
*Tel:* {conversacion.numero_telefono}
*Mensaje:* "{mensaje_contexto}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 *Cola actual:*
  [ACTIVO] 🟢 {nombre_activo}
  [#{position}] ⏳ {nombre} ← *NUEVA*

Continúa con {nombre_activo} o usa `/next` para cambiar."""


def _format_client_message_notification(numero_telefono: str, nombre: str, mensaje: str, is_active: bool, position: int = None) -> str:
    """
    Genera notificación de mensaje de cliente (activo o en cola).

    Args:
        numero_telefono: Número del cliente
        nombre: Nombre del cliente
        mensaje: Mensaje del cliente
        is_active: Si es la conversación activa
        position: Posición en cola si no es activo

    Returns:
        str: Mensaje formateado
    """
    nombre_display = nombre or "Cliente"

    # Truncar mensaje si es muy largo
    mensaje_display = mensaje
    if len(mensaje) > 100:
        mensaje_display = mensaje[:100] + "..."

    if is_active:
        return f"💬 *{nombre_display}:* \"{mensaje_display}\""
    else:
        return f"💬 *[#{position}] {nombre_display}:* \"{mensaje_display}\" (en cola)"


async def handle_interactive_button(numero_telefono: str, button_id: str, profile_name: str = "") -> str:
    """
    Maneja las respuestas de botones interactivos
    
    Args:
        numero_telefono: Número de teléfono del usuario
        button_id: ID del botón presionado
        profile_name: Nombre del perfil del usuario
        
    Returns:
        str: Respuesta a enviar al usuario (si hay alguna)
    """
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        from chatbot.models import EstadoConversacion, TipoConsulta
        
        logger.info(f"Procesando botón {button_id} de {numero_telefono}")
        
        # Obtener conversación actual
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        # Guardar nombre de usuario si es la primera vez que lo vemos
        if profile_name and not conversacion.nombre_usuario:
            conversation_manager.set_nombre_usuario(numero_telefono, profile_name)
        
        # Manejar diferentes tipos de botones
        if button_id == "presupuesto":
            conversation_manager.set_tipo_consulta(numero_telefono, TipoConsulta.PRESUPUESTO)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
            return ChatbotRules.get_mensaje_inicio_secuencial(TipoConsulta.PRESUPUESTO)
            
        elif button_id == "urgencia":
            conversation_manager.set_tipo_consulta(numero_telefono, TipoConsulta.URGENCIA)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
            return ChatbotRules.get_mensaje_inicio_secuencial(TipoConsulta.URGENCIA)
            
        elif button_id == "otras":
            conversation_manager.set_tipo_consulta(numero_telefono, TipoConsulta.OTRAS)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
            return ChatbotRules.get_mensaje_inicio_secuencial(TipoConsulta.OTRAS)
            
        elif button_id == "volver_menu":
            # Limpiar datos temporales y volver al menú
            conversation_manager.clear_datos_temporales(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            # Enviar menú interactivo
            ChatbotRules.send_menu_interactivo(numero_telefono, conversacion.nombre_usuario)
            return ""  # El menú se envía directamente
            
        elif button_id == "finalizar_chat":
            # Finalizar conversación
            conversation_manager.finalizar_conversacion(numero_telefono)
            return "¡Gracias por contactarnos! 👋 Esperamos poder ayudarte en el futuro."
            
        elif button_id == "si":
            # Confirmar datos
            if conversacion.estado == EstadoConversacion.CONFIRMANDO:
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.ENVIANDO)
                return "⏳ Procesando tu solicitud..."
            else:
                return "No hay nada que confirmar en este momento."
                
        elif button_id == "no":
            # Corregir datos
            if conversacion.estado == EstadoConversacion.CONFIRMANDO:
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.CORRIGIENDO)
                return ChatbotRules._get_mensaje_pregunta_campo_a_corregir()
            else:
                return "No hay datos para corregir en este momento."
                
        elif button_id == "menu":
            # Volver al menú principal
            conversation_manager.clear_datos_temporales(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            # Enviar menú interactivo
            ChatbotRules.send_menu_interactivo(numero_telefono, conversacion.nombre_usuario)
            return ""  # El menú se envía directamente
            
        else:
            logger.warning(f"Botón no reconocido: {button_id}")
            return "No reconozco ese botón. Por favor, usa los botones disponibles o escribe tu mensaje."
            
    except Exception as e:
        logger.error(f"Error en handle_interactive_button: {e}")
        return "Hubo un error procesando tu solicitud. Por favor, intenta nuevamente."

async def handle_agent_message(agent_phone: str, message: str, profile_name: str = ""):
    """
    Maneja mensajes del agente humano con sistema de cola FIFO.

    Args:
        agent_phone: Número de teléfono del agente
        message: Mensaje del agente
        profile_name: Nombre del perfil del agente (si está disponible)
    """
    try:
        from services.agent_command_service import agent_command_service

        logger.info(f"Procesando mensaje del agente {agent_phone}: {message}")

        # PASO 1: Verificar si es un comando
        if agent_command_service.is_command(message):
            command = agent_command_service.parse_command(message)

            if command == 'done':
                # Cerrar conversación activa y activar siguiente
                response = agent_command_service.execute_done_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)

                # Si hay nuevo activo, notificar
                new_active = conversation_manager.get_active_handoff()
                if new_active:
                    new_conv = conversation_manager.get_conversacion(new_active)
                    position = 1
                    total = conversation_manager.get_queue_size()
                    notification = _format_handoff_activated_notification(new_conv, position, total)
                    meta_whatsapp_service.send_text_message(agent_phone, notification)
                return

            elif command == 'next':
                # Mover al siguiente sin cerrar
                response = agent_command_service.execute_next_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)

                # Notificar nuevo activo
                new_active = conversation_manager.get_active_handoff()
                if new_active:
                    new_conv = conversation_manager.get_conversacion(new_active)
                    position = 1
                    total = conversation_manager.get_queue_size()
                    notification = _format_handoff_activated_notification(new_conv, position, total)
                    meta_whatsapp_service.send_text_message(agent_phone, notification)
                return

            elif command == 'queue':
                # Mostrar estado de cola
                response = agent_command_service.execute_queue_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)
                return

            elif command == 'help':
                # Mostrar ayuda
                response = agent_command_service.execute_help_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)
                return

            elif command == 'active':
                # Mostrar conversación activa
                response = agent_command_service.execute_active_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)
                return
            
            elif command == 'historial':
                # Mostrar historial de mensajes
                response = agent_command_service.execute_historial_command(agent_phone)
                meta_whatsapp_service.send_text_message(agent_phone, response)
                return

        # PASO 2: Es un mensaje normal, enviar a conversación activa
        active_phone = conversation_manager.get_active_handoff()

        if not active_phone:
            # No hay conversación activa
            no_active_msg = (
                "⚠️ No hay conversación activa.\n\n"
                "Usa /queue para ver las conversaciones en cola."
            )
            meta_whatsapp_service.send_text_message(agent_phone, no_active_msg)
            return

        # Guardar mensaje del agente en historial
        conversation_manager.add_message_to_history(active_phone, "agent", message)
        
        # Enviar mensaje al cliente activo
        success = whatsapp_handoff_service.send_agent_response_to_client(
            active_phone,
            message
        )

        if not success:
            error_msg = f"❌ Error enviando mensaje al cliente {active_phone}"
            meta_whatsapp_service.send_text_message(agent_phone, error_msg)

    except Exception as e:
        logger.error(f"Error en handle_agent_message: {e}")
        try:
            error_msg = f"❌ Error procesando tu mensaje: {str(e)}"
            meta_whatsapp_service.send_text_message(agent_phone, error_msg)
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
        success = meta_whatsapp_service.send_text_message(agent_number, test_message)
        
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

@app.post("/test-bot-flow")
async def test_bot_flow(test_number: str = Form(...)):
    """Endpoint para probar el flujo completo del bot desde un número específico"""
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        
        logger.info(f"🧪 TESTING BOT FLOW para número: {test_number}")
        
        # Resetear conversación
        conversation_manager.reset_conversacion(test_number)
        
        # Simular mensaje "hola"
        respuesta = ChatbotRules.procesar_mensaje(test_number, "hola", "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = meta_whatsapp_service.send_text_message(test_number, respuesta)
            if success:
                return {
                    "message": "Flujo de bot probado exitosamente",
                    "test_number": test_number,
                    "response_sent": True
                }
            else:
                return {"error": "Error enviando respuesta del bot"}
        else:
            return {
                "message": "Bot procesó el mensaje (respuesta en background)",
                "test_number": test_number,
                "response_sent": False
            }
            
    except Exception as e:
        logger.error(f"Error en test de bot flow: {str(e)}")
        return {"error": f"Error: {str(e)}"}

@app.post("/test-interactive-buttons")
async def test_interactive_buttons(test_number: str = Form(...)):
    """Endpoint para probar botones interactivos"""
    try:
        from chatbot.rules import ChatbotRules
        
        logger.info(f"🧪 TESTING INTERACTIVE BUTTONS para número: {test_number}")
        
        # Probar menú interactivo
        success = ChatbotRules.send_menu_interactivo(test_number, "Usuario Test")
        
        if success:
            return {
                "message": "Botones interactivos enviados exitosamente",
                "test_number": test_number,
                "button_type": "menu_interactivo"
            }
        else:
            return {"error": "Error enviando botones interactivos"}
            
    except Exception as e:
        logger.error(f"Error en test de botones interactivos: {str(e)}")
        return {"error": f"Error: {str(e)}"}

@app.post("/simulate-client-message")
async def simulate_client_message(test_number: str = Form(...), message: str = Form(...)):
    """Endpoint para simular mensaje de cliente (bypass de detección de agente)"""
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        
        logger.info(f"🧪 SIMULATING CLIENT MESSAGE: {message} from {test_number}")
        
        # Procesar mensaje como si fuera de cliente (no agente)
        respuesta = ChatbotRules.procesar_mensaje(test_number, message, "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = meta_whatsapp_service.send_text_message(test_number, respuesta)
            if success:
                return {
                    "message": "Mensaje de cliente simulado exitosamente",
                    "test_number": test_number,
                    "client_message": message,
                    "bot_response": respuesta,
                    "response_sent": True
                }
            else:
                return {"error": "Error enviando respuesta del bot"}
        else:
            return {
                "message": "Bot procesó el mensaje (respuesta en background)",
                "test_number": test_number,
                "client_message": message,
                "response_sent": False
            }
            
    except Exception as e:
        logger.error(f"Error en simulación de mensaje de cliente: {str(e)}")
        return {"error": f"Error: {str(e)}"}

@app.get("/test-complete-flow")
async def test_complete_flow():
    """Endpoint GET para probar el flujo completo con tu número"""
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        
        # Usar tu número por defecto
        test_number = "+5491135722871"
        
        logger.info(f"🧪 TESTING COMPLETE FLOW para número: {test_number}")
        
        # Resetear conversación
        conversation_manager.reset_conversacion(test_number)
        
        # Simular mensaje "hola"
        respuesta = ChatbotRules.procesar_mensaje(test_number, "hola", "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = meta_whatsapp_service.send_text_message(test_number, respuesta)
            if success:
                return {
                    "message": "Flujo completo probado exitosamente",
                    "test_number": test_number,
                    "response_sent": True,
                    "bot_response": respuesta
                }
            else:
                return {"error": "Error enviando respuesta del bot"}
        else:
            return {
                "message": "Bot procesó el mensaje (respuesta en background)",
                "test_number": test_number,
                "response_sent": False
            }
            
    except Exception as e:
        logger.error(f"Error en test de flujo completo: {str(e)}")
        return {"error": f"Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
