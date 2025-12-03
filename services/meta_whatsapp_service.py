import os
import json
import hmac
import hashlib
import logging
from typing import Optional, Dict, Any, Tuple
import requests

from services.otel_metrics_service import otel_metrics

logger = logging.getLogger(__name__)


class MetaWhatsAppService:
    """Servicio para interactuar con WhatsApp Cloud API de Meta."""
    
    def __init__(self):
        # Variables de entorno requeridas
        self.access_token = os.getenv('META_WA_ACCESS_TOKEN')
        self.phone_number_id = os.getenv('META_WA_PHONE_NUMBER_ID')
        self.app_secret = os.getenv('META_WA_APP_SECRET')
        self.verify_token = os.getenv('META_WA_VERIFY_TOKEN')
        
        # Validar que todas las variables estén configuradas
        if not self.access_token:
            raise ValueError("META_WA_ACCESS_TOKEN es requerido")
        if not self.phone_number_id:
            raise ValueError("META_WA_PHONE_NUMBER_ID es requerido")
        if not self.app_secret:
            raise ValueError("META_WA_APP_SECRET es requerido para validar webhooks")
        if not self.verify_token:
            raise ValueError("META_WA_VERIFY_TOKEN es requerido para verificación de webhook")
        
        # Graph API version (hardcodeado para estabilidad)
        self.api_version = "v21.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        
        # Headers comunes para todas las peticiones
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"MetaWhatsAppService inicializado. Phone ID: {self.phone_number_id}, API: {self.api_version}")
    
    def send_text_message(self, to_number: str, message: str) -> bool:
        """
        Envía un mensaje de texto a través de WhatsApp Cloud API.
        
        Args:
            to_number: Número de destino en formato E.164 (ej: +5491135722871)
            message: Texto del mensaje
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            logger.info(f"=== META WHATSAPP SEND TEXT DEBUG ===")
            logger.info(f"to_number original: {to_number}")
            logger.info(f"message: {message}")
            
            # Normalizar número (remover whatsapp: si existe, asegurar que tenga +)
            normalized_number = self._normalize_phone_number(to_number)
            logger.info(f"to_number normalizado: {normalized_number}")
            
            # Construir payload
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": message
                }
            }
            
            logger.info(f"URL: {url}")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")
            
            # Enviar petición
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            logger.info(f"Status code: {response.status_code}")
            logger.debug(f"Response: {response.text}")
            
            # Validar respuesta
            if response.status_code in [200, 201]:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                logger.info(f"✅ Mensaje enviado exitosamente a {normalized_number}. Message ID: {message_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando mensaje a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Excepción enviando mensaje a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def send_media_message(self, to_number: str, media_url: str, caption: str = "") -> bool:
        """
        Envía un mensaje con imagen/media a través de WhatsApp Cloud API.
        
        Args:
            to_number: Número de destino en formato E.164
            media_url: URL pública de la imagen/media
            caption: Texto opcional que acompaña la imagen
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            normalized_number = self._normalize_phone_number(to_number)
            
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "image",
                "image": {
                    "link": media_url,
                    "caption": caption
                }
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                logger.info(f"✅ Media enviado exitosamente a {normalized_number}. Message ID: {message_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando media a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando media a {to_number}: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def send_sticker(self, to_number: str, sticker_url: str) -> bool:
        """
        Envía un sticker a través de WhatsApp Cloud API.
        
        Args:
            to_number: Número de destino en formato E.164
            sticker_url: URL pública del sticker (formato WebP recomendado)
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            normalized_number = self._normalize_phone_number(to_number)
            
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "sticker",
                "sticker": {
                    "link": sticker_url
                }
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                logger.info(f"✅ Sticker enviado exitosamente a {normalized_number}. Message ID: {message_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando sticker a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando sticker a {to_number}: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def send_template_message(self, to_number: str, template_name: str, language_code: str, 
                            components: Optional[list] = None) -> bool:
        """
        Envía un mensaje usando un template aprobado de WhatsApp.
        
        Args:
            to_number: Número de destino en formato E.164
            template_name: Nombre del template aprobado
            language_code: Código de idioma (ej: "es", "en_US")
            components: Lista de componentes del template (para parámetros)
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            normalized_number = self._normalize_phone_number(to_number)
            
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {
                        "code": language_code
                    }
                }
            }
            
            # Agregar componentes si existen
            if components:
                payload["template"]["components"] = components
            
            logger.info(f"Enviando template '{template_name}' a {normalized_number}")
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                logger.info(f"✅ Template enviado exitosamente a {normalized_number}. Message ID: {message_id}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando template a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando template a {to_number}: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def send_interactive_buttons(self, to_number: str, body_text: str, 
                                buttons: list, header_text: Optional[str] = None,
                                footer_text: Optional[str] = None) -> bool:
        """
        Envía mensaje con botones interactivos (máximo 3 botones).
        
        Args:
            to_number: Número de destino en formato E.164
            body_text: Texto principal del mensaje
            buttons: Lista de botones [{"id": "btn_1", "title": "Opción 1"}, ...]
            header_text: Texto opcional del encabezado
            footer_text: Texto opcional del pie
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            if len(buttons) > 3:
                logger.error("❌ Máximo 3 botones permitidos en mensajes interactivos")
                return False
            
            normalized_number = self._normalize_phone_number(to_number)
            
            # Construir action con botones
            action = {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn["id"],
                            "title": btn["title"][:20]  # Máximo 20 caracteres
                        }
                    }
                    for btn in buttons
                ]
            }
            
            # Construir payload
            interactive = {
                "type": "button",
                "body": {"text": body_text},
                "action": action
            }
            
            if header_text:
                interactive["header"] = {"type": "text", "text": header_text}
            
            if footer_text:
                interactive["footer"] = {"text": footer_text}
            
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "interactive",
                "interactive": interactive
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Botones interactivos enviados a {normalized_number}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando botones a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando botones a {to_number}: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def send_interactive_list(self, to_number: str, body_text: str, button_text: str,
                            sections: list, header_text: Optional[str] = None,
                            footer_text: Optional[str] = None) -> bool:
        """
        Envía mensaje con lista interactiva.
        
        Args:
            to_number: Número de destino en formato E.164
            body_text: Texto principal del mensaje
            button_text: Texto del botón que abre la lista
            sections: Lista de secciones [{"title": "Sección", "rows": [{"id": "1", "title": "Opción"}]}]
            header_text: Texto opcional del encabezado
            footer_text: Texto opcional del pie
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            normalized_number = self._normalize_phone_number(to_number)
            
            # Construir action con lista
            action = {
                "button": button_text,
                "sections": sections
            }
            
            # Construir payload
            interactive = {
                "type": "list",
                "body": {"text": body_text},
                "action": action
            }
            
            if header_text:
                interactive["header"] = {"type": "text", "text": header_text}
            
            if footer_text:
                interactive["footer"] = {"text": footer_text}
            
            url = f"{self.base_url}/{self.phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalized_number,
                "type": "interactive",
                "interactive": interactive
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ Lista interactiva enviada a {normalized_number}")
                otel_metrics.record_whatsapp_sent()
                return True
            else:
                logger.error(f"❌ Error enviando lista a {normalized_number}: {response.status_code} - {response.text}")
                otel_metrics.record_whatsapp_error(error_type="api_error")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error enviando lista a {to_number}: {str(e)}")
            otel_metrics.record_whatsapp_error(error_type="exception")
            return False
    
    def validate_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Valida que el webhook venga realmente de Meta usando X-Hub-Signature-256.
        
        Args:
            payload: Cuerpo del request en bytes (raw body)
            signature: Header X-Hub-Signature-256 del request
            
        Returns:
            bool: True si la firma es válida
        """
        try:
            # La firma viene como "sha256=<hash>"
            if not signature.startswith('sha256='):
                logger.error("Firma no tiene formato correcto (debe empezar con 'sha256=')")
                return False
            
            # Extraer el hash
            expected_hash = signature[7:]  # Remover "sha256="
            
            # Calcular HMAC-SHA256 del payload con app_secret
            computed_hash = hmac.new(
                self.app_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Comparación segura
            is_valid = hmac.compare_digest(computed_hash, expected_hash)
            
            if not is_valid:
                logger.error("❌ Firma de webhook inválida")
                logger.debug(f"Expected: {expected_hash}")
                logger.debug(f"Computed: {computed_hash}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error validando firma de webhook: {str(e)}")
            return False
    
    def verify_webhook_token(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Verifica el token del webhook durante la configuración inicial (GET request).
        
        Args:
            mode: hub.mode del request
            token: hub.verify_token del request
            challenge: hub.challenge del request
            
        Returns:
            Optional[str]: El challenge si la verificación es exitosa, None si falla
        """
        try:
            if mode == "subscribe" and token == self.verify_token:
                logger.info("✅ Webhook verificado exitosamente")
                return challenge
            else:
                logger.error(f"❌ Verificación de webhook fallida. Mode: {mode}, Token válido: {token == self.verify_token}")
                return None
                
        except Exception as e:
            logger.error(f"Error en verificación de webhook: {str(e)}")
            return None
    
    def extract_message_data(self, webhook_data: dict) -> Optional[Tuple[str, str, str, str, str]]:
        """
        Extrae datos de mensaje del webhook de Meta.
        
        Args:
            webhook_data: Payload del webhook
            
        Returns:
            Optional[Tuple]: (numero_telefono, mensaje, message_id, profile_name, message_type) o None si no es válido
        """
        try:
            # Estructura: entry[0].changes[0].value
            if 'entry' not in webhook_data or not webhook_data['entry']:
                return None
            
            entry = webhook_data['entry'][0]
            changes = entry.get('changes', [])
            
            if not changes:
                return None
            
            value = changes[0].get('value', {})
            
            # Verificar que el mensaje sea del número correcto
            metadata = value.get('metadata', {})
            phone_number_id = metadata.get('phone_number_id', '')
            
            if phone_number_id != self.phone_number_id:
                logger.warning(
                    "Webhook de otro número ignorado: %s (esperado=%s)",
                    phone_number_id,
                    self.phone_number_id
                )
                logger.debug("Payload ignorado: %s", value)
                return None
            
            # Extraer mensajes
            messages = value.get('messages', [])
            if not messages:
                return None
            
            message = messages[0]
            
            # Datos básicos
            from_number = message.get('from', '')
            message_id = message.get('id', '')
            message_type = message.get('type', '')
            
            # Nombre del contacto
            contacts = value.get('contacts', [])
            profile_name = ''
            if contacts:
                profile = contacts[0].get('profile', {})
                profile_name = profile.get('name', '')
            
            # Extraer texto según el tipo
            text_body = ''
            
            if message_type == 'text':
                text_body = message.get('text', {}).get('body', '')
            
            elif message_type == 'interactive':
                # Botón o lista
                interactive = message.get('interactive', {})
                inter_type = interactive.get('type', '')
                
                if inter_type == 'button_reply':
                    # Respuesta de botón
                    button_reply = interactive.get('button_reply', {})
                    text_body = button_reply.get('id', '')  # ID del botón
                    
                elif inter_type == 'list_reply':
                    # Respuesta de lista
                    list_reply = interactive.get('list_reply', {})
                    text_body = list_reply.get('id', '')  # ID de la opción
            
            elif message_type == 'image':
                # Imagen (registrar pero no procesar por ahora)
                logger.info("Mensaje de tipo imagen recibido de %s", from_number)
                text_body = ''  # Vacío para que sea manejado como media
            
            elif message_type == 'audio':
                logger.info("Mensaje de tipo audio recibido de %s", from_number)
                text_body = ''
            
            elif message_type == 'video':
                logger.info("Mensaje de tipo video recibido de %s", from_number)
                text_body = ''
            
            elif message_type == 'document':
                logger.info("Mensaje de tipo documento recibido de %s", from_number)
                text_body = ''
            
            # Asegurar formato E.164 (agregar + si no lo tiene)
            if from_number and not from_number.startswith('+'):
                from_number = f'+{from_number}'
            
            return (from_number, text_body, message_id, profile_name, message_type)
            
        except Exception as e:
            logger.error(f"Error extrayendo datos del webhook: {str(e)}")
            return None
    
    def extract_status_data(self, webhook_data: dict) -> Optional[Dict[str, Any]]:
        """
        Extrae datos de estado de mensaje del webhook.
        
        Args:
            webhook_data: Payload del webhook
            
        Returns:
            Optional[Dict]: {"message_id": str, "status": str, "timestamp": str} o None
        """
        try:
            if 'entry' not in webhook_data or not webhook_data['entry']:
                return None
            
            entry = webhook_data['entry'][0]
            changes = entry.get('changes', [])
            
            if not changes:
                return None
            
            value = changes[0].get('value', {})
            statuses = value.get('statuses', [])
            
            if not statuses:
                return None
            
            status = statuses[0]
            
            return {
                "message_id": status.get('id', ''),
                "status": status.get('status', ''),  # sent, delivered, read, failed
                "timestamp": status.get('timestamp', ''),
                "recipient_id": status.get('recipient_id', '')
            }
            
        except Exception as e:
            logger.error(f"Error extrayendo estado del webhook: {str(e)}")
            return None
    
    def _normalize_phone_number(self, phone_number: str) -> str:
        """
        Normaliza un número de teléfono al formato E.164.
        
        Args:
            phone_number: Número en cualquier formato
            
        Returns:
            str: Número en formato E.164 (ej: 5491135722871 sin +)
        """
        # Remover prefijo whatsapp: si existe
        normalized = phone_number.replace('whatsapp:', '')
        
        # Remover espacios y caracteres especiales
        normalized = normalized.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Para Meta API, el número NO debe tener el +
        if normalized.startswith('+'):
            normalized = normalized[1:]
        
        return normalized


# Instancia global del servicio
meta_whatsapp_service = MetaWhatsAppService()
