import os
import json
from twilio.rest import Client
from typing import Optional
import logging

from services.metrics_service import metrics_service

logger = logging.getLogger(__name__)

class TwilioService:
    FAILURE_STATUSES = {"failed", "undelivered", "canceled"}
    DELIVERED_STATUSES = {"delivered", "read"}

    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        whatsapp_num = os.getenv('TWILIO_WHATSAPP_NUMBER')
        if not whatsapp_num:
            raise ValueError("TWILIO_WHATSAPP_NUMBER es requerido")
        self.whatsapp_number = f'whatsapp:{whatsapp_num}' if not whatsapp_num.startswith('whatsapp:') else whatsapp_num
        
        if not self.account_sid or not self.auth_token:
            raise ValueError("TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN son requeridos")
        
        self.client = Client(self.account_sid, self.auth_token)

    def _record_attempt(self, kind: str):
        try:
            metrics_service.on_message_attempt(kind)
        except Exception:
            pass

    def _record_status(self, status: str, kind: str):
        try:
            metrics_service.on_message_status(status, kind)
        except Exception:
            pass

    def _record_success(self, status: Optional[str], kind: str):
        normalized = (status or '').lower()
        try:
            if normalized in self.FAILURE_STATUSES:
                metrics_service.on_message_failure(kind)
            else:
                metrics_service.on_message_success(kind)
                if normalized in self.DELIVERED_STATUSES:
                    metrics_service.on_message_delivered(kind)
        except Exception:
            pass
        self._record_status(status or 'unknown', kind)

    def _record_failure(self, kind: str, status: str = 'exception'):
        try:
            metrics_service.on_message_failure(kind)
            metrics_service.on_message_status(status, kind)
        except Exception:
            pass
    
    def send_whatsapp_message(self, to_number: str, message: str) -> bool:
        try:
            self._record_attempt('text')
            logger.info(f"=== TWILIO SEND DEBUG ===")
            logger.info(f"to_number original: {to_number}")
            logger.info(f"message: {message}")
            logger.info(f"whatsapp_number: {self.whatsapp_number}")
            
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            logger.info(f"to_number final: {to_number}")
            
            message_obj = self.client.messages.create(
                body=message,
                from_=self.whatsapp_number,
                to=to_number
            )
            
            logger.info(f"✅ Mensaje enviado exitosamente a {to_number}. SID: {message_obj.sid}")
            logger.info(f"Estado Twilio: {message_obj.status}")
            self._record_success(getattr(message_obj, 'status', None), 'text')
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando mensaje a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            self._record_failure('text')
            return False
    
    def send_whatsapp_media(self, to_number: str, media_url: str, caption: str = "") -> bool:
        """
        Envía una imagen/sticker a WhatsApp
        """
        try:
            self._record_attempt('media')
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            message = self.client.messages.create(
                body=caption,
                from_=self.whatsapp_number,
                to=to_number,
                media_url=[media_url]
            )
            
            logger.info(f"Media enviado exitosamente a {to_number}. SID: {message.sid}")
            logger.info(f"Estado Twilio: {message.status}")
            self._record_success(getattr(message, 'status', None), 'media')
            return True
            
        except Exception as e:
            logger.error(f"Error enviando media a {to_number}: {str(e)}")
            self._record_failure('media')
            return False
    
    def send_whatsapp_template(self, to_number: str, template_name: str, parameters: list = None) -> bool:
        """
        Envía un Message Template de WhatsApp
        
        Args:
            to_number: Número de destino
            template_name: Nombre del template (ej: "handoff_notification").
                           Si existe HANDOFF_TEMPLATE_SID en variables de entorno, se usará ese SID en su lugar.
            parameters: Lista de parámetros para el template
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            self._record_attempt('template')
            logger.info(f"=== TWILIO TEMPLATE SEND DEBUG ===")
            logger.info(f"to_number: {to_number}")
            logger.info(f"template_name: {template_name}")
            logger.info(f"parameters: {parameters}")
            
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            # Determinar el Content SID del template
            # FORZADO: usar HANDOFF_TEMPLATE_SID. Si no existe, registrar error y abortar.
            content_sid = os.getenv('HANDOFF_TEMPLATE_SID')
            if not content_sid:
                logger.error("HANDOFF_TEMPLATE_SID no está definido en las variables de entorno. Configúralo con el SID del template aprobado (HX...).")
                self._record_failure('template', 'config_missing')
                return False

            # Convertir lista de parámetros a dict numerado {"1": v1, "2": v2, ...}
            content_vars: Optional[dict] = None
            if parameters:
                try:
                    content_vars = {str(i + 1): str(v) for i, v in enumerate(parameters)}
                except Exception:
                    # fallback simple: enviar como json de la lista
                    content_vars = {"1": json.dumps(parameters)}
            
            # Crear el mensaje con template
            message = self.client.messages.create(
                from_=self.whatsapp_number,
                to=to_number,
                content_sid=content_sid,
                content_variables=json.dumps(content_vars) if content_vars else None
            )
            
            logger.info(f"✅ Template enviado exitosamente a {to_number}. SID: {message.sid}")
            logger.info(f"Estado Twilio: {message.status}")
            self._record_success(getattr(message, 'status', None), 'template')
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando template a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            self._record_failure('template')
            return False
    
    def send_whatsapp_quick_reply(self, to_number: str, body: str, buttons: list) -> bool:
        """
        Envía un mensaje con botones de respuesta rápida usando plantillas de Twilio
        
        Args:
            to_number: Número de destino
            body: Texto del mensaje
            buttons: Lista de botones (máximo 3) [{"id": "button1", "title": "Opción 1"}]
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            logger.info(f"=== TWILIO QUICK REPLY SEND DEBUG ===")
            logger.info(f"to_number: {to_number}")
            logger.info(f"body: {body}")
            logger.info(f"buttons: {buttons}")
            
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            # Validar que no haya más de 3 botones
            if len(buttons) > 3:
                logger.error("❌ Máximo 3 botones permitidos en Quick Reply")
                self._record_failure('quick_reply', 'validation')
                return False
            
            # Verificar si tenemos plantillas de botones configuradas
            menu_template_sid = os.getenv("MENU_BUTTONS_TEMPLATE_SID")
            
            if menu_template_sid:
                # Usar plantilla de Twilio con botones
                logger.info(f"Usando plantilla de botones: {menu_template_sid}")
                
                # Crear variables para la plantilla
                template_variables = {
                    "1": body,  # Mensaje principal
                    "2": buttons[0]["title"] if len(buttons) > 0 else "",
                    "3": buttons[1]["title"] if len(buttons) > 1 else "",
                    "4": buttons[2]["title"] if len(buttons) > 2 else ""
                }
                
                self._record_attempt('quick_reply')
                message = self.client.messages.create(
                    from_=self.whatsapp_number,
                    to=to_number,
                    content_sid=menu_template_sid,
                    content_variables=json.dumps(template_variables)
                )
                
                logger.info(f"✅ Plantilla de botones enviada exitosamente a {to_number}. SID: {message.sid}")
                logger.info(f"Estado Twilio: {message.status}")
                self._record_success(getattr(message, 'status', None), 'quick_reply')
                return True
            else:
                # Fallback: usar mensaje de texto mejorado
                logger.info("No hay plantilla de botones configurada, usando fallback")
                self._record_failure('quick_reply', 'template_missing')
                return False
            
        except Exception as e:
            logger.error(f"❌ Error enviando botones a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            self._record_failure('quick_reply')
            return False
    
    def send_whatsapp_list_picker(self, to_number: str, body: str, button_text: str, sections: list) -> bool:
        """
        Envía un mensaje con lista desplegable (List Picker)
        
        Args:
            to_number: Número de destino
            body: Texto del mensaje
            button_text: Texto del botón que abre la lista
            sections: Lista de secciones con opciones [{"title": "Sección 1", "rows": [{"id": "opt1", "title": "Opción 1"}]}]
            
        Returns:
            bool: True si se envió exitosamente
        """
        try:
            self._record_attempt('list_picker')
            logger.info(f"=== TWILIO LIST PICKER SEND DEBUG ===")
            logger.info(f"to_number: {to_number}")
            logger.info(f"body: {body}")
            logger.info(f"button_text: {button_text}")
            logger.info(f"sections: {sections}")
            
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            # Validar que no haya más de 10 opciones totales
            total_options = sum(len(section.get('rows', [])) for section in sections)
            if total_options > 10:
                logger.error("❌ Máximo 10 opciones permitidas en List Picker")
                self._record_failure('list_picker', 'validation')
                return False
            
            # Crear el mensaje con lista interactiva
            message = self.client.messages.create(
                from_=self.whatsapp_number,
                to=to_number,
                body=body,
                actions={
                    'button': button_text,
                    'sections': sections
                }
            )
            
            logger.info(f"✅ List Picker enviado exitosamente a {to_number}. SID: {message.sid}")
            logger.info(f"Estado Twilio: {message.status}")
            self._record_success(getattr(message, 'status', None), 'list_picker')
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando List Picker a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            self._record_failure('list_picker')
            return False
    
    def extract_message_data(self, request_data: dict) -> tuple[str, str, str, str]:
        """
        Extrae los datos relevantes del webhook de Twilio
        Returns: (numero_telefono, mensaje, message_sid, profile_name)
        """
        numero_telefono = request_data.get('From', '').replace('whatsapp:', '')
        mensaje = request_data.get('Body', '').strip()
        message_sid = request_data.get('MessageSid', '')
        profile_name = request_data.get('ProfileName', '').strip()
        
        return numero_telefono, mensaje, message_sid, profile_name
    
    def extract_interactive_data(self, request_data: dict) -> tuple[str, str, str, str]:
        """
        Extrae los datos de botones interactivos del webhook de Twilio
        Returns: (numero_telefono, button_id, message_sid, profile_name)
        """
        numero_telefono = request_data.get('From', '').replace('whatsapp:', '')
        button_id = request_data.get('ButtonPayload', '').strip()
        message_sid = request_data.get('MessageSid', '')
        profile_name = request_data.get('ProfileName', '').strip()
        
        return numero_telefono, button_id, message_sid, profile_name
    
    def validate_webhook_signature(self, request_url: str, post_data: dict, signature: str) -> bool:
        """
        Valida que el webhook venga realmente de Twilio
        """
        try:
            from twilio.request_validator import RequestValidator
            
            auth_token = self.auth_token
            validator = RequestValidator(auth_token)
            
            return validator.validate(request_url, post_data, signature)
        except Exception as e:
            logger.error(f"Error validando signature de Twilio: {str(e)}")
            return False

twilio_service = TwilioService()
