from jinja2 import Template

NLU_INTENT_PROMPT=Template("""
Usuario escribió: "{{mensaje_usuario}}"

Las opciones disponibles son:
1. PRESUPUESTO - cuando el cliente SABE EXACTAMENTE qué necesita: equipos específicos, cantidades definidas, tipos concretos (ej: "necesito 3 matafuegos ABC 5kg", "quiero comprar 2 extintores para oficina")
2. URGENCIA - emergencias, reparaciones inmediatas, problemas urgentes
3. OTRAS - información general, horarios, dudas, consultas varias, visitas técnicas, asesoramiento

EJEMPLOS DE CLASIFICACIÓN:

✅ PRESUPUESTO (cliente sabe exactamente qué necesita):
- "necesito 3 matafuegos ABC de 5kg"
- "quiero comprar 2 extintores para mi oficina"
- "necesito que me fijen 4 matafuegos, 2 placas, 2 carteles"
- "cotización para 10 extintores clase BC"

✅ VISITA_TECNICA (cliente no sabe qué necesita):
- "no sé qué equipos necesito para mi local"
- "necesito que evalúen qué dotación requiere mi empresa"
- "vengan a ver qué necesito instalar"
- "qué tipo de matafuegos necesito?"

Analiza la intención del usuario y responde ÚNICAMENTE con una de estas opciones: PRESUPUESTO, URGENCIA, o OTRAS

Si no puedes determinar la intención con certeza, responde: UNCLEAR
""")


NLU_MESSAGE_PARSING_PROMPT = Template("""
Eres un experto en parsing de datos para servicios contra incendios en Argentina.

Analiza este mensaje y extrae la información de contacto:
"{{mensaje_usuario}}"

REGLAS CRÍTICAS DE EXTRACCIÓN:

**DIRECCIONES** - Solo extraer ubicaciones físicas reales:
✅ EXTRAER: "Av. Corrientes 1234", "Del Valle Centenera 322 piso 4", "Palermo Norte", "Rivadavia 4500"
❌ NO EXTRAER: "Mi mail es...", "email:", "correo:", cualquier línea que mencione email/mail/correo

**EMAILS** - Solo direcciones de correo válidas:
✅ EXTRAER: "juan@empresa.com", "info@local.com.ar"
❌ NO EXTRAER: "por email", "envíen email", "manden correo" (menciones de email, no emails)

**CONSERVADURISMO**: Es mejor dejar un campo vacío ("") que extraer información incorrecta.

**SEPARACIÓN INTELIGENTE**: Una línea puede contener dirección Y horario separados por comas:
- "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h" → direccion + horario_visita

Devuelve JSON con estos campos (cadena vacía si no encuentras):
- "email": email válido
- "direccion": dirección física (SIN el horario si están juntos)
- "horario_visita": horario/disponibilidad (extraído de la misma línea si está con dirección)
- "descripcion": qué necesita específicamente
- "tipo_consulta": PRESUPUESTO, VISITA_TECNICA, URGENCIA, o OTRAS

EJEMPLOS CRÍTICOS:

# EJEMPLO 1: Dirección + horario en una línea
Input: "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h"
Output: {{ "{" }}"direccion": "Del valle centenera 3222 piso 4D", "horario_visita": "15-17h", "email": "", "descripcion": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 2: Email + dirección + descripción completa
Input: "juan@empresa.com, Luis Viale 2020, necesito 4 extintores clase ABC 5kg"
Output: {{ "{" }}"email": "juan@empresa.com", "direccion": "Luis Viale 2020", "descripcion": "necesito 4 extintores clase ABC 5kg", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 3: Solo email (NO extraer como dirección)
Input: "Mi Mail es carlos@hotmail.com"
Output: {{ "{" }}"email": "carlos@hotmail.com", "direccion": "", "descripcion": "", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 4: Solo descripción de necesidad
Input: "Quiero comprar 5 matafuegos para mi local gastronómico"
Output: {{ "{" }}"email": "", "direccion": "", "descripcion": "Quiero comprar 5 matafuegos para mi local gastronómico", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 5: Email mencionado como texto (NO extraer)
Input: "necesito que me envíen por email la cotización"
Output: {{ "{" }}"email": "", "direccion": "", "descripcion": "necesito que me envíen por email la cotización", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 6: Formato "mi X es Y" - extraer correctamente
Input: "mi dirección es Rivadavia 4500 y mi email es jose@empresa.com"
Output: {{ "{" }}"email": "jose@empresa.com", "direccion": "Rivadavia 4500", "descripcion": "", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 7: Solo horario disponible
Input: "Estoy disponible mañanas de 9 a 12"
Output: {{ "{" }}"email": "", "direccion": "", "descripcion": "", "horario_visita": "mañanas de 9 a 12", "tipo_consulta": ""{{ "}" }}

# EJEMPLO 8: Dirección informal pero válida
Input: "Estoy en Palermo cerca del shopping, necesito extintores"
Output: {{ "{" }}"email": "", "direccion": "Palermo cerca del shopping", "descripcion": "necesito extintores", "horario_visita": "", "tipo_consulta": ""{{ "}" }}

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
"Av. Corrientes 1234 CABA" → {{ "{" }}"ubicacion_detectada": "CABA", "confianza": 10, "razon": "menciona CABA explícitamente"{{ "}" }}
"Del valle centenera 3222" → {{ "{" }}"ubicacion_detectada": "UNCLEAR", "confianza": 2, "razon": "no especifica CABA o Provincia"{{ "}" }}
"La Plata centro" → {{ "{" }}"ubicacion_detectada": "PROVINCIA", "confianza": 9, "razon": "La Plata es ciudad de Provincia de Buenos Aires"{{ "}" }}

Responde solo JSON.
""")

# Templates para detección de consultas de contacto
CONTACT_INFO_DETECTION_PROMPT = Template("""
Analiza este mensaje del usuario: "{{mensaje_usuario}}"

¿El usuario está preguntando sobre información de contacto, datos o ubicación de la empresa?

TIPOS DE CONSULTAS DE CONTACTO:
- Teléfono: "cuál es su teléfono", "número de contacto", "como los llamo"
- Dirección: "dónde están ubicados", "cuál es su dirección", "donde los encuentro"
- Horarios: "qué horarios tienen", "cuándo abren", "hasta qué hora atienden"
- Email: "cuál es su email", "correo electrónico"
- Información general: "datos de contacto", "cómo los contacto"

Responde ÚNICAMENTE: CONTACTO o NO

Ejemplos:
"cuál es su teléfono?" → CONTACTO
"necesito un presupuesto" → NO
"dónde están ubicados?" → CONTACTO
"ok, pero cuándo abren?" → CONTACTO
""")

CONTACT_INFO_RESPONSE_PROMPT = Template("""
Responde de manera natural y amigable esta consulta sobre información de contacto de nuestra empresa:

Pregunta del usuario: "{{mensaje_usuario}}"

Información de la empresa {{company_name}}:
- Nombre: {{company_name}}
{% if company_public_phone and company_mobile_phone %}
- Teléfono fijo: {{company_public_phone}}
- Celular: {{company_mobile_phone}}
{% elif company_phone %}
- Teléfono: {{company_phone}}
{% endif %}
- Dirección: {{company_address}}
- Horarios: {{company_hours}}
- Email: {{company_email}}
{% if company_website %}- Web: {{company_website}}{% endif %}

Instrucciones:
1. Responde de manera conversacional y amigable
2. Proporciona la información específica que está pidiendo
3. Si la pregunta es general, da la información más relevante
4. Usa emojis apropiados para hacer la respuesta más visual
5. Mantén un tono profesional pero cercano

Genera una respuesta natural en español.
""")

PERSONALIZED_GREETING_PROMPT = Template("""
Genera un saludo personalizado para WhatsApp como {{bot_name}} de {{company_name}}.

Información del usuario:
- Nombre: {{user_name}}
- Es primera vez: {{is_first_time}}

Instrucciones:
1. Si tiene nombre, úsalo en el saludo
2. Si no tiene nombre, saluda de manera general  
3. Preséntate como {{bot_name}} de {{company_name}}
4. Usa un tono amigable y profesional
6. Incluye emojis apropiados
7. Invita a elegir una opción del menú

Genera un saludo natural en español.
""")