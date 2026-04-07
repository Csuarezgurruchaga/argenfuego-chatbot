import os
import logging
import json
import re
from typing import Optional, Dict, Any
from openai import OpenAI
from chatbot.models import TipoConsulta
from templates.template import NLU_INTENT_PROMPT, NLU_MESSAGE_PARSING_PROMPT
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

# Patrones para detectar intención de hablar con humano/agente
HUMAN_INTENT_PATTERNS = [
    # Palabras clave directas
    r"\bhumano\b",
    r"\bpersona\b",
    r"\balguien\s+real\b",
    r"\batenci[oó]n\s+al\s+cliente\b",
    r"\bagente\b",
    r"\boperador(?:a)?\b",
    r"\brepresentante\b",
    r"\basesor(?:a)?\b",

    # Expresiones comunes
    r"\bquiero\s+hablar\b",
    r"\bnecesito\s+hablar\b",
    r"\bpuedo\s+hablar\b",
    r"\bhablar\s+con\s+(?:alguien|una\s+persona)\b",
    r"\bquiero\s+hablar\s+con\s+(?:alguien|una\s+persona)\b",
    r"\bquiero\s+hablar\s+con\s+(?:vos|ustedes)\b",
    r"\bnecesito\s+hablar\s+con\s+(?:alguien|una\s+persona)\b",
    r"\bcomunicar(?:me)?\s+con\s+(?:alguien|una\s+persona)\b",
    r"\bnecesito\s+un\s+tel[eé]fono\b",
    r"\btelefono\s+para\s+llamar(?:los|las)?\b",
    r"\bquiero\s+llamar\b",

    # Frustración / fallback
    r"no\s+me\s+entend[eé]s?",
    r"ninguna\s+opci[oó]n",
    r"ninguna\s+de\s+las\s+anteriores",
    r"quiero\s+que\s+me\s+atiendan?",

    # Mayúsculas / errores comunes
    r"HABLAR\s+CON\s+HUMANO",
    r"humnao",
    r"operadro",
]

CONTACT_RESPONSE_FIELD_PATTERNS = {
    "phone": [
        r"\b(?:cu[aá]l|cual)\s+es\s+su\s+(?:tel[eé]fono|n[uú]mero|numero)",
        r"\b(?:n[uú]mero|numero)\s+de\s+(?:tel[eé]fono|contacto)",
        r"\b(?:llamo|llamarlos|llamarlas|contacto|contactarlos|contactarlas)\b",
        r"\btel[eé]fonos?\b",
    ],
    "address": [
        r"\b(?:d[oó]nde|donde)\s+(?:est[aá]n|estan|queda|quedan)\b",
        r"\b(?:cu[aá]l|cual)\s+es\s+su\s+direcci[oó]n\b",
        r"\b(?:direcci[oó]n|ubicaci[oó]n|ubicados|ubicada)\b",
    ],
    "hours": [
        r"\b(?:cu[aá]ndo|cuando)\s+(?:abren|abre|atienden)\b",
        r"\b(?:qu[eé]|que)\s+horarios?\s+tienen\b",
        r"\bhasta\s+(?:qu[eé]|que)\s+hora\b",
        r"\bhorarios?\b",
    ],
    "email": [
        r"\b(?:cu[aá]l|cual)\s+es\s+su\s+(?:email|correo)\b",
        r"\bcorreo(?:\s+electr[oó]nico)?\b",
        r"\bmail\b",
    ],
    "website": [
        r"\b(?:web|sitio\s+web|p[aá]gina\s+web|pagina\s+web|website)\b",
    ],
}

CONTACT_SUMMARY_PATTERNS = [
    r"\bdatos?\s+de\s+contacto\b",
    r"\binformaci[oó]n\s+de\s+contacto\b",
    r"\b(?:todos|toda)\s+sus\s+datos\b",
    r"\bc[oó]mo\s+(?:los|las)\s+contacto\b",
]

class NLUService:
    
    def __init__(self):
        self._client = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY es requerido para usar NLU LLM")
            self._client = OpenAI(api_key=api_key)
        return self._client
    
    def mapear_intencion(self, mensaje_usuario: str) -> Optional[TipoConsulta]:
        """
        Mapea un mensaje de usuario a una de las opciones disponibles usando LLM
        """
        try:
            prompt = NLU_INTENT_PROMPT.render(mensaje_usuario=mensaje_usuario)

            response = self._get_client().chat.completions.create(
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

            response = self._get_client().chat.completions.create(
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
            
            response = self._get_client().chat.completions.create(
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

    @staticmethod
    def _normalize_text(text: str) -> str:
        import unicodedata

        text = (text or "").lower().strip()
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

    def _extract_requested_contact_fields(self, mensaje_usuario: str, include_website: bool = True) -> list[str]:
        normalized = self._normalize_text(mensaje_usuario)
        requested_fields = []

        for field, patterns in CONTACT_RESPONSE_FIELD_PATTERNS.items():
            if field == "website" and not include_website:
                continue
            if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
                requested_fields.append(field)

        wants_summary = any(
            re.search(pattern, normalized, re.IGNORECASE)
            for pattern in CONTACT_SUMMARY_PATTERNS
        )

        if wants_summary or not requested_fields:
            requested_fields = ["phone", "address", "hours", "email"]
            if include_website:
                requested_fields.append("website")

        return requested_fields

    @staticmethod
    def _build_contact_response(profile: Dict[str, Any], requested_fields: list[str]) -> str:
        company_name = profile['name']
        lines = []

        if len(requested_fields) > 1:
            lines.append(f"📞 *Información de contacto de {company_name}*")
        elif requested_fields == ["phone"]:
            lines.append(f"📞 *Teléfonos de {company_name}*")
        elif requested_fields == ["address"]:
            lines.append(f"📍 *Dirección de {company_name}*")
        elif requested_fields == ["hours"]:
            lines.append(f"🕒 *Horarios de {company_name}*")
        elif requested_fields == ["email"]:
            lines.append(f"📧 *Email de {company_name}*")
        elif requested_fields == ["website"]:
            lines.append(f"🌐 *Web de {company_name}*")
        else:
            lines.append(f"📞 *Información de contacto de {company_name}*")

        if isinstance(profile.get('phone'), dict):
            public_phone = profile['phone'].get('public_phone', '')
            mobile_phone = profile['phone'].get('mobile_phone', '')
        else:
            public_phone = profile.get('phone', '')
            mobile_phone = ''

        for field in requested_fields:
            if field == "phone":
                if public_phone:
                    lines.append(f"📞 Teléfono fijo: {public_phone}")
                if mobile_phone:
                    lines.append(f"📱 Celular / WhatsApp: {mobile_phone}")
            elif field == "address" and profile.get("address"):
                lines.append(f"📍 Dirección: {profile['address']}")
            elif field == "hours" and profile.get("hours"):
                lines.append(f"🕒 Horarios: {profile['hours']}")
            elif field == "email" and profile.get("email"):
                lines.append(f"📧 Email: {profile['email']}")
            elif field == "website" and profile.get("website"):
                lines.append(f"🌐 Web: {profile['website']}")

        lines.append("")
        lines.append("Si necesitás otro dato puntual, decímelo y te lo paso.")
        return "\n".join(lines).strip()
    
    
    def detectar_consulta_contacto(self, mensaje_usuario: str) -> bool:
        """
        Detecta si el usuario está preguntando sobre información de contacto de la empresa usando regex
        """
        try:
            # Normalización básica: minúsculas y remover tildes
            import unicodedata
            def _normalize(s: str) -> str:
                s = s.lower().strip()
                return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

            mensaje_lower = _normalize(mensaje_usuario)
            
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

    def detectar_solicitud_humano(self, mensaje_usuario: str) -> bool:
        """
        Detecta si el usuario solicita hablar con un humano/agente.
        Usa patrones regex tolerantes a acentos y variaciones comunes.
        """
        try:
            # Normalización básica
            import unicodedata
            def _normalize(s: str) -> str:
                s = s.lower().strip()
                return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

            mensaje_lower = _normalize(mensaje_usuario)

            # Negaciones simples para evitar falsos positivos
            negaciones = [
                r"no\s+quiero\s+hablar",
                r"no\s+humano",
                r"sin\s+humano",
            ]
            for neg in negaciones:
                if re.search(neg, mensaje_lower, re.IGNORECASE):
                    logger.info(f"Detección humano (regex): '{mensaje_usuario}' -> NO (negación)")
                    return False

            for pattern in HUMAN_INTENT_PATTERNS:
                if re.search(pattern, mensaje_lower, re.IGNORECASE):
                    logger.info(f"Detección humano (regex): '{mensaje_usuario}' -> HUMANO (pattern: {pattern})")
                    return True

            logger.info(f"Detección humano (regex): '{mensaje_usuario}' -> NO")
            return False
        except Exception as e:
            logger.error(f"Error detectando solicitud humano: {str(e)}")
            return False

    def generar_respuesta_humano(self, mensaje_usuario: str = "") -> str:
        """
        Genera un mensaje con teléfonos para hablar con una persona.
        Aclara que el teléfono público es solo para llamadas con una persona.
        """
        try:
            profile = get_active_company_profile()

            public_phone = ""
            mobile_phone = ""
            phone_single = ""

            if isinstance(profile.get('phone'), dict):
                public_phone = profile['phone'].get('public_phone', '')
                mobile_phone = profile['phone'].get('mobile_phone', '')
            else:
                phone_single = profile.get('phone', '')

            partes = [
                "👤 Si necesitás hablar con una persona ahora mismo:",
            ]

            if public_phone:
                partes.append(f"📞 Teléfono fijo (solo llamadas para hablar con una persona): {public_phone}")
            if mobile_phone:
                partes.append(f"📱 Celular / WhatsApp: {mobile_phone}")
            if not public_phone and not mobile_phone and phone_single:
                partes.append(f"📱 Teléfono: {phone_single}")

            partes.append("")
            partes.append("Si preferís, también puedo ayudarte por acá y luego te deriva un asesor 🙌")

            return "\n".join(partes).strip()
        except Exception as e:
            logger.error(f"Error generando respuesta humano: {str(e)}")
            # Fallback a info general de contacto
            return get_company_info_text()
    
    def generar_respuesta_contacto(self, mensaje_usuario: str) -> str:
        """
        Genera una respuesta determinística sobre información de contacto de la empresa.
        No usa LLM para evitar que texto arbitrario del usuario termine afectando
        la redacción de salida.
        """
        try:
            company_profile = get_active_company_profile()
            requested_fields = self._extract_requested_contact_fields(
                mensaje_usuario,
                include_website=bool(company_profile.get("website")),
            )
            respuesta = self._build_contact_response(company_profile, requested_fields)
            logger.info(
                "Respuesta contacto determinística para '%s' con campos %s",
                mensaje_usuario,
                requested_fields,
            )
            return respuesta
        except Exception as e:
            logger.error(f"Error generando respuesta de contacto: {str(e)}")
            return get_company_info_text()
    
# Instancia global del servicio
nlu_service = NLUService()
