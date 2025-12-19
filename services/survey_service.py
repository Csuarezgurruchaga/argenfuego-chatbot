import os
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

from services.meta_whatsapp_service import meta_whatsapp_service
from services.sheets_service import sheets_service
from chatbot.models import ConversacionData, EstadoConversacion

logger = logging.getLogger(__name__)


def _get_client_messaging_service(client_id: str):
    """
    Devuelve el servicio correcto para enviar mensajes al cliente.
    """
    if client_id.startswith("messenger:"):
        from services.meta_messenger_service import meta_messenger_service
        clean_id = client_id.replace("messenger:", "")
        return meta_messenger_service, clean_id
    else:
        return meta_whatsapp_service, client_id

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
                'text': '¿Qué tan satisfecho quedaste con la atención?',
                'options': {
                    '1': 'Muy insatisfecho',
                    '2': 'Insatisfecho',
                    '3': 'Neutral',
                    '4': 'Satisfecho',
                    '5': 'Muy satisfecho'
                },
                'emojis': {
                    '1': '1️⃣',
                    '2': '2️⃣',
                    '3': '3️⃣',
                    '4': '4️⃣',
                    '5': '5️⃣'
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
            conversation.survey_sent_at = datetime.utcnow()
            conversation.survey_question_number = 1

            # Cambiar estado a ENCUESTA_SATISFACCION
            from chatbot.models import EstadoConversacion
            conversation.estado = EstadoConversacion.ENCUESTA_SATISFACCION

            # Construir mensaje de la primera pregunta (sin preámbulo, ya viene del opt-in)
            question_data = self.questions[1]
            message = self._build_question_message(question_data, first_question=True)

            # Enviar mensaje usando el servicio correcto
            service, clean_id = _get_client_messaging_service(client_phone)
            success = service.send_text_message(clean_id, message)
            
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
                # Encuesta completa, guardar resultados y KPIs, luego finalizar
                self._save_survey_results(client_phone, conversation)
                self._save_kpis(conversation)
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
    
    def _build_question_message(self, question_data: Dict, include_instructions: bool = False, first_question: bool = False) -> str:
        """Construye el mensaje de una pregunta de la encuesta"""
        message = ""

        # Solo agregar preámbulo en la primera pregunta
        if first_question:
            message += "¡Perfecto! Comencemos:\n\n"

        message += question_data['text'] + '\n\n'

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
            # Pregunta 1: ¿Pudiste resolver?
            'si': 'Sí',
            'sí': 'Sí',
            'yes': 'Sí',
            'parcialmente': 'Parcialmente',
            'partial': 'Parcialmente',
            'no': 'No',
            # Pregunta 2: ¿Qué tan satisfecho? (escala 1-5)
            'muy insatisfecho': 'Muy insatisfecho',
            'pesimo': 'Muy insatisfecho',
            'pésimo': 'Muy insatisfecho',
            'horrible': 'Muy insatisfecho',
            'insatisfecho': 'Insatisfecho',
            'malo': 'Insatisfecho',
            'mala': 'Insatisfecho',
            'neutral': 'Neutral',
            'normal': 'Neutral',
            'ok': 'Neutral',
            'satisfecho': 'Satisfecho',
            'bueno': 'Satisfecho',
            'buena': 'Satisfecho',
            'bien': 'Satisfecho',
            'muy satisfecho': 'Muy satisfecho',
            'excelente': 'Muy satisfecho',
            'perfecto': 'Muy satisfecho',
            'genial': 'Muy satisfecho'
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

            # Calcular duración del handoff en minutos
            duracion_minutos = 0
            if conversation.handoff_started_at:
                delta = datetime.utcnow() - conversation.handoff_started_at
                duracion_minutos = int(delta.total_seconds() / 60)

            # Formatear survey_accepted como string para claridad
            survey_accepted_str = ''
            if conversation.survey_accepted is True:
                survey_accepted_str = 'accepted'
            elif conversation.survey_accepted is False:
                survey_accepted_str = 'declined'
            elif conversation.survey_accepted is None:
                survey_accepted_str = 'timeout'

            # Formatear nombre del cliente (nombre + inicial de apellido)
            nombre_cliente = ''
            if conversation.nombre_usuario:
                partes = conversation.nombre_usuario.strip().split()
                if len(partes) == 1:
                    nombre_cliente = partes[0]  # Solo nombre
                elif len(partes) >= 2:
                    # Nombre + inicial de apellido
                    nombre_cliente = f"{partes[0]} {partes[1][0]}."

            # Preparar datos para la hoja
            row_data = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # fecha
                self._mask_phone(client_phone),  # telefono_masked
                responses.get('pregunta_1', ''),  # resolvio_problema
                responses.get('pregunta_2', ''),  # amabilidad
                responses.get('pregunta_3', ''),  # volveria_contactar
                duracion_minutos,  # duracion_handoff_minutos
                str(conversation.survey_offered).lower(),  # survey_offered (true/false)
                survey_accepted_str,  # survey_accepted (accepted/declined/timeout)
                nombre_cliente  # nombre_cliente (formato: "Juan P.")
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

    def _save_kpis(self, conversation: ConversacionData) -> bool:
        """
        Calcula y guarda KPIs consolidados en la hoja KPIs.

        Args:
            conversation: Datos de la conversación con encuesta completada

        Returns:
            bool: True si se guardó exitosamente
        """
        try:
            from services.metrics_service import metrics_service

            # Obtener respuestas de la encuesta
            responses = conversation.survey_responses

            # KPI #1: Goal Completion Rate (de esta encuesta específica)
            # Valores: Sí=1, Parcialmente=0.5, No=0
            resolvio = responses.get('pregunta_1', '')
            if resolvio == 'Sí':
                goal_completion = 1.0
            elif resolvio == 'Parcialmente':
                goal_completion = 0.5
            else:
                goal_completion = 0.0

            # KPI #2: Fallback Rate (del día actual)
            # Necesitamos leer METRICS_BUSINESS del día, pero por simplicidad usamos 0
            # (se puede calcular manualmente en Sheets con fórmulas)
            fallback_rate = 0.0  # Placeholder - calcular en Sheets

            # KPI #3: User Rating (convertir respuesta a escala 1-5)
            satisfaccion = responses.get('pregunta_2', '')
            rating_map = {
                'Muy insatisfecho': 1,
                'Insatisfecho': 2,
                'Neutral': 3,
                'Satisfecho': 4,
                'Muy satisfecho': 5
            }
            user_rating = rating_map.get(satisfaccion, 0)

            # KPI #4: Conversation Duration (en minutos)
            duracion_minutos = 0
            if conversation.handoff_started_at:
                delta = datetime.utcnow() - conversation.handoff_started_at
                duracion_minutos = int(delta.total_seconds() / 60)

            # Métricas adicionales
            survey_opt_in_rate = 1.0 if conversation.survey_accepted else 0.0

            volveria = responses.get('pregunta_3', '')
            retention_intent = 1.0 if volveria == 'Sí' else 0.0

            # Preparar fila de KPIs
            kpi_row = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # fecha
                goal_completion,  # goal_completion_rate
                fallback_rate,  # fallback_rate (placeholder)
                user_rating,  # avg_user_rating (1-5)
                duracion_minutos,  # avg_conversation_duration_min
                1,  # total_surveys_completed (esta encuesta)
                survey_opt_in_rate,  # survey_opt_in_rate
                retention_intent  # customer_retention_intent
            ]

            # Enviar a Google Sheets
            success = sheets_service.append_row('kpis', kpi_row)

            if success:
                logger.info(f"✅ KPIs guardados para conversación {conversation.numero_telefono}")
            else:
                logger.error(f"❌ Error guardando KPIs")

            return success

        except Exception as e:
            logger.error(f"Error guardando KPIs: {e}")
            return False

# Instancia global del servicio
survey_service = SurveyService()
