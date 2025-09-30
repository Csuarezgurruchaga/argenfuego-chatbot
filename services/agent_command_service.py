import logging
from typing import Optional
from chatbot.states import conversation_manager
from services.twilio_service import twilio_service

logger = logging.getLogger(__name__)


class AgentCommandService:
    """Servicio para gestionar comandos del agente en el sistema de cola de handoffs."""

    # Comandos reconocidos y sus alias
    COMMAND_ALIASES = {
        'done': ['done', 'd', 'resuelto', 'r', 'resolved', 'finalizar', 'cerrar'],
        'next': ['next', 'n', 'siguiente', 'sig', 'skip'],
        'queue': ['queue', 'q', 'cola', 'list', 'lista'],
        'help': ['help', 'h', 'ayuda', '?', 'comandos'],
        'active': ['active', 'current', 'a', 'activo', 'actual']
    }

    def is_command(self, message: str) -> bool:
        """
        Verifica si un mensaje es un comando del agente.

        Args:
            message: Mensaje a verificar

        Returns:
            bool: True si es un comando
        """
        if not message or not message.strip():
            return False

        clean_msg = message.strip().lower()

        # Verificar si empieza con /
        if clean_msg.startswith('/'):
            return True

        return False

    def parse_command(self, message: str) -> Optional[str]:
        """
        Extrae y normaliza el comando del mensaje.

        Args:
            message: Mensaje con comando

        Returns:
            Optional[str]: Comando normalizado o None si no se reconoce
        """
        if not message or not message.strip():
            return None

        clean_msg = message.strip().lower()

        # Remover / si existe
        if clean_msg.startswith('/'):
            clean_msg = clean_msg[1:]

        # Buscar en los alias
        for command_name, aliases in self.COMMAND_ALIASES.items():
            if clean_msg in aliases:
                return command_name

        return None

    def execute_done_command(self, agent_phone: str) -> str:
        """
        Ejecuta el comando /done: ofrece encuesta al cliente o cierra conversación si encuestas deshabilitadas.

        Args:
            agent_phone: Número del agente (para logs)

        Returns:
            str: Mensaje de respuesta para el agente
        """
        try:
            from services.survey_service import survey_service
            from chatbot.models import EstadoConversacion
            from datetime import datetime

            active_phone = conversation_manager.get_active_handoff()

            if not active_phone:
                return "⚠️ No hay conversación activa para finalizar.\n\nUsa /queue para ver el estado de la cola."

            # Obtener info del cliente
            conversacion = conversation_manager.get_conversacion(active_phone)
            nombre_cliente = conversacion.nombre_usuario or "Cliente"

            # Verificar si las encuestas están habilitadas
            if survey_service.is_enabled():
                # Enviar mensaje opt-in/opt-out de encuesta
                survey_message = self._build_survey_offer_message(nombre_cliente)
                success = twilio_service.send_whatsapp_message(active_phone, survey_message)

                if success:
                    # Cambiar estado a esperar respuesta de encuesta
                    conversacion.estado = EstadoConversacion.ESPERANDO_RESPUESTA_ENCUESTA
                    conversacion.survey_offered = True
                    conversacion.survey_offer_sent_at = datetime.utcnow()

                    logger.info(f"✅ Oferta de encuesta enviada al cliente {active_phone}")
                    return f"✅ Solicitud de cierre enviada a {nombre_cliente}.\n\n⏳ Esperando respuesta sobre la encuesta (auto-cierre en 2 min).\n\nLa conversación sigue activa hasta que el cliente responda o expire el tiempo."
                else:
                    logger.error(f"❌ Error enviando oferta de encuesta al cliente {active_phone}")
                    return f"❌ Error enviando mensaje al cliente. Intenta nuevamente."
            else:
                # Encuestas deshabilitadas: comportamiento original (cerrar inmediatamente)
                twilio_service.send_whatsapp_message(
                    active_phone,
                    "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"
                )

                # Cerrar conversación activa (esto automáticamente activa la siguiente)
                next_phone = conversation_manager.close_active_handoff()

                logger.info(f"✅ Agente {agent_phone} finalizó conversación con {active_phone} (encuestas deshabilitadas)")

                # Mensaje de confirmación
                if next_phone:
                    return f"✅ Conversación con {nombre_cliente} finalizada.\n\n🔄 Activando siguiente conversación..."
                else:
                    return f"✅ Conversación con {nombre_cliente} finalizada.\n\n📋 Cola vacía. No hay más conversaciones pendientes."

        except Exception as e:
            logger.error(f"Error ejecutando comando /done: {e}")
            return f"❌ Error finalizando conversación: {str(e)}"

    def _build_survey_offer_message(self, nombre_cliente: str) -> str:
        """
        Construye el mensaje de oferta de encuesta con opt-in/opt-out.

        Args:
            nombre_cliente: Nombre del cliente

        Returns:
            str: Mensaje formateado
        """
        return f"""¡Gracias por tu consulta, {nombre_cliente}! 🙏

¿Nos ayudas con 3 preguntas rápidas? (toma menos de 1 minuto)
Tu opinión es muy valiosa para mejorar nuestro servicio.

1️⃣ Sí, con gusto
2️⃣ No, gracias

Si no respondes en 2 minutos, cerraremos la conversación automáticamente."""

    def execute_next_command(self, agent_phone: str) -> str:
        """
        Ejecuta el comando /next: mueve conversación activa al final y activa siguiente.

        Args:
            agent_phone: Número del agente (para logs)

        Returns:
            str: Mensaje de respuesta para el agente
        """
        try:
            active_phone = conversation_manager.get_active_handoff()

            if not active_phone:
                return "⚠️ No hay conversación activa.\n\nUsa /queue para ver el estado de la cola."

            queue_size = conversation_manager.get_queue_size()

            if queue_size <= 1:
                return "⚠️ Solo hay una conversación en la cola. Usa /done para finalizarla."

            # Obtener info antes de cambiar
            old_conversacion = conversation_manager.get_conversacion(active_phone)
            old_nombre = old_conversacion.nombre_usuario or "Cliente anterior"

            # Mover al final y activar siguiente
            next_phone = conversation_manager.move_to_next_in_queue()

            if next_phone:
                new_conversacion = conversation_manager.get_conversacion(next_phone)
                new_nombre = new_conversacion.nombre_usuario or "Nuevo cliente"

                logger.info(f"✅ Agente {agent_phone} cambió de {active_phone} a {next_phone}")

                return f"🔄 Conversación con {old_nombre} movida al final de la cola.\n\n✅ Activando conversación con {new_nombre}..."
            else:
                return "❌ Error al cambiar de conversación."

        except Exception as e:
            logger.error(f"Error ejecutando comando /next: {e}")
            return f"❌ Error cambiando de conversación: {str(e)}"

    def execute_queue_command(self, agent_phone: str) -> str:
        """
        Ejecuta el comando /queue: muestra estado completo de la cola.

        Args:
            agent_phone: Número del agente (para logs)

        Returns:
            str: Mensaje con estado de la cola formateado
        """
        try:
            queue_status = conversation_manager.format_queue_status()
            logger.info(f"Agente {agent_phone} solicitó estado de cola")
            return queue_status

        except Exception as e:
            logger.error(f"Error ejecutando comando /queue: {e}")
            return f"❌ Error obteniendo estado de cola: {str(e)}"

    def execute_help_command(self, agent_phone: str) -> str:
        """
        Ejecuta el comando /help: muestra ayuda de comandos.

        Args:
            agent_phone: Número del agente (para logs)

        Returns:
            str: Mensaje de ayuda
        """
        help_text = """📚 *COMANDOS DISPONIBLES*

🔹 *Comandos Principales:*

**/done** (o /d, /resuelto)
   Finaliza la conversación activa y activa la siguiente en cola.
   Ejemplo: /done

**/next** (o /n, /siguiente)
   Mueve la conversación activa al final de la cola y activa la siguiente.
   Útil cuando necesitas cambiar temporalmente a otro cliente.
   Ejemplo: /next

**/queue** (o /q, /cola)
   Muestra el estado completo de la cola de handoffs.
   Ejemplo: /queue

━━━━━━━━━━━━━━━━━━━━━━━

🔹 *Comandos de Información:*

**/active** (o /a, /activo)
   Muestra qué conversación está activa actualmente.
   Ejemplo: /active

**/help** (o /h, /ayuda)
   Muestra este mensaje de ayuda.
   Ejemplo: /help

━━━━━━━━━━━━━━━━━━━━━━━

💡 *Funcionamiento del Sistema de Cola:*

• Siempre hay UNA conversación activa
• Los mensajes que escribas van al cliente activo
• Usa /done cuando termines con un cliente
• La siguiente conversación se activa automáticamente
• Puedes ver la cola completa con /queue

━━━━━━━━━━━━━━━━━━━━━━━

❓ *¿Dudas?* Pregúntale al equipo técnico."""

        logger.info(f"Agente {agent_phone} solicitó ayuda")
        return help_text

    def execute_active_command(self, agent_phone: str) -> str:
        """
        Ejecuta el comando /active: muestra conversación activa.

        Args:
            agent_phone: Número del agente (para logs)

        Returns:
            str: Mensaje con información de conversación activa
        """
        try:
            active_phone = conversation_manager.get_active_handoff()

            if not active_phone:
                return "ℹ️ No hay conversación activa.\n\nUsa /queue para ver el estado de la cola."

            conversacion = conversation_manager.get_conversacion(active_phone)
            nombre = conversacion.nombre_usuario or "Sin nombre"
            queue_size = conversation_manager.get_queue_size()

            # Calcular tiempo activo
            tiempo_activo = ""
            if conversacion.handoff_started_at:
                from datetime import datetime
                delta = datetime.utcnow() - conversacion.handoff_started_at
                minutos = int(delta.total_seconds() / 60)
                if minutos < 60:
                    tiempo_activo = f"{minutos} min"
                else:
                    horas = minutos // 60
                    mins = minutos % 60
                    tiempo_activo = f"{horas}h {mins}min"

            message = f"""🟢 *CONVERSACIÓN ACTIVA*

*Cliente:* {nombre}
*Teléfono:* {active_phone}
*Tiempo activo:* {tiempo_activo or 'N/A'}

━━━━━━━━━━━━━━━━━━━━━━━

📋 *Cola:* {queue_size} conversación(es) total(es)

💬 Los mensajes que escribas irán a {nombre}."""

            if queue_size > 1:
                message += f"\n\nUsa /queue para ver todas las conversaciones o /next para cambiar."

            logger.info(f"Agente {agent_phone} solicitó conversación activa")
            return message

        except Exception as e:
            logger.error(f"Error ejecutando comando /active: {e}")
            return f"❌ Error obteniendo conversación activa: {str(e)}"


# Instancia global del servicio
agent_command_service = AgentCommandService()