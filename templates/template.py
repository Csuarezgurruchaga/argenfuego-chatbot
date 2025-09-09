from jinja2 import Template

NLU_INTENT_PROMPT=Template("""
Usuario escribió: "{{mensaje_usuario}}"

Las opciones disponibles son:
1. PRESUPUESTO - para compras, cotizaciones, precios, solicitar matafuegos/extintores
2. VISITA_TECNICA - para evaluación, inspección, consultoría en sitio, revisión técnica
3. URGENCIA - emergencias, reparaciones inmediatas, problemas urgentes
4. OTRAS - información general, horarios, dudas, consultas varias

Analiza la intención del usuario y responde ÚNICAMENTE con una de estas opciones: PRESUPUESTO, VISITA_TECNICA, URGENCIA, o OTRAS

Si no puedes determinar la intención con certeza, responde: UNCLEAR
""")


NLU_MESSAGE_PARSING_PROMPT = Template("""
Eres un experto en parsing de datos para servicios contra incendios en Argentina.

Analiza este mensaje y extrae la información de contacto:
"{{mensaje_usuario}}"

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

Input: "juan@empresa.com, Luis Viale 2020, necesito 4 extintores clase ABC 5kg"
Output: {{"email": "juan@empresa.com", "direccion": "Luis Viale 2020", "descripcion": "necesito 4 extintores clase ABC 5kg", "horario_visita": "", "tipo_consulta": ""}}

Input: "pinturerias_rex@rex.com.ar, Av del barco centenera 322, necesito que vengan a ver que matafuegos y elementos necesito para mi local, estamos disponibles de lunes a viernes de 8 a 18hs"
Output: {{"email": "juan@empresa.com", "direccion": "Luis Viale 2020", "descripcion": "necesito que vengan a ver que matafuegos y elementos necesito para mi local", "horario_visita": "8-18h", "tipo_consulta": ""}}

Responde ÚNICAMENTE con JSON válido, sin texto adicional.
""")



NLU_LOCATION_PROMPT=Template("""
Analiza esta dirección en Argentina: "{{direccion}}"

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
""")