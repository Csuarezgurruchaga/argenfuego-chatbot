import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import json

from .twilio_service import twilio_service

logger = logging.getLogger(__name__)


class WhatsAppHandoffService:
    """Servicio para manejar handoffs a agentes humanos vía WhatsApp usando Twilio."""

    def __init__(self):
        self.agent_whatsapp_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
        if not self.agent_whatsapp_number:
            raise ValueError("AGENT_WHATSAPP_NUMBER es requerido para el handoff a WhatsApp")
        
        # Asegurar que el número tenga el formato correcto
        if not self.agent_whatsapp_number.startswith('+'):
            self.agent_whatsapp_number = f'+{self.agent_whatsapp_number}'
        
        logger.info(f"WhatsApp Handoff Service inicializado. Agente: {self.agent_whatsapp_number}")

    def notify_agent_new_handoff(self, client_phone: str, client_name: str, 
                                handoff_message: str, current_message: str) -> bool:
        """
        Notifica al agente sobre una nueva solicitud de handoff usando Message Template.
        
        Args:
            client_phone: Número de teléfono del cliente
            client_name: Nombre del cliente (si está disponible)
            handoff_message: Mensaje que disparó el handoff
            current_message: Último mensaje del cliente
            
        Returns:
            bool: True si la notificación se envió exitosamente
        """
        try:
            # Usar Message Template para iniciar conversación
            success = twilio_service.send_whatsapp_template(
                self.agent_whatsapp_number,
                "handoff_notification",  # Nombre del template
                [
                    client_name or "Sin nombre",  # {{1}}
                    client_phone,                 # {{2}}
                    handoff_message,              # {{3}}
                    current_message               # {{4}}
                ]
            )
            
            if success:
                logger.info(f"✅ Notificación de handoff enviada al agente para cliente {client_phone}")
                # Enviar instrucción clara: responder en este chat para que el bot reenvíe al cliente
                try:
                    instruction = (
                        "ℹ️ Instrucciones:\n\n"
                        "• Responde en este mismo chat y enviaremos tu mensaje al cliente automáticamente.\n"
                        "• No es necesario escribirle al número del cliente.\n"
                        "• Para cerrar la conversación, responde con: /resuelto"
                    )
                    twilio_service.send_whatsapp_message(self.agent_whatsapp_number, instruction)
                except Exception:
                    pass
            else:
                logger.error(f"❌ Error enviando notificación de handoff al agente para cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en notify_agent_new_handoff: {e}")
            return False

    def notify_agent_new_message(self, client_phone: str, client_name: str, 
                                message: str) -> bool:
        """
        Notifica al agente sobre un nuevo mensaje del cliente durante el handoff.
        
        Args:
            client_phone: Número de teléfono del cliente
            client_name: Nombre del cliente
            message: Nuevo mensaje del cliente
            
        Returns:
            bool: True si la notificación se envió exitosamente
        """
        try:
            agent_message = f"💬 *Nuevo mensaje del cliente*\n\n"
            agent_message += f"Cliente: {client_name or 'Sin nombre'} ({client_phone})\n"
            agent_message += f"Mensaje: {message}\n\n"
            agent_message += f"Para responder, envía tu mensaje a: {client_phone}"
            
            success = twilio_service.send_whatsapp_message(
                self.agent_whatsapp_number, 
                agent_message
            )
            
            if success:
                logger.info(f"✅ Nuevo mensaje notificado al agente para cliente {client_phone}")
            else:
                logger.error(f"❌ Error notificando nuevo mensaje al agente para cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en notify_agent_new_message: {e}")
            return False

    def send_agent_response_to_client(self, client_phone: str, agent_message: str) -> bool:
        """
        Envía la respuesta del agente al cliente.
        
        Args:
            client_phone: Número de teléfono del cliente
            agent_message: Mensaje del agente para el cliente
            
        Returns:
            bool: True si el mensaje se envió exitosamente
        """
        try:
            # Formatear mensaje del agente
            formatted_message = f"👨‍💼 *Agente:* {agent_message}"
            
            success = twilio_service.send_whatsapp_message(client_phone, formatted_message)
            
            if success:
                logger.info(f"✅ Respuesta del agente enviada al cliente {client_phone}")
            else:
                logger.error(f"❌ Error enviando respuesta del agente al cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en send_agent_response_to_client: {e}")
            return False

    def notify_handoff_resolved(self, client_phone: str, client_name: str) -> bool:
        """
        Notifica al agente que el handoff ha sido resuelto.
        
        Args:
            client_phone: Número de teléfono del cliente
            client_name: Nombre del cliente
            
        Returns:
            bool: True si la notificación se envió exitosamente
        """
        try:
            agent_message = f"✅ *Handoff resuelto*\n\n"
            agent_message += f"Cliente: {client_name or 'Sin nombre'} ({client_phone})\n"
            agent_message += f"La conversación ha sido finalizada exitosamente."
            
            success = twilio_service.send_whatsapp_message(
                self.agent_whatsapp_number, 
                agent_message
            )
            
            if success:
                logger.info(f"✅ Notificación de resolución enviada al agente para cliente {client_phone}")
            else:
                logger.error(f"❌ Error notificando resolución al agente para cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en notify_handoff_resolved: {e}")
            return False

    def _format_handoff_notification(self, client_phone: str, client_name: str, 
                                   handoff_message: str, current_message: str) -> str:
        """
        Formatea el mensaje de notificación de handoff para el agente.
        """
        message = f"🔄 *Nueva solicitud de agente humano*\n\n"
        message += f"Cliente: {client_name or 'Sin nombre'} ({client_phone})\n\n"
        message += f"📝 *Mensaje que disparó el handoff:*\n{handoff_message}\n\n"
        message += f"💬 *Último mensaje:*\n{current_message}\n\n"
        message += f"Para responder, envía tu mensaje a: {client_phone}\n\n"
        message += f"Para marcar como resuelto, responde con: /resuelto"
        
        return message

    def is_agent_message(self, from_number: str) -> bool:
        """
        Verifica si un mensaje proviene del agente.
        
        Args:
            from_number: Número de teléfono que envió el mensaje
            
        Returns:
            bool: True si el mensaje proviene del agente
        """
        # Normalizar números para comparación
        normalized_from = from_number.replace('whatsapp:', '').replace('+', '')
        normalized_agent = self.agent_whatsapp_number.replace('+', '')
        
        return normalized_from == normalized_agent

    def is_resolution_command(self, message: str) -> bool:
        """
        Verifica si el mensaje del agente es un comando de resolución.
        
        Args:
            message: Mensaje del agente
            
        Returns:
            bool: True si es un comando de resolución
        """
        resolution_commands = [
            '/resuelto', '/resolved', '/cerrar', '/close', '/fin', '/end',
            '/r', 'resuelto', 'resolved', 'cerrar', 'close', 'fin', 'end',
            'ok', 'listo', 'done', 'terminado', 'completado'
        ]
        return message.strip().lower() in resolution_commands

    def send_agent_buttons(self, client_phone: str, client_name: str, 
                          handoff_message: str, current_message: str) -> bool:
        """
        Envía notificación al agente con botones interactivos de WhatsApp.
        
        Args:
            client_phone: Número de teléfono del cliente
            client_name: Nombre del cliente
            handoff_message: Mensaje que disparó el handoff
            current_message: Último mensaje del cliente
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            # Formatear mensaje principal
            main_message = self._format_handoff_notification(
                client_phone, client_name, handoff_message, current_message
            )
            
            # Enviar mensaje principal
            success = twilio_service.send_whatsapp_message(
                self.agent_whatsapp_number, 
                main_message
            )
            
            if success:
                # Enviar botones como mensaje separado
                buttons_message = (
                    f"📱 *Opciones de respuesta:*\n\n"
                    f"• Escribe tu respuesta para enviar al cliente\n"
                    f"• Envía 'ok' o 'listo' para marcar como resuelto\n"
                    f"• Envía '/r' para resolución rápida"
                )
                
                twilio_service.send_whatsapp_message(
                    self.agent_whatsapp_number, 
                    buttons_message
                )
                
                logger.info(f"✅ Notificación con botones enviada al agente para cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en send_agent_buttons: {e}")
            return False

    def send_resolution_question_to_client(self, client_phone: str) -> bool:
        """
        Envía pregunta de resolución al cliente.
        
        Args:
            client_phone: Número de teléfono del cliente
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            question_message = (
                f"👨‍💼 *Agente:* ¿Hay algo más en lo que pueda ayudarte?\n\n"
                f"Si no necesitas más ayuda, simplemente no respondas y la conversación se cerrará automáticamente en unos minutos."
            )
            
            success = twilio_service.send_whatsapp_message(client_phone, question_message)
            
            if success:
                logger.info(f"✅ Pregunta de resolución enviada al cliente {client_phone}")
            else:
                logger.error(f"❌ Error enviando pregunta de resolución al cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en send_resolution_question_to_client: {e}")
            return False

    def get_agent_phone(self) -> str:
        """
        Retorna el número de teléfono del agente.
        
        Returns:
            str: Número de teléfono del agente
        """
        return self.agent_whatsapp_number


# Instancia global del servicio
whatsapp_handoff_service = WhatsAppHandoffService()
