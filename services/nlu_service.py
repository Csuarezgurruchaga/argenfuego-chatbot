import os
import logging
import json
from typing import Optional, Dict, Any
from openai import OpenAI
from chatbot.models import TipoConsulta

logger = logging.getLogger(__name__)

class NLUService:
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def mapear_intencion(self, mensaje_usuario: str) -> Optional[TipoConsulta]:
        """
        Mapea un mensaje de usuario a una de las opciones disponibles usando LLM
        """
        try:
            prompt = f"""
Usuario escribió: "{mensaje_usuario}"

Las opciones disponibles son:
1. PRESUPUESTO - para compras, cotizaciones, precios, solicitar matafuegos/extintores
2. VISITA_TECNICA - para evaluación, inspección, consultoría en sitio, revisión técnica
3. URGENCIA - emergencias, reparaciones inmediatas, problemas urgentes
4. OTRAS - información general, horarios, dudas, consultas varias

Analiza la intención del usuario y responde ÚNICAMENTE con una de estas opciones: PRESUPUESTO, VISITA_TECNICA, URGENCIA, o OTRAS

Si no puedes determinar la intención con certeza, responde: UNCLEAR
"""

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
        Extrae datos de contacto de un mensaje usando LLM cuando el usuario envía todo junto
        """
        try:
            prompt = f"""
Extrae la información de contacto del siguiente mensaje de un usuario que solicita servicios de equipos contra incendios:

"{mensaje_usuario}"

Devuelve un JSON con estos campos (si no encuentras algún dato, usa cadena vacía):
- "email": dirección de correo electrónico
- "direccion": dirección física completa
- "horario_visita": horario o disponibilidad para visita
- "descripcion": descripción de lo que necesita
- "tipo_consulta": PRESUPUESTO, VISITA_TECNICA, URGENCIA, o OTRAS

Ejemplo de respuesta:
{{"email": "juan@empresa.com", "direccion": "Av. Corrientes 1234", "horario_visita": "lunes a viernes 9-17", "descripcion": "necesito matafuegos para oficina", "tipo_consulta": "PRESUPUESTO"}}

Responde ÚNICAMENTE con el JSON, sin texto adicional.
"""

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

# Instancia global del servicio
nlu_service = NLUService()