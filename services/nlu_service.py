import os
import logging
import json
import re
from typing import Optional, Dict, Any
from openai import OpenAI
from chatbot.models import TipoConsulta
from templates.template import NLU_INTENT_PROMPT, NLU_MESSAGE_PARSING_PROMPT, NLU_LOCATION_PROMPT, CONTACT_INFO_DETECTION_PROMPT, CONTACT_INFO_RESPONSE_PROMPT, PERSONALIZED_GREETING_PROMPT
from config.company_profiles import get_active_company_profile, get_company_info_text

logger = logging.getLogger(__name__)

# Patrones regex para detectar consultas específicas de contacto empresarial
CONTACT_QUERY_PATTERNS = [
    # Teléfono
    r'\b(?:cuál|cual)\s+es\s+su\s+(?:teléfono|telefono|número|numero)',
    r'\b(?:número|numero)\s+de\s+(?:teléfono|telefono)',
    r'\b(?:cómo|como)\s+(?:los|las)\s+(?:contacto|llamo)',
    r'\bteléfonos?\b.*\b(?:empresa|ustedes|su)',
    
    # Dirección
    r'\b(?:dónde|donde)\s+(?:están|esta|estan)\s+(?:ubicados|ubicada)',
    r'\b(?:cuál|cual)\s+es\s+su\s+dirección',
    r'\b(?:dónde|donde)\s+(?:los|las)\s+encuentro',
    
    # Horarios
    r'\b(?:cuándo|cuando)\s+(?:abren|abre|atienden)',
    r'\b(?:qué|que)\s+horarios?\s+tienen',
    r'\bhasta\s+(?:qué|que)\s+hora',
    r'\bhorarios?\b.*\b(?:empresa|ustedes)',
    
    # Email
    r'\b(?:cuál|cual)\s+es\s+su\s+(?:email|correo)',
    r'\bcorreo\s+electrónico\b.*\b(?:empresa|ustedes)',
    
    # Información general
    r'\bdatos?\s+de\s+contacto\b',
    r'\binformación\s+de\s+contacto\b',
    r'\b(?:cómo|como)\s+(?:los|las)\s+contacto\b'
]

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
    
    def detectar_consulta_contacto(self, mensaje_usuario: str) -> bool:
        """
        Detecta si el usuario está preguntando sobre información de contacto de la empresa usando regex
        """
        try:
            mensaje_lower = mensaje_usuario.lower().strip()
            
            # Buscar coincidencias con los patrones de consulta de contacto
            for pattern in CONTACT_QUERY_PATTERNS:
                if re.search(pattern, mensaje_lower, re.IGNORECASE):
                    logger.info(f"Detección consulta contacto (regex): '{mensaje_usuario}' -> CONTACTO (pattern: {pattern})")
                    return True
            
            logger.info(f"Detección consulta contacto (regex): '{mensaje_usuario}' -> NO")
            return False
            
        except Exception as e:
            logger.error(f"Error detectando consulta de contacto: {str(e)}")
            return False
    
    def generar_respuesta_contacto(self, mensaje_usuario: str) -> str:
        """
        Genera una respuesta natural sobre información de contacto de la empresa
        """
        try:
            company_profile = get_active_company_profile()
            
            # Manejar tanto formato de teléfono dict como string para compatibilidad
            template_params = {
                'mensaje_usuario': mensaje_usuario,
                'company_name': company_profile['name'],
                'company_address': company_profile['address'],
                'company_hours': company_profile['hours'],
                'company_email': company_profile['email'],
                'company_website': company_profile.get('website', '')
            }
            
            # Agregar parámetros de teléfono según el formato
            if isinstance(company_profile['phone'], dict):
                template_params['company_public_phone'] = company_profile['phone'].get('public_phone', '')
                template_params['company_mobile_phone'] = company_profile['phone'].get('mobile_phone', '')
                template_params['company_phone'] = ''
            else:
                template_params['company_phone'] = company_profile['phone']
                template_params['company_public_phone'] = ''
                template_params['company_mobile_phone'] = ''
            
            prompt = CONTACT_INFO_RESPONSE_PROMPT.render(**template_params)

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": f"Eres {company_profile['bot_name']}, asistente virtual de {company_profile['name']}. Responde de manera amigable y profesional."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )
            
            respuesta = response.choices[0].message.content.strip()
            logger.info(f"Respuesta contacto generada para: '{mensaje_usuario}'")
            
            return respuesta
            
        except Exception as e:
            logger.error(f"Error generando respuesta de contacto: {str(e)}")
            # Fallback a respuesta estática si falla el LLM
            return get_company_info_text()
    
    def generar_saludo_personalizado(self, nombre_usuario: str = "", es_primera_vez: bool = True) -> str:
        """
        Genera un saludo personalizado usando el nombre del usuario si está disponible
        """
        try:
            company_profile = get_active_company_profile()
            
            prompt = PERSONALIZED_GREETING_PROMPT.render(
                bot_name=company_profile['bot_name'],
                company_name=company_profile['name'],
                user_name=nombre_usuario or "sin nombre",
                is_first_time=es_primera_vez
            )

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": f"Eres {company_profile['bot_name']}, asistente virtual amigable de {company_profile['name']}. Genera saludos naturales y profesionales."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=150
            )
            
            saludo = response.choices[0].message.content.strip()
            logger.info(f"Saludo personalizado generado para usuario: '{nombre_usuario}'")
            
            return saludo
            
        except Exception as e:
            logger.error(f"Error generando saludo personalizado: {str(e)}")
            # Fallback a saludo estático si falla el LLM
            company_profile = get_active_company_profile()
            if nombre_usuario:
                return f"¡Hola {nombre_usuario}! 👋 Soy {company_profile['bot_name']} de {company_profile['name']}"
            else:
                return f"¡Hola! 👋 Soy {company_profile['bot_name']} de {company_profile['name']}"

# Instancia global del servicio
nlu_service = NLUService()