import os
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
            # Asegurar que el número tenga el prefijo whatsapp:
            if not to_number.startswith('whatsapp:'):
                to_number = f'whatsapp:{to_number}'
            
            message = self.client.messages.create(
                body=message,
                from_=self.whatsapp_number,
                to=to_number
            )
            
            logger.info(f"Mensaje enviado exitosamente a {to_number}. SID: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Error enviando mensaje a {to_number}: {str(e)}")
            return False
    
    def extract_message_data(self, request_data: dict) -> tuple[str, str, str]:
        """
        Extrae los datos relevantes del webhook de Twilio
        Returns: (numero_telefono, mensaje, message_sid)
        """
        numero_telefono = request_data.get('From', '').replace('whatsapp:', '')
        mensaje = request_data.get('Body', '').strip()
        message_sid = request_data.get('MessageSid', '')
        
        return numero_telefono, mensaje, message_sid
    
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