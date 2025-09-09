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
        Extrae datos de contacto de un mensaje usando LLM con enfoque semántico LLM-first
        """
        try:
            prompt = f"""
Eres un experto en parsing de datos para servicios contra incendios en Argentina.

Analiza este mensaje y extrae la información de contacto:
"{mensaje_usuario}"

INSTRUCCIONES ESPECÍFICAS:
1. **Direcciones**: Pueden incluir múltiples campos en una línea (ej: "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h")
2. **Horarios**: Busca patrones como "15-17h", "pueden pasar de X a Y", "disponible mañana", "lunes a viernes"
3. **Context clues**: "pueden pasar", "disponible", "vengan" indican horarios
4. **Separación inteligente**: Una línea puede contener dirección Y horario separados por comas/conjunciones

Devuelve JSON con estos campos (cadena vacía si no encuentras):
- "email": email válido
- "direccion": dirección física (SIN el horario si están juntos)
- "horario_visita": horario/disponibilidad (extraído de la misma línea si está con dirección)
- "descripcion": qué necesita específicamente
- "tipo_consulta": PRESUPUESTO, VISITA_TECNICA, URGENCIA, o OTRAS

EJEMPLOS:
Input: "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h"
Output: {{"direccion": "Del valle centenera 3222 piso 4D", "horario_visita": "15-17h", "email": "", "descripcion": "", "tipo_consulta": ""}}

Input: "juan@empresa.com, Palermo cerca del shopping, necesito extintores clase ABC"
Output: {{"email": "juan@empresa.com", "direccion": "Palermo cerca del shopping", "descripcion": "necesito extintores clase ABC", "horario_visita": "", "tipo_consulta": ""}}

Responde ÚNICAMENTE con JSON válido, sin texto adicional.
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
    
    def detectar_ubicacion_geografica(self, direccion: str) -> Dict[str, Any]:
        """
        Detecta si una dirección especifica CABA o Provincia usando LLM
        """
        try:
            prompt = f"""
Analiza esta dirección en Argentina: "{direccion}"

¿La dirección especifica claramente si es CABA o Provincia de Buenos Aires?

SINÓNIMOS CABA: CABA, Ciudad Autónoma, Capital, Capital Federal, C.A.B.A, Microcentro, Palermo, Recoleta, San Telmo, etc.
SINÓNIMOS PROVINCIA: Provincia, Prov, Buenos Aires, Bs As, GBA, Gran Buenos Aires, Zona Norte, Zona Oeste, Zona Sur, La Plata, etc.

Responde JSON:
- "ubicacion_detectada": "CABA", "PROVINCIA", o "UNCLEAR"
- "confianza": número del 1 al 10
- "razon": explicación breve

Ejemplos:
"Av. Corrientes 1234 CABA" → {{"ubicacion_detectada": "CABA", "confianza": 10, "razon": "menciona CABA explícitamente"}}
"Del valle centenera 3222" → {{"ubicacion_detectada": "UNCLEAR", "confianza": 2, "razon": "no especifica CABA o Provincia"}}
"La Plata centro" → {{"ubicacion_detectada": "PROVINCIA", "confianza": 9, "razon": "La Plata es ciudad de Provincia de Buenos Aires"}}

Responde solo JSON.
"""

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