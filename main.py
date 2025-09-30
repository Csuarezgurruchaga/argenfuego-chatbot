import os
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
            
            # Verificar timeout de encuesta de satisfacción (15 minutos)
            if conv.estado == EstadoConversacion.ENCUESTA_SATISFACCION and conv.survey_sent_at:
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
                    if close_reason == "Encuesta de satisfacción sin completar":
                        twilio_service.send_whatsapp_message(conv.numero_telefono, "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅")
                    elif close_reason == "Pregunta de resolución sin respuesta":
                        twilio_service.send_whatsapp_message(conv.numero_telefono, "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅")
                    else:
                        twilio_service.send_whatsapp_message(conv.numero_telefono, "Esta conversación se finalizará por inactividad. ¡Muchas gracias por contactarnos! 🕒")
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
                            twilio_service.send_whatsapp_message(agent_number, notification)
                        except Exception as e:
                            logger.error(f"Error notificando siguiente handoff después de TTL: {e}")
                else:
                    # No es la activa, solo remover de cola
                    conversation_manager.remove_from_handoff_queue(conv.numero_telefono)
                    conversation_manager.finalizar_conversacion(conv.numero_telefono)
                    cerradas += 1

                logger.info(f"Conversación {conv.numero_telefono} cerrada por: {close_reason}")
    
    return {"closed": cerradas}

@app.post("/webhook/status")
async def webhook_status(request: Request):
    """
    Webhook para recibir callbacks de estado de mensajes de Twilio
    """
    try:
        data = await request.form()
        message_sid = data.get('MessageSid', '')
        message_status = data.get('MessageStatus', '')
        
        logger.info(f"Status callback recibido - SID: {message_sid}, Status: {message_status}")
        
        # Registrar métrica según el estado
        if message_status == 'sent':
            metrics_service.on_message_sent()
        elif message_status == 'delivered':
            metrics_service.on_message_delivered()
        elif message_status == 'failed':
            metrics_service.on_message_failed()
        elif message_status == 'undelivered':
            metrics_service.on_message_undelivered()
        elif message_status == 'read':
            metrics_service.on_message_read()
        
        return PlainTextResponse("", status_code=200)
        
    except Exception as e:
        logger.error(f"Error en webhook de status: {str(e)}")
        return PlainTextResponse("Error", status_code=500)

@app.post("/webhook")
async def webhook_whatsapp(request: Request):
    try:
        # Obtener datos del formulario de Twilio
        form_data = await request.form()
        form_dict = dict(form_data)
        
        logger.info(f"Webhook recibido: {form_dict}")
        
        # Verificar si es un mensaje interactivo (botón)
        if 'ButtonText' in form_dict:
            # Es un mensaje de botón interactivo
            numero_telefono, button_id, message_sid, profile_name = twilio_service.extract_interactive_data(form_dict)
            
            if not numero_telefono or not button_id:
                logger.warning("Datos incompletos en el webhook de botón")
                return PlainTextResponse("", status_code=200)
            
            logger.info(f"Botón presionado por {numero_telefono} ({profile_name or 'sin nombre'}): {button_id}")
            
            # Procesar botón presionado
            respuesta = await handle_interactive_button(numero_telefono, button_id, profile_name)
            
            # Enviar respuesta si hay una
            if respuesta:
                mensaje_enviado = twilio_service.send_whatsapp_message(numero_telefono, respuesta)
                if not mensaje_enviado:
                    logger.error(f"Error enviando respuesta a botón a {numero_telefono}")
            
            return PlainTextResponse("", status_code=200)
        else:
            # Es un mensaje de texto normal
            numero_telefono, mensaje_usuario, message_sid, profile_name = twilio_service.extract_message_data(form_dict)

            # Parsear NumMedia y MessageType ANTES de validar mensaje_usuario para manejar audio/imagen/etc
            try:
                num_media = int(form_dict.get('NumMedia', '0') or '0')
            except Exception:
                num_media = 0
            message_type = (form_dict.get('MessageType') or '').lower().strip()

            if not numero_telefono:
                logger.warning("Datos incompletos en el webhook (sin numero_telefono)")
                return PlainTextResponse("", status_code=200)
            # Permitir continuar si hay media, aunque Body esté vacío
            if (not mensaje_usuario or not mensaje_usuario.strip()) and num_media == 0:
                logger.warning("Datos incompletos en el webhook (sin mensaje ni media)")
                return PlainTextResponse("", status_code=200)
        logger.info(f"Procesando mensaje de {numero_telefono} ({profile_name or 'sin nombre'}): {mensaje_usuario}")

        # Fallback unificado para contenidos no-texto (audio/imagen/video/documento/etc.)
        # num_media y message_type ya parseados arriba
        try:
            num_media = int(form_dict.get('NumMedia', '0') or '0')
        except Exception:
            num_media = 0

        message_type = (form_dict.get('MessageType') or '').lower().strip()

        # Determinar si la conversación está en handoff
        conv_check = conversation_manager.get_conversacion(numero_telefono)
        en_handoff = conv_check.atendido_por_humano or conv_check.estado == EstadoConversacion.ATENDIDO_POR_HUMANO

        if not whatsapp_handoff_service.is_agent_message(numero_telefono) and not en_handoff:
            if num_media > 0 or message_type in ['image', 'audio', 'video', 'document', 'file', 'sticker', 'media', 'location']:
                # Caso especial: primer mensaje del usuario es media (aún no se mostró el menú)
                if conv_check.estado == EstadoConversacion.INICIO:
                    twilio_service.send_whatsapp_message(
                        numero_telefono,
                        "Gracias por tu mensaje 😊 Para continuar, mandá un texto breve (por ejemplo: 'Hola') y verás el menú 📲"
                    )
                    return PlainTextResponse("", status_code=200)

                # Si el usuario está en el menú principal, enviar mensaje corto específico
                if conv_check.estado in [EstadoConversacion.ESPERANDO_OPCION, EstadoConversacion.MENU_PRINCIPAL]:
                    twilio_service.send_whatsapp_message(
                        numero_telefono,
                        "Actualmente este canal solo recibe mensajes de texto. Por favor, selecciona la opcion que desees del menu"
                    )
                    return PlainTextResponse("", status_code=200)

                # En otros estados, usar fallback general (con email si está disponible)
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
            # Si el agente envía media durante handoff, reenviarla al cliente
            try:
                if num_media > 0:
                    # Buscar la conversación de handoff más reciente
                    latest_handoff_conv = None
                    latest_timestamp = None
                    for phone, conv in conversation_manager.conversaciones.items():
                        if conv.atendido_por_humano or conv.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
                            if conv.handoff_started_at and (latest_timestamp is None or conv.handoff_started_at > latest_timestamp):
                                latest_handoff_conv = conv
                                latest_timestamp = conv.handoff_started_at
                    if latest_handoff_conv:
                        for i in range(num_media):
                            media_url = form_dict.get(f'MediaUrl{i}')
                            if media_url:
                                twilio_service.send_whatsapp_media(latest_handoff_conv.numero_telefono, media_url, caption=mensaje_usuario or "")
                        return PlainTextResponse("", status_code=200)
            except Exception:
                pass
            # Procesar mensaje del agente
            await handle_agent_message(numero_telefono, mensaje_usuario, profile_name)
            return PlainTextResponse("", status_code=200)
        
        # Obtener conversación actual
        conversacion_actual = conversation_manager.get_conversacion(numero_telefono)
        
        # Verificar si está en encuesta de satisfacción (PRIORIDAD ALTA)
        if conversacion_actual.estado == EstadoConversacion.ENCUESTA_SATISFACCION:
            # Procesar respuesta de encuesta
            from services.survey_service import survey_service
            
            survey_complete, next_message = survey_service.process_survey_response(
                numero_telefono, mensaje_usuario, conversacion_actual
            )
            
            if next_message:
                # Enviar siguiente pregunta o mensaje de finalización
                twilio_service.send_whatsapp_message(numero_telefono, next_message)
            
            if survey_complete:
                # Encuesta completada, finalizar conversación
                conversation_manager.finalizar_conversacion(numero_telefono)
                logger.info(f"✅ Encuesta completada y conversación finalizada para {numero_telefono}")
            
            return PlainTextResponse("", status_code=200)

        # Si está en handoff, reenviar a WhatsApp del agente y no responder con bot
        if conversacion_actual.atendido_por_humano or conversacion_actual.estado == EstadoConversacion.ATENDIDO_POR_HUMANO:
            # Si el cliente envía no-texto durante handoff, responder con fallback y no reenviar al agente
            if num_media > 0 or message_type in ['image', 'audio', 'video', 'document', 'file', 'sticker', 'media', 'location']:
                twilio_service.send_whatsapp_message(
                    numero_telefono,
                    "Actualmente este canal solo recibe mensajes de texto. Disculpe las molestias ocasionadas"
                )
                try:
                    from datetime import datetime
                    conversacion_actual.last_client_message_at = datetime.utcnow()
                except Exception:
                    pass
                return PlainTextResponse("", status_code=200)
            # Notificar al agente vía WhatsApp con indicación de posición en cola
            active_phone = conversation_manager.get_active_handoff()
            is_active = (active_phone == numero_telefono)

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
                # Obtener posición si no es activo
                position = None if is_active else conversation_manager.get_queue_position(numero_telefono)

                if num_media > 0:
                    # Reenviar media al agente
                    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                    for i in range(num_media):
                        media_url = form_dict.get(f'MediaUrl{i}')
                        if media_url and agent_number:
                            caption = mensaje_usuario or ""
                            if not is_active and position:
                                caption = f"[#{position}] {caption}"
                            twilio_service.send_whatsapp_media(agent_number, media_url, caption=caption)
                else:
                    # Enviar notificación de mensaje con indicador de posición
                    notification = _format_client_message_notification(
                        numero_telefono,
                        profile_name or '',
                        mensaje_usuario,
                        is_active,
                        position
                    )
                    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
                    twilio_service.send_whatsapp_message(agent_number, notification)

                    # Si no es activo, agregar recordatorio
                    if not is_active and position:
                        reminder = f"ℹ️ Este mensaje es del cliente en posición #{position}. Los mensajes que escribas irán al cliente activo. Usa /next para cambiar o /queue para ver la cola completa."
                        twilio_service.send_whatsapp_message(agent_number, reminder)
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
            mensaje_enviado = twilio_service.send_whatsapp_message(numero_telefono, respuesta)
            
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

                # Determinar tipo de notificación
                agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")

                if position == 1:
                    # Es el activo, notificar como activado
                    notification = _format_handoff_activated_notification(
                        conversacion_post,
                        position,
                        total
                    )
                    success = twilio_service.send_whatsapp_message(agent_number, notification)
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
                    success = twilio_service.send_whatsapp_message(agent_number, notification)

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

    return f"""┌────────────────────────────────────────┐
│ 🔔 *HANDOFF ACTIVADO* [{position}/{total}]      │
└────────────────────────────────────────┘

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

    return f"""┌────────────────────────────────────────┐
│ 🔔 *NUEVO HANDOFF EN COLA* [#{position}/{total}] │
└────────────────────────────────────────┘

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
                twilio_service.send_whatsapp_message(agent_phone, response)

                # Si hay nuevo activo, notificar
                new_active = conversation_manager.get_active_handoff()
                if new_active:
                    new_conv = conversation_manager.get_conversacion(new_active)
                    position = 1
                    total = conversation_manager.get_queue_size()
                    notification = _format_handoff_activated_notification(new_conv, position, total)
                    twilio_service.send_whatsapp_message(agent_phone, notification)
                return

            elif command == 'next':
                # Mover al siguiente sin cerrar
                response = agent_command_service.execute_next_command(agent_phone)
                twilio_service.send_whatsapp_message(agent_phone, response)

                # Notificar nuevo activo
                new_active = conversation_manager.get_active_handoff()
                if new_active:
                    new_conv = conversation_manager.get_conversacion(new_active)
                    position = 1
                    total = conversation_manager.get_queue_size()
                    notification = _format_handoff_activated_notification(new_conv, position, total)
                    twilio_service.send_whatsapp_message(agent_phone, notification)
                return

            elif command == 'queue':
                # Mostrar estado de cola
                response = agent_command_service.execute_queue_command(agent_phone)
                twilio_service.send_whatsapp_message(agent_phone, response)
                return

            elif command == 'help':
                # Mostrar ayuda
                response = agent_command_service.execute_help_command(agent_phone)
                twilio_service.send_whatsapp_message(agent_phone, response)
                return

            elif command == 'active':
                # Mostrar conversación activa
                response = agent_command_service.execute_active_command(agent_phone)
                twilio_service.send_whatsapp_message(agent_phone, response)
                return

        # PASO 2: Es un mensaje normal, enviar a conversación activa
        active_phone = conversation_manager.get_active_handoff()

        if not active_phone:
            # No hay conversación activa
            no_active_msg = (
                "⚠️ No hay conversación activa.\n\n"
                "Usa /queue para ver las conversaciones en cola."
            )
            twilio_service.send_whatsapp_message(agent_phone, no_active_msg)
            return

        # Enviar mensaje al cliente activo
        success = whatsapp_handoff_service.send_agent_response_to_client(
            active_phone,
            message
        )

        if not success:
            error_msg = f"❌ Error enviando mensaje al cliente {active_phone}"
            twilio_service.send_whatsapp_message(agent_phone, error_msg)

    except Exception as e:
        logger.error(f"Error en handle_agent_message: {e}")
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

@app.post("/test-bot-flow")
async def test_bot_flow(test_number: str = Form(...)):
    """Endpoint para probar el flujo completo del bot desde un número específico"""
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        from services.twilio_service import twilio_service
        
        logger.info(f"🧪 TESTING BOT FLOW para número: {test_number}")
        
        # Resetear conversación
        conversation_manager.reset_conversacion(test_number)
        
        # Simular mensaje "hola"
        respuesta = ChatbotRules.procesar_mensaje(test_number, "hola", "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = twilio_service.send_whatsapp_message(test_number, respuesta)
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
        from services.twilio_service import twilio_service
        
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
        from services.twilio_service import twilio_service
        
        logger.info(f"🧪 SIMULATING CLIENT MESSAGE: {message} from {test_number}")
        
        # Procesar mensaje como si fuera de cliente (no agente)
        respuesta = ChatbotRules.procesar_mensaje(test_number, message, "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = twilio_service.send_whatsapp_message(test_number, respuesta)
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
        from services.twilio_service import twilio_service
        
        # Usar tu número por defecto
        test_number = "+5491135722871"
        
        logger.info(f"🧪 TESTING COMPLETE FLOW para número: {test_number}")
        
        # Resetear conversación
        conversation_manager.reset_conversacion(test_number)
        
        # Simular mensaje "hola"
        respuesta = ChatbotRules.procesar_mensaje(test_number, "hola", "Usuario Test")
        
        # Enviar respuesta
        if respuesta:
            success = twilio_service.send_whatsapp_message(test_number, respuesta)
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