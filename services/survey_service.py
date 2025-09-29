import os
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from services.twilio_service import twilio_service
from services.sheets_service import sheets_service
from chatbot.models import ConversacionData, EstadoConversacion

logger = logging.getLogger(__name__)

class SurveyService:
    """
    Servicio para manejar encuestas de satisfacción post-handoff
    """
    
    def __init__(self):
        self.enabled = os.getenv('SUMMARY', 'false').lower() == 'true'
        self.survey_sheet_name = os.getenv('SHEETS_SURVEY_SHEET_NAME', 'ENCUESTA_RESULTADOS')
        
        # Definir las preguntas de la encuesta
        self.questions = {
            1: {
                'text': '¿Pudiste resolver el motivo por el cuál te comunicaste?',
                'options': {
                    '1': 'Sí',
                    '2': 'Parcialmente', 
                    '3': 'No'
                },
                'emojis': {
                    '1': '1️⃣',
                    '2': '2️⃣',
                    '3': '3️⃣'
                }
            },
            2: {
                'text': '¿Cómo calificarías la amabilidad en la atención?',
                'options': {
                    '1': 'Muy buena',
                    '2': 'Regular',
                    '3': 'Mala'
                },
                'emojis': {
                    '1': '1️⃣',
                    '2': '2️⃣',
                    '3': '3️⃣'
                }
            },
            3: {
                'text': '¿Volverías a utilizar esta vía de contacto?',
                'options': {
                    '1': 'Sí',
                    '2': 'No'
                },
                'emojis': {
                    '1': '1️⃣',
                    '2': '2️⃣'
                }
            }
        }
    
    def is_enabled(self) -> bool:
        """Verifica si las encuestas están habilitadas"""
        return self.enabled
    
    def send_survey(self, client_phone: str, conversation: ConversacionData) -> bool:
        """
        Envía la primera pregunta de la encuesta al cliente
        
        Args:
            client_phone: Número de teléfono del cliente
            conversation: Datos de la conversación
            
        Returns:
            bool: True si se envió exitosamente
        """
        if not self.enabled:
            logger.info("Encuestas deshabilitadas, saltando envío")
            return False
            
        try:
            # Marcar que se envió la encuesta
            conversation.survey_sent = True
            conversation.survey_question_number = 1
            
            # Construir mensaje de la primera pregunta
            question_data = self.questions[1]
            message = self._build_question_message(question_data)
            
            # Enviar mensaje
            success = twilio_service.send_whatsapp_message(client_phone, message)
            
            if success:
                logger.info(f"✅ Encuesta enviada al cliente {client_phone}")
            else:
                logger.error(f"❌ Error enviando encuesta al cliente {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error en send_survey: {e}")
            return False
    
    def process_survey_response(self, client_phone: str, message: str, conversation: ConversacionData) -> Tuple[bool, Optional[str]]:
        """
        Procesa la respuesta del cliente a la encuesta
        
        Args:
            client_phone: Número de teléfono del cliente
            message: Mensaje de respuesta del cliente
            conversation: Datos de la conversación
            
        Returns:
            Tuple[bool, Optional[str]]: (encuesta_completa, siguiente_pregunta)
        """
        if not self.enabled or not conversation.survey_sent:
            return False, None
            
        try:
            current_question = conversation.survey_question_number
            question_data = self.questions.get(current_question)
            
            if not question_data:
                logger.error(f"Pregunta {current_question} no encontrada")
                return False, None
            
            # Procesar respuesta
            response = self._parse_response(message, question_data)
            if not response:
                # Respuesta inválida, pedir que responda de nuevo
                return False, self._build_question_message(question_data, include_instructions=True)
            
            # Guardar respuesta
            conversation.survey_responses[f'pregunta_{current_question}'] = response
            
            # Verificar si es la última pregunta
            if current_question >= len(self.questions):
                # Encuesta completa, guardar resultados y finalizar
                self._save_survey_results(client_phone, conversation)
                return True, self._build_completion_message()
            else:
                # Enviar siguiente pregunta
                next_question = current_question + 1
                conversation.survey_question_number = next_question
                next_question_data = self.questions[next_question]
                return False, self._build_question_message(next_question_data)
                
        except Exception as e:
            logger.error(f"Error procesando respuesta de encuesta: {e}")
            return False, None
    
    def _build_question_message(self, question_data: Dict, include_instructions: bool = False) -> str:
        """Construye el mensaje de una pregunta de la encuesta"""
        message = question_data['text'] + '\n\n'
        
        # Agregar opciones con emojis
        for key, emoji in question_data['emojis'].items():
            option_text = question_data['options'][key]
            message += f"{emoji} {option_text}\n"
        
        if include_instructions:
            message += '\nResponde con el número (1, 2 o 3)'
        
        return message
    
    def _build_completion_message(self) -> str:
        """Construye el mensaje de finalización de la encuesta"""
        return "¡Gracias por tu tiempo! Tus respuestas nos ayudan a mejorar nuestro servicio. ✅"
    
    def _parse_response(self, message: str, question_data: Dict) -> Optional[str]:
        """
        Parsea la respuesta del cliente y la convierte al formato estándar
        
        Args:
            message: Mensaje del cliente
            question_data: Datos de la pregunta actual
            
        Returns:
            Optional[str]: Respuesta parseada o None si es inválida
        """
        message = message.strip().lower()
        
        # Buscar por número
        for key, option_text in question_data['options'].items():
            if message == key or message == key + '️⃣':
                return option_text
        
        # Buscar por texto
        for key, option_text in question_data['options'].items():
            if message in option_text.lower():
                return option_text
        
        # Buscar por palabras clave
        keyword_mapping = {
            'si': 'Sí',
            'sí': 'Sí', 
            'yes': 'Sí',
            'parcialmente': 'Parcialmente',
            'partial': 'Parcialmente',
            'no': 'No',
            'muy buena': 'Muy buena',
            'muy bueno': 'Muy buena',
            'excelente': 'Muy buena',
            'regular': 'Regular',
            'normal': 'Regular',
            'mala': 'Mala',
            'malo': 'Mala',
            'terrible': 'Mala'
        }
        
        for keyword, response in keyword_mapping.items():
            if keyword in message:
                # Verificar que la respuesta sea válida para esta pregunta
                if response in question_data['options'].values():
                    return response
        
        return None
    
    def _save_survey_results(self, client_phone: str, conversation: ConversacionData) -> bool:
        """
        Guarda los resultados de la encuesta en Google Sheets
        
        Args:
            client_phone: Número de teléfono del cliente
            conversation: Datos de la conversación
            
        Returns:
            bool: True si se guardó exitosamente
        """
        try:
            # Obtener respuestas
            responses = conversation.survey_responses
            
            # Preparar datos para la hoja
            row_data = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # fecha
                self._mask_phone(client_phone),  # telefono_masked
                responses.get('pregunta_1', ''),  # resolvio_problema
                responses.get('pregunta_2', ''),  # amabilidad
                responses.get('pregunta_3', ''),  # volveria_contactar
                self._mask_phone(conversation.handoff_started_at.strftime('%Y-%m-%d %H:%M:%S') if conversation.handoff_started_at else '')  # fecha_handoff
            ]
            
            # Enviar a Google Sheets
            success = sheets_service.append_row('survey', row_data)
            
            if success:
                logger.info(f"✅ Resultados de encuesta guardados para {client_phone}")
            else:
                logger.error(f"❌ Error guardando resultados de encuesta para {client_phone}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error guardando resultados de encuesta: {e}")
            return False
    
    def _mask_phone(self, phone: str) -> str:
        """Enmascara el número de teléfono para privacidad"""
        if not phone or len(phone) < 4:
            return phone
        
        # Mantener los últimos 4 dígitos
        return '*' * (len(phone) - 4) + phone[-4:]

# Instancia global del servicio
survey_service = SurveyService()
