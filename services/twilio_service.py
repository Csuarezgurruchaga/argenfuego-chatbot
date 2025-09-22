import os
import json
import requests
import tempfile
from twilio.rest import Client
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class TwilioService:
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
    
    def send_whatsapp_message(self, to_number: str, message: str) -> bool:
        try:
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
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando mensaje a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
            return False
    
    def send_whatsapp_media(self, to_number: str, media_url: str, caption: str = "") -> bool:
        """
        Envía una imagen/sticker a WhatsApp
        """
        try:
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            # WhatsApp requiere un body, usar caption o texto por defecto
            body_text = caption if caption.strip() else "📎 Archivo multimedia"
            
            message = self.client.messages.create(
                body=body_text,
                from_=self.whatsapp_number,
                to=to_number,
                media_url=[media_url]
            )
            
            logger.info(f"Media enviado exitosamente a {to_number}. SID: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Error enviando media a {to_number}: {str(e)}")
            return False
    
    def send_whatsapp_media_from_url(self, to_number: str, media_url: str, caption: str = "") -> bool:
        """
        DEBUG: Probar si el problema es expiración o algo más.
        Primero intenta reenviar directamente, si falla, descarga y reenvía.
        """
        try:
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            # PRUEBA 1: Intentar reenviar directamente el MediaUrl original
            logger.info(f"🔍 DEBUG: Intentando reenviar MediaUrl original: {media_url}")
            try:
                body_text = caption if caption.strip() else "📎 Archivo multimedia"
                
                message = self.client.messages.create(
                    body=body_text,
                    from_=self.whatsapp_number,
                    to=to_number,
                    media_url=[media_url]
                )
                
                logger.info(f"✅ Media reenviado exitosamente con URL original a {to_number}. SID: {message.sid}")
                return True
                
            except Exception as direct_error:
                logger.warning(f"⚠️ Falló reenvío directo: {direct_error}")
                logger.info(f"🔍 DEBUG: Intentando descargar y reenviar...")
                
                # PRUEBA 2: Descargar y reenviar
                response = requests.get(media_url, timeout=30)
                response.raise_for_status()
                
                # Crear archivo temporal
                with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
                
                # Crear URL pública usando el servidor de Railway
                railway_url = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
                if not railway_url:
                    railway_url = os.getenv('RAILWAY_STATIC_URL', '')
                
                if railway_url:
                    public_url = f"https://{railway_url}/temp_media/{os.path.basename(temp_file_path)}"
                    
                    message = self.client.messages.create(
                        body=body_text,
                        from_=self.whatsapp_number,
                        to=to_number,
                        media_url=[public_url]
                    )
                    
                    logger.info(f"✅ Media reenviado exitosamente con URL descargada a {to_number}. SID: {message.sid}")
                    return True
                else:
                    logger.error("No se pudo obtener URL pública de Railway")
                    return False
                
        except Exception as e:
            logger.error(f"❌ Error reenviando media desde URL a {to_number}: {str(e)}")
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
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando template a {to_number}: {str(e)}")
            logger.error(f"Tipo de error: {type(e).__name__}")
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