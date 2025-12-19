import os
import json
import hmac
import hashlib
import logging
from typing import Optional, Dict, Any, Tuple
import requests

from services.otel_metrics_service import otel_metrics

logger = logging.getLogger(__name__)


class MetaMessengerService:
    """Servicio para interactuar con Facebook Messenger API de Meta."""
    
    def __init__(self):
        # Reutilizar las mismas variables de entorno que WhatsApp
        self.access_token = os.getenv('META_WA_ACCESS_TOKEN')
        self.app_secret = os.getenv('META_WA_APP_SECRET')
        self.verify_token = os.getenv('META_WA_VERIFY_TOKEN')
        
        # Variable específica de Messenger
        self.page_id = os.getenv('META_PAGE_ID')
        
        # Validar variables requeridas
        if not self.access_token:
            logger.warning("META_WA_ACCESS_TOKEN no configurado - Messenger deshabilitado")
            self.enabled = False
            return
        
        if not self.page_id:
            logger.warning("META_PAGE_ID no configurado - Messenger deshabilitado")
            self.enabled = False
            return
        
        self.enabled = True
        
        # Graph API version
        self.api_version = "v21.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        
        # Headers comunes
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"MetaMessengerService inicializado. Page ID: {self.page_id}, API: {self.api_version}")
    
    def send_text_message(self, recipient_id: str, message: str) -> bool:
        """
        Envía un mensaje de texto a través de Messenger Send API.
        
        Args:
            recipient_id: PSID del destinatario (Page-Scoped ID)
            message: Texto del mensaje
            
        Returns:
            bool: True si se envió exitosamente
        """
        if not self.enabled:
            logger.error("MetaMessengerService no está habilitado")
            return False
        
        try:
            logger.info(f"=== META MESSENGER SEND TEXT ===")
            logger.info(f"recipient_id: {recipient_id}")
            logger.info(f"message: {message[:100]}...")
            
            # Construir payload para Send API
            url = f"{self.base_url}/me/messages"
            payload = {
                "recipient": {
                    "id": recipient_id
                },
                "message": {
                    "text": message
                },
                "messaging_type": "RESPONSE"
            }
            
            # Enviar petición
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            logger.info(f"Status code: {response.status_code}")
            logger.debug(f"Response: {response.text}")
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                message_id = response_data.get('message_id', 'N/A')
                logger.info(f"✅ Mensaje Messenger enviado a {recipient_id}. Message ID: {message_id}")
                otel_metrics.record_whatsapp_sent()  # Reutilizamos la métrica
                return True
            else:
                logger.error(f"❌ Error enviando mensaje Messenger: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="messenger_api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Excepción enviando mensaje Messenger: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="messenger_exception")
            return False
    
    def send_quick_replies(self, recipient_id: str, message: str, quick_replies: list) -> bool:
        """
        Envía un mensaje con Quick Replies (botones de respuesta rápida).
        
        Args:
            recipient_id: PSID del destinatario
            message: Texto del mensaje
            quick_replies: Lista de quick replies [{"title": "Opción 1", "payload": "opt_1"}, ...]
            
        Returns:
            bool: True si se envió exitosamente
        """
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/me/messages"
            
            # Formatear quick replies
            formatted_replies = [
                {
                    "content_type": "text",
                    "title": qr.get("title", "")[:20],  # Máximo 20 caracteres
                    "payload": qr.get("payload", qr.get("title", ""))
                }
                for qr in quick_replies[:13]  # Máximo 13 quick replies
            ]
            
            payload = {
                "recipient": {"id": recipient_id},
                "message": {
                    "text": message,
                    "quick_replies": formatted_replies
                },
                "messaging_type": "RESPONSE"
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Quick replies enviados a {recipient_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando quick replies: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="messenger_api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando quick replies: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="messenger_exception")
            return False
    
    def send_image_message(self, recipient_id: str, image_url: str) -> bool:
        """
        Envía una imagen a través de Messenger.
        
        Args:
            recipient_id: PSID del destinatario
            image_url: URL pública de la imagen
            
        Returns:
            bool: True si se envió exitosamente
        """
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/me/messages"
            payload = {
                "recipient": {"id": recipient_id},
                "message": {
                    "attachment": {
                        "type": "image",
                        "payload": {
                            "url": image_url,
                            "is_reusable": True
                        }
                    }
                },
                "messaging_type": "RESPONSE"
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Imagen enviada a {recipient_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando imagen: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="messenger_api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando imagen: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="messenger_exception")
            return False
    
    def validate_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Valida que el webhook venga realmente de Meta usando X-Hub-Signature-256.
        Reutiliza la misma lógica que WhatsApp (mismo app_secret).
        
        Args:
            payload: Cuerpo del request en bytes
            signature: Header X-Hub-Signature-256
            
        Returns:
            bool: True si la firma es válida
        """
        try:
            if not self.app_secret:
                logger.error("META_WA_APP_SECRET no configurado para validar firma")
                return False
            
            if not signature.startswith('sha256='):
                logger.error("Firma no tiene formato correcto")
                return False
            
            expected_hash = signature[7:]
            
            computed_hash = hmac.new(
                self.app_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            is_valid = hmac.compare_digest(computed_hash, expected_hash)
            
            if not is_valid:
                logger.error("❌ Firma de webhook Messenger inválida")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error validando firma de webhook Messenger: {str(e)}")
            return False
    
    def extract_message_data(self, webhook_data: dict) -> Optional[Tuple[str, str, str, str, str]]:
        """
        Extrae datos de mensaje del webhook de Messenger.
        
        Args:
            webhook_data: Payload del webhook
            
        Returns:
            Optional[Tuple]: (sender_id, mensaje, message_id, sender_name, message_type) o None
        """
        try:
            # Estructura Messenger: entry[0].messaging[0]
            if 'entry' not in webhook_data or not webhook_data['entry']:
                return None
            
            entry = webhook_data['entry'][0]
            messaging = entry.get('messaging', [])
            
            if not messaging:
                return None
            
            messaging_event = messaging[0]
            
            # Verificar que sea nuestra página
            recipient = messaging_event.get('recipient', {})
            page_id = recipient.get('id', '')
            
            if self.page_id and page_id != self.page_id:
                logger.warning(f"Webhook de otra página ignorado: {page_id} (esperado={self.page_id})")
                return None
            
            # Extraer sender
            sender = messaging_event.get('sender', {})
            sender_id = sender.get('id', '')
            
            # Verificar si hay mensaje
            message = messaging_event.get('message', {})
            if not message:
                # Podría ser un evento de postback u otro tipo
                postback = messaging_event.get('postback', {})
                if postback:
                    return (
                        sender_id,
                        postback.get('payload', ''),
                        '',
                        '',
                        'postback'
                    )
                return None
            
            message_id = message.get('mid', '')
            
            # Extraer texto
            text_body = message.get('text', '')
            message_type = 'text' if text_body else 'unknown'
            
            # Quick reply payload
            quick_reply = message.get('quick_reply', {})
            if quick_reply:
                text_body = quick_reply.get('payload', text_body)
                message_type = 'quick_reply'
            
            # Attachments (imagen, audio, etc.)
            attachments = message.get('attachments', [])
            if attachments and not text_body:
                attachment_type = attachments[0].get('type', 'unknown')
                message_type = attachment_type
                logger.info(f"Mensaje de tipo {attachment_type} recibido de {sender_id}")
            
            # Nota: Messenger no envía nombre del sender en el webhook
            # Se necesitaría una llamada adicional a Graph API para obtenerlo
            sender_name = ''
            
            # Prefijo para identificar que es Messenger (no número de teléfono)
            messenger_id = f"messenger:{sender_id}"
            
            return (messenger_id, text_body, message_id, sender_name, message_type)
            
        except Exception as e:
            logger.error(f"Error extrayendo datos del webhook Messenger: {str(e)}")
            return None
    
    def get_user_profile(self, psid: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene el perfil del usuario de Messenger.
        
        Args:
            psid: Page-Scoped ID del usuario
            
        Returns:
            Optional[Dict]: {"first_name": str, "last_name": str, "profile_pic": str} o None
        """
        if not self.enabled:
            return None
        
        try:
            url = f"{self.base_url}/{psid}"
            params = {
                "fields": "first_name,last_name,profile_pic",
                "access_token": self.access_token
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"No se pudo obtener perfil de {psid}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error obteniendo perfil de usuario: {str(e)}")
            return None
    
    def is_messenger_webhook(self, webhook_data: dict) -> bool:
        """
        Detecta si el webhook es de Messenger (vs WhatsApp).
        
        Args:
            webhook_data: Payload del webhook
            
        Returns:
            bool: True si es un webhook de Messenger
        """
        return webhook_data.get('object') == 'page'


# Instancia global del servicio (se inicializa solo si hay configuración)
try:
    meta_messenger_service = MetaMessengerService()
except Exception as e:
    logger.warning(f"MetaMessengerService no inicializado: {e}")
    meta_messenger_service = None

