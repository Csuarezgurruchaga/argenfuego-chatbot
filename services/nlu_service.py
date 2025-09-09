import os
import logging
import json
from typing import Optional, Dict, Any
from openai import OpenAI
from chatbot.models import TipoConsulta
from ..templates.template import NLU_INTENT_PROMPT, NLU_MESSAGE_PARSING_PROMPT, NLU_LOCATION_PROMPT
from jinja2 import Template

logger = logging.getLogger(__name__)

class NLUService:
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def mapear_intencion(self, mensaje_usuario: str) -> Optional[TipoConsulta]:
        """
        Mapea un mensaje de usuario a una de las opciones disponibles usando LLM
        """
        try:
            prompt = NLU_INTENT_PROMPT.render(mensaje_usuario=mensaje_usuario)

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un clasificador de intenciones para un chatbot de equipos contra incendios. Responde solo con la categoría exacta solicitada."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=10
            )
            
            resultado = response.choices[0].message.content.strip().upper()
            logger.info(f"NLU mapeo: '{mensaje_usuario}' -> '{resultado}'")
            
            # Mapear respuesta a enum
            mapeo = {
                'PRESUPUESTO': TipoConsulta.PRESUPUESTO,
                'VISITA_TECNICA': TipoConsulta.VISITA_TECNICA,
                'URGENCIA': TipoConsulta.URGENCIA,
                'OTRAS': TipoConsulta.OTRAS
            }
            
            return mapeo.get(resultado)
            
        except Exception as e:
            logger.error(f"Error en mapeo de intención: {str(e)}")
            return None
    
    def extraer_datos_estructurados(self, mensaje_usuario: str) -> Dict[str, Any]:
        """
        Extrae datos de contacto de un mensaje usando LLM con enfoque semántico LLM-first
        """
        try:
            prompt = NLU_MESSAGE_PARSING_PROMPT.render(mensaje_usuario=mensaje_usuario)

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un extractor de datos de contacto. Responde solo con JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=200
            )
            
            resultado_text = response.choices[0].message.content.strip()
            logger.info(f"NLU extracción: '{mensaje_usuario}' -> '{resultado_text}'")
            
            # Intentar parsear JSON
            try:
                datos = json.loads(resultado_text)
                return datos
            except json.JSONDecodeError:
                logger.error(f"Error parseando JSON de LLM: {resultado_text}")
                return {}
            
        except Exception as e:
            logger.error(f"Error en extracción de datos: {str(e)}")
            return {}
    
    def validar_campo_individual(self, campo: str, valor: str, contexto: str = "") -> Dict[str, Any]:
        """
        Valida y mejora un campo individual usando LLM
        """
        try:
            prompts_campo = {
                'email': f"¿Es '{valor}' un email válido? Responde: {{'valido': true/false, 'sugerencia': 'email corregido o mensaje'}}",
                'direccion': f"¿Es '{valor}' una dirección válida en Argentina? Responde: {{'valido': true/false, 'sugerencia': 'dirección mejorada o mensaje'}}",
                'horario_visita': f"¿Es '{valor}' un horario/disponibilidad comprensible? Responde: {{'valido': true/false, 'sugerencia': 'horario mejorado o mensaje'}}",
                'descripcion': f"¿Es '{valor}' una descripción clara de servicios contra incendios? Responde: {{'valido': true/false, 'sugerencia': 'descripción mejorada o mensaje'}}"
            }
            
            if campo not in prompts_campo:
                return {'valido': True, 'sugerencia': valor}
            
            prompt = prompts_campo[campo]
            if contexto:
                prompt += f"\nContexto: {contexto}"
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Valida datos de contacto. Responde solo con JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=100
            )
            
            resultado_text = response.choices[0].message.content.strip()
            try:
                return json.loads(resultado_text)
            except json.JSONDecodeError:
                return {'valido': True, 'sugerencia': valor}
            
        except Exception as e:
            logger.error(f"Error validando campo {campo}: {str(e)}")
            return {'valido': True, 'sugerencia': valor}
    
    def detectar_ubicacion_geografica(self, direccion: str) -> Dict[str, Any]:
        """
        Detecta si una dirección especifica CABA o Provincia usando LLM
        """
        try:
            prompt = NLU_LOCATION_PROMPT.render(direccion=direccion)

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un experto en geografía de Buenos Aires, Argentina."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=150
            )
            
            resultado_text = response.choices[0].message.content.strip()
            logger.info(f"Detección ubicación: '{direccion}' -> '{resultado_text}'")
            
            try:
                return json.loads(resultado_text)
            except json.JSONDecodeError:
                return {"ubicacion_detectada": "UNCLEAR", "confianza": 1, "razon": "error parsing JSON"}
                
        except Exception as e:
            logger.error(f"Error detectando ubicación: {str(e)}")
            return {"ubicacion_detectada": "UNCLEAR", "confianza": 1, "razon": "error LLM"}

# Instancia global del servicio
nlu_service = NLUService()