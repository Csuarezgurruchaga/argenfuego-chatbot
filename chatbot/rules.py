import os
import re
import unicodedata
from typing import Optional
from .models import EstadoConversacion, TipoConsulta
from .states import conversation_manager
from config.company_profiles import get_urgency_redirect_message, get_active_company_profile
from datetime import datetime, timedelta
from services.error_reporter import error_reporter, ErrorTrigger
from services.metrics_service import metrics_service

POST_FINALIZADO_WINDOW_SECONDS = int(os.getenv("POST_FINALIZADO_WINDOW_SECONDS", "120"))
POST_FINALIZADO_ACK_MESSAGE = os.getenv(
    "POST_FINALIZADO_ACK_MESSAGE",
    "¡Gracias por tu mensaje! Ya registramos tu solicitud. Si necesitás otra cosa, escribime \"hola\" para comenzar de nuevo. 🤖",
)

def normalizar_texto(texto: str) -> str:
    """
    Normaliza texto: lowercase + sin acentos + sin espacios + sin puntos
    """
    texto = texto.lower().strip()
    # Remover acentos
    sin_acentos = ''.join(c for c in unicodedata.normalize('NFD', texto) 
                          if unicodedata.category(c) != 'Mn')
    # Remover espacios y puntos para mejor matching (bsas = bs as = bs. as.)
    return sin_acentos.replace(' ', '').replace('.', '')

# Mapeo de sinónimos para validación geográfica (solo minúsculas, se normalizan automáticamente)
SINONIMOS_CABA = [
    'caba', 'c.a.b.a', 'ciudad autonoma', 
    'capital', 'capital federal', 'microcentro', 'palermo', 
    'recoleta', 'san telmo', 'puerto madero', 'belgrano',
    'barracas', 'boca', 'caballito', 'flores', 'once',
    'retiro', 'villa crespo', 'almagro', 'balvanera'
]

SINONIMOS_PROVINCIA = [
    'provincia', 'prov', 'buenos aires', 'bs as', 'bs. as.',
    'gba', 'gran buenos aires', 'zona norte', 'zona oeste', 
    'zona sur', 'la plata', 'quilmes', 'lomas de zamora',
    'san isidro', 'tigre', 'pilar', 'escobar', 'moreno',
    'merlo', 'moron', 'tres de febrero', 'vicente lopez',
    'avellaneda', 'lanus', 'berazategui', 'florencio varela',
    'ramos mejia'
]

# Sets pre-computados normalizados para búsqueda O(1)
SINONIMOS_CABA_NORM = {normalizar_texto(s) for s in SINONIMOS_CABA}
SINONIMOS_PROVINCIA_NORM = {normalizar_texto(s) for s in SINONIMOS_PROVINCIA}

class ChatbotRules:
    MENU_OPTIONS = (
        {
            "id": "presupuesto",
            "title": "📋 Presupuesto",
            "text": "Solicitar un presupuesto",
            "tipo": TipoConsulta.PRESUPUESTO,
        },
        {
            "id": "urgencia",
            "title": "🚨 Urgencia",
            "text": "Reportar una urgencia",
            "tipo": TipoConsulta.URGENCIA,
        },
        {
            "id": "otras",
            "title": "❓ Otras consultas",
            "text": "Otras consultas",
            "tipo": TipoConsulta.OTRAS,
        },
    )
    MENU_NUMBER_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
    MENU_MATCH_PRIORITY = ("urgencia", "presupuesto", "otras")
    MENU_STOPWORDS = {"un", "una", "de", "del", "la", "el", "las", "los", "para", "por", "a", "y", "en"}
    EXTRA_MENU_KEYWORDS = {
        "presupuesto": ["cotizacion", "cotización", "cotizar", "presupuestar"],
        "urgencia": ["urgente", "emergencia", "emergente"],
        "otras": ["consulta", "consultas", "informacion", "información", "visita", "visitas"],
    }
    _MENU_KEYWORDS = None

    GRATITUDE_KEYWORDS = {
        "gracias",
        "muchas gracias",
        "mil gracias",
        "gracias totales",
        "gracias eva",
        "gracias genia",
        "gracias por todo",
        "gracias!!!",
        "gracias!!",
        "genial gracias",
        "buenísimo gracias",
        "graciass",
        "graciasss",
        "grac",
        "thank you",
        "thanks",
    }
    GRATITUDE_EMOJIS = {"🙏", "🤝", "👍", "🙌", "😊", "😁", "🤗", "👌"}
    PRESUPUESTO_MENU_ROWS = (
        {
            "id": "presupuesto_extintores",
            "title": "🧯 Extintores",
            "aliases": ("🧯 Matafuegos/Extintores", "matafuegos/extintores", "matafuegos", "extintores"),
        },
        {
            "id": "presupuesto_ifci",
            "title": "💧 IFCI",
            "aliases": ("💧 IFCI (Hidrantes)", "ifci (hidrantes)", "hidrantes"),
        },
        {
            "id": "presupuesto_combo",
            "title": "🧯+💧 Ambos",
            "aliases": ("🧯+💧 Matafuegos y IFCI", "matafuegos y ifci", "ambos"),
        },
    )
    EXTINTOR_PRODUCT_ROWS = (
        {"id": "extintor_vehicular_1kg", "title": "Vehicular (1 kg)", "capacidad": "1 kg", "tipo": "PQ (ABC)", "plazo": "24h", "detalle_plazo": "*Según disponibilidad del taller."},
        {"id": "extintor_pq_5kg", "title": "Extintor 5kg PQ (ABC)", "capacidad": "5 kg", "tipo": "PQ (ABC)", "plazo": "72h", "detalle_plazo": "*Según disponibilidad del taller."},
        {"id": "extintor_pq_10kg", "title": "Extintor 10kg PQ (ABC)", "capacidad": "10 kg", "tipo": "PQ (ABC)", "plazo": "72h", "detalle_plazo": "*Según disponibilidad del taller."},
        {"id": "extintor_co2_5kg", "title": "Extintor 5kg CO2 (BC)", "capacidad": "5 kg", "tipo": "CO2 (BC)", "plazo": "72h", "detalle_plazo": "*Según disponibilidad del taller y vigencia de la PH."},
        {"id": "extintor_otro", "title": "Otro"},
    )
    PRESUPUESTO_CONTACT_BUTTONS = (
        {"id": "presupuesto_contacto_si", "title": "Sí"},
        {"id": "presupuesto_contacto_no", "title": "No, muchas gracias"},
        {"id": "presupuesto_contacto_back", "title": "↩️ Volver"},
    )
    PRESUPUESTO_SERVICIO_BUTTONS = (
        {"id": "presupuesto_compra", "title": "Equipo nuevo"},
        {"id": "presupuesto_mantenimiento", "title": "Mantenimiento"},
    )
    PRESUPUESTO_CANTIDAD_ROWS = (
        {"id": "cantidad_1", "title": "1"},
        {"id": "cantidad_2", "title": "2"},
        {"id": "cantidad_otra", "title": "Otra cantidad"},
    )
    IFCI_NIVEL_ROWS = (
        {
            "id": "ifci_nivel_1",
            "title": "Nivel 1: Cañería seca",
            "value": "Nivel 1: Cañería seca",
            "aliases": ("1",),
        },
        {
            "id": "ifci_nivel_2",
            "title": "Nivel 2: Cañería humeda",
            "value": "Nivel 2: Cañería húmeda (Aysa)",
            "aliases": ("2", "Nivel 2: Cañería húmeda (Aysa)", "Nivel 2: Cañería húmeda Aysa"),
        },
        {
            "id": "ifci_nivel_3",
            "title": "Nivel 3: Cañería humeda",
            "value": "Nivel 3: Cañería húmeda (con bombas)",
            "aliases": ("3", "Nivel 3: Cañería húmeda (con bombas)", "Nivel 3: Cañería húmeda con bombas"),
        },
        {
            "id": "ifci_nivel_no_se",
            "title": "No sé",
            "value": "No sé",
            "aliases": ("4",),
        },
    )
    IFCI_BINARY_BUTTONS = (
        {"id": "ifci_si", "title": "Sí"},
        {"id": "ifci_no", "title": "No"},
        {"id": "ifci_no_se", "title": "No sé"},
    )
    IFCI_CORRECTION_OPTIONS = {
        "1": "email",
        "2": "direccion",
        "3": "horario_visita",
        "4": "razon_social",
        "5": "cuit",
        "6": "ifci_nivel",
        "7": "ifci_hidrantes",
        "8": "ifci_establecimiento",
        "9": "ifci_detectores",
        "10": "ifci_plano",
        "11": "todo",
    }

    @staticmethod
    def _normalized_choice(text: str) -> str:
        return ChatbotRules._normalize_menu_text(text or "")

    @staticmethod
    def _matches_choice(text: str, *choices: str) -> bool:
        normalized = ChatbotRules._normalized_choice(text)
        return any(normalized == ChatbotRules._normalized_choice(choice) for choice in choices)

    @classmethod
    def _find_row_by_id(cls, rows, row_id: str):
        for row in rows:
            if row["id"] == row_id:
                return row
        return None

    @classmethod
    def _find_row_by_text(cls, rows, message: str):
        normalized = cls._normalized_choice(message)
        for row in rows:
            candidates = {
                cls._normalized_choice(row["id"]),
                cls._normalized_choice(row["title"]),
            }
            for alias in row.get("aliases", ()):
                candidates.add(cls._normalized_choice(alias))
            if normalized in candidates:
                return row
        return None

    @classmethod
    def _get_menu_options(cls):
        return cls.MENU_OPTIONS

    @classmethod
    def _build_menu_lines(cls) -> str:
        lines = []
        for idx, option in enumerate(cls.MENU_OPTIONS, start=1):
            emoji = cls.MENU_NUMBER_EMOJI.get(idx, f"{idx}️⃣")
            lines.append(f"{emoji} {option['text']}")
        return "\n".join(lines)

    @classmethod
    def _normalize_menu_text(cls, text: str) -> str:
        text = text.lower().strip()
        text = ''.join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        )
        text = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in text)
        return " ".join(text.split())

    @classmethod
    def _get_menu_keywords(cls) -> dict:
        if cls._MENU_KEYWORDS is not None:
            return cls._MENU_KEYWORDS
        keywords = {}
        for option in cls.MENU_OPTIONS:
            tokens = set()
            for raw in (option["id"], option["text"], option["title"]):
                normalized = cls._normalize_menu_text(raw)
                if normalized:
                    tokens.update(normalized.split())
            for extra in cls.EXTRA_MENU_KEYWORDS.get(option["id"], []):
                normalized = cls._normalize_menu_text(extra)
                if normalized:
                    tokens.update(normalized.split())
            tokens = {t for t in tokens if t not in cls.MENU_STOPWORDS and len(t) > 2}
            keywords[option["id"]] = tokens
        cls._MENU_KEYWORDS = keywords
        return keywords

    @classmethod
    def _get_menu_option_by_id(cls, option_id: str):
        for option in cls.MENU_OPTIONS:
            if option["id"] == option_id:
                return option
        return None

    @classmethod
    def _match_menu_option(cls, mensaje: str):
        if not mensaje:
            return None, ""
        digits = re.findall(r"\d", mensaje)
        if len(digits) == 1:
            idx = int(digits[0])
            if 1 <= idx <= len(cls.MENU_OPTIONS):
                return cls.MENU_OPTIONS[idx - 1], "number"
        normalized = cls._normalize_menu_text(mensaje)
        if not normalized:
            return None, ""
        for option in cls.MENU_OPTIONS:
            if normalized == option["id"]:
                return option, "id"
        message_tokens = set(normalized.split())
        keywords = cls._get_menu_keywords()
        for option_id in cls.MENU_MATCH_PRIORITY:
            if keywords.get(option_id, set()) & message_tokens:
                return cls._get_menu_option_by_id(option_id), "keyword"
        return None, ""

    @classmethod
    def _build_menu_prompt(cls) -> str:
        return f"""

¿En qué puedo ayudarte hoy? Por favor selecciona una opción:

{cls._build_menu_lines()}

Responde con el número de la opción que necesitas 📱"""
    
    @staticmethod
    def _normalizar_agradecimiento(texto: str) -> str:
        texto = texto.strip().lower()
        texto = ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        )
        texto = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in texto)
        texto = " ".join(texto.split())
        return texto
    
    @staticmethod
    def es_mensaje_agradecimiento(texto: str) -> bool:
        if not texto:
            return False
        
        raw = texto.strip()
        # Emojis o reacciones cortas
        if raw and len(raw) <= 8 and any(emoji in raw for emoji in ChatbotRules.GRATITUDE_EMOJIS):
            return True
        
        normalizado = ChatbotRules._normalizar_agradecimiento(raw)
        if not normalizado:
            return False
        
        if normalizado in ChatbotRules.GRATITUDE_KEYWORDS:
            return True
        
        compact = normalizado.replace(" ", "")
        if compact in {"gracias", "muchasgracias", "milgracias", "graciass", "graciasss", "thankyou"}:
            return True
        
        for keyword in ChatbotRules.GRATITUDE_KEYWORDS:
            if keyword in normalizado:
                return True
        
        palabras = set(normalizado.split())
        if "gracias" in palabras or "thanks" in palabras:
            return True
        
        return False
    
    @staticmethod
    def get_mensaje_post_finalizado_gracias() -> str:
        return POST_FINALIZADO_ACK_MESSAGE
    
    @staticmethod
    def _detectar_volver_menu(mensaje: str) -> bool:
        """
        Detecta si el usuario quiere volver al menú principal
        """
        mensaje_lower = mensaje.lower().strip()
        frases_menu = [
            'volver', 'menu', 'menú', 'inicio', 'empezar de nuevo',
            'me equivoqué', 'me equivoque', 'error', 'atrás', 'atras',
            'menu principal', 'menú principal', 'opción', 'opcion',
            'elegir otra', 'cambiar opción', 'cambiar opcion'
        ]
        
        return any(frase in mensaje_lower for frase in frases_menu)

    @staticmethod
    def _detectar_volver_local(mensaje: str) -> bool:
        return ChatbotRules._matches_choice(
            mensaje,
            "volver",
            "volver al menu anterior",
            "volver al menú anterior",
            "menu anterior",
            "menú anterior",
        )

    @staticmethod
    def _manejar_menu_principal(numero_telefono: str, nombre_usuario: str = "") -> str:
        conversation_manager.clear_datos_temporales(numero_telefono)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
        try:
            ChatbotRules.send_menu_interactivo(numero_telefono, nombre_usuario)
        except Exception:
            pass
        return "↩️ *Volviendo al menú principal...*"

    @staticmethod
    def _activar_handoff(numero_telefono: str, mensaje_contexto: str):
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.ATENDIDO_POR_HUMANO)
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        conversacion.atendido_por_humano = True
        conversacion.handoff_started_at = datetime.utcnow()
        conversacion.mensaje_handoff_contexto = mensaje_contexto
        conversation_manager.add_to_handoff_queue(numero_telefono)

    @staticmethod
    def _aplicar_tipo_consulta(numero_telefono: str, tipo_consulta: TipoConsulta, mensaje: str, source: str, handoff_contexto: str = "") -> str:
        conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta)
        try:
            metrics_service.on_intent(tipo_consulta.value)
        except Exception:
            pass

        if tipo_consulta == TipoConsulta.URGENCIA:
            contexto = handoff_contexto or mensaje.strip() or "Urgencia"
            ChatbotRules._activar_handoff(numero_telefono, contexto)
            return "Detectamos una urgencia. Te conecto con un agente ahora mismo. 🚨"

        if tipo_consulta == TipoConsulta.PRESUPUESTO:
            return ChatbotRules._start_presupuesto_menu(numero_telefono)

        conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)

        if source == "nlu" and tipo_consulta != TipoConsulta.OTRAS:
            return (
                f"¡Listo! 📝 Entendí que necesitás {ChatbotRules._get_texto_tipo_consulta(tipo_consulta)}.\n\n"
                f"{ChatbotRules.get_mensaje_inicio_secuencial(tipo_consulta)}"
            )

        return ChatbotRules.get_mensaje_inicio_secuencial(tipo_consulta)

    @staticmethod
    def _aplicar_opcion_menu(numero_telefono: str, opcion: dict, mensaje: str, source: str) -> str:
        handoff_contexto = ""
        if source == "button":
            handoff_contexto = opcion.get("text", "") or opcion.get("id", "")
        return ChatbotRules._aplicar_tipo_consulta(
            numero_telefono,
            opcion["tipo"],
            mensaje,
            source,
            handoff_contexto=handoff_contexto,
        )
    
    @staticmethod
    def get_mensaje_inicial() -> str:
        return (
            "¡Hola! 👋 Mi nombre es Eva, soy la asistente virtual de Argenfuego."
            + ChatbotRules._build_menu_prompt()
        )
    
    @staticmethod
    def get_mensaje_inicial_personalizado(nombre_usuario: str = "") -> str:
        """
        Genera saludo personalizado estático con nombre si está disponible
        """
        # Saludo personalizado simple sin OpenAI
        if nombre_usuario:
            saludo = f"¡Hola {nombre_usuario}! 👋🏻 Mi nombre es Eva 👩🏻‍🦱, soy la asistente virtual de Argenfuego."
        else:
            saludo = "¡Hola! 👋🏻 Mi nombre es Eva 👩🏻‍🦱, soy la asistente virtual de Argenfuego."

        return saludo + ChatbotRules._build_menu_prompt()
    
    @staticmethod
    def send_menu_interactivo(numero_telefono: str, nombre_usuario: str = ""):
        """
        Envía el menú principal con botones interactivos reales
        """
        from services.meta_whatsapp_service import meta_whatsapp_service
        import logging

        logger = logging.getLogger(__name__)

        mensaje_menu = "¿En qué puedo ayudarte hoy?"
        buttons = [
            {"id": option["id"], "title": option["title"]}
            for option in ChatbotRules.MENU_OPTIONS
        ]

        footer_text = "Seleccioná una opción para continuar"

        success = meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text=mensaje_menu,
            buttons=buttons,
            footer_text=footer_text
        )

        if success:
            logger.info(f"✅ Menú interactivo enviado a {numero_telefono}")
            return True

        logger.error(f"❌ Error enviando menú interactivo a {numero_telefono}")
        return False

    @staticmethod
    def _build_single_section(title: str, rows: tuple) -> list:
        return [{
            "title": title,
            "rows": [{"id": row["id"], "title": row["title"][:24]} for row in rows],
        }]

    @staticmethod
    def send_presupuesto_menu(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text="Seleccioná qué tipo de presupuesto necesitás:",
            buttons=list(ChatbotRules.PRESUPUESTO_MENU_ROWS),
            footer_text="Ingresá 'hola' para volver a empezar.",
        )

    @staticmethod
    def send_extintor_menu(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_list(
            numero_telefono,
            body_text="Seleccioná el tipo de matafuego/extintor.",
            button_text="Ver tipos",
            sections=ChatbotRules._build_single_section("Extintores", ChatbotRules.EXTINTOR_PRODUCT_ROWS),
            footer_text="Elegí una opción para continuar",
        )

    @staticmethod
    def send_presupuesto_contact_buttons(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text="¿Querés dejarnos tus datos para que te contactemos?",
            buttons=list(ChatbotRules.PRESUPUESTO_CONTACT_BUTTONS),
        )

    @staticmethod
    def send_presupuesto_servicio_buttons(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text="Dejanos tus datos y nos comunicamos con vos.",
            buttons=list(ChatbotRules.PRESUPUESTO_SERVICIO_BUTTONS),
        )

    @staticmethod
    def send_presupuesto_cantidad_menu(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text="¿Cuántos equipos necesitás?",
            buttons=list(ChatbotRules.PRESUPUESTO_CANTIDAD_ROWS),
        )

    @staticmethod
    def send_ifci_nivel_menu(numero_telefono: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_list(
            numero_telefono,
            body_text="Ahora te voy a hacer unas preguntas para poder darte una atención más personalizada al comunicarme con vos.",
            button_text="Ver niveles",
            sections=ChatbotRules._build_single_section("Nivel de instalación", ChatbotRules.IFCI_NIVEL_ROWS),
            footer_text="¿Cuál es el nivel de la instalación?",
        )

    @staticmethod
    def send_ifci_binary_buttons(numero_telefono: str, body_text: str) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        return meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text=body_text,
            buttons=list(ChatbotRules.IFCI_BINARY_BUTTONS),
        )
    
    @staticmethod
    def send_handoff_buttons(numero_telefono: str):
        """
        Envía botones de navegación después del handoff
        """
        from services.meta_whatsapp_service import meta_whatsapp_service
        import logging
        logger = logging.getLogger(__name__)
        
        mensaje = (
            "Ya me contacté con el staff de Argenfuego; en breve uno de nuestros asesores se unirá a la charla. 🙌\n"
            "Por favor aguardá un momento."
        )
        
        # Enviar mensaje
        success = meta_whatsapp_service.send_text_message(numero_telefono, mensaje)
        
        if success:
            logger.info(f"✅ Botones de handoff enviados a {numero_telefono}")
        else:
            logger.error(f"❌ Error enviando botones de handoff a {numero_telefono}")
        
        return success
    
    @staticmethod
    def send_confirmation_buttons(numero_telefono: str, mensaje: str):
        """
        Envía botones de confirmación (Sí/No)
        """
        from services.meta_whatsapp_service import meta_whatsapp_service
        import logging
        logger = logging.getLogger(__name__)
        
        success = meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text=mensaje,
            buttons=[
                {"id": "si", "title": "Sí"},
                {"id": "no", "title": "No"},
            ],
        )
        
        if success:
            logger.info(f"✅ Botones de confirmación enviados a {numero_telefono}")
        else:
            logger.error(f"❌ Error enviando botones de confirmación a {numero_telefono}")
        
        return success
    
    @staticmethod
    def get_saludo_inicial(nombre_usuario: str = "") -> str:
        """
        Primera parte del saludo: solo el saludo y presentación de Eva
        """
        if nombre_usuario:
            return f"¡Hola {nombre_usuario}! 👋🏻 Mi nombre es *Eva*"
        else:
            return "¡Hola! 👋🏻 Mi nombre es *Eva*"
    
    @staticmethod
    def get_presentacion_empresa() -> str:
        """
        Segunda parte del saludo: presentación de la empresa y menú
        """
        from config.company_profiles import get_active_company_profile
        profile = get_active_company_profile()
        company_name = profile['name']

        return f"Soy la asistente virtual de {company_name}." + ChatbotRules._build_menu_prompt()
    
    @staticmethod
    def _enviar_flujo_saludo_completo(numero_telefono: str, nombre_usuario: str = "") -> str:
        """
        Envía el flujo completo de saludo en background: saludo → sticker → menú
        Retorna inmediatamente (vacío) para que el webhook responda rápido
        
        MEJORA DE LATENCIA:
        - Antes: Webhook bloqueado ~500ms esperando la API de WhatsApp
        - Ahora: Webhook responde en ~15ms, todo se envía en paralelo
        """
        import os
        from services.meta_whatsapp_service import meta_whatsapp_service
        from config.company_profiles import get_active_company_profile
        import threading
        import time
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Función que envía TODO secuencialmente en background
        def enviar_todo_secuencial():
            """
            Envía los 3 mensajes en orden garantizado:
            1. Saludo (inmediato)
            2. Sticker (0.3s después)
            3. Menú (1.5s después del sticker = 1.8s total)
            """
            try:
                # ===== MENSAJE 1: SALUDO =====
                if nombre_usuario:
                    saludo = f"¡Hola {nombre_usuario}! 👋🏻 Mi nombre es Eva"
                else:
                    saludo = "¡Hola! 👋🏻 Mi nombre es Eva"
                
                logger.info(f"⚡ [Background] Enviando saludo a {numero_telefono}")
                inicio = time.time()
                saludo_enviado = meta_whatsapp_service.send_text_message(numero_telefono, saludo)
                tiempo_saludo = (time.time() - inicio) * 1000
                logger.info(f"✅ Saludo enviado en {tiempo_saludo:.0f}ms: {saludo_enviado}")
                
                # ===== MENSAJE 2: STICKER =====
                
                logger.info(f"⚡ [Background] Enviando sticker a {numero_telefono}")
                inicio = time.time()
                profile = get_active_company_profile()
                company_name = profile['name'].lower()
                sticker_url = f"https://raw.githubusercontent.com/Csuarezgurruchaga/argenfuego-chatbot/main/assets/{company_name}.webp"
                sticker_media_id = os.getenv("WHATSAPP_STICKER_MEDIA_ID", "").strip()

                if sticker_media_id:
                    sticker_enviado = meta_whatsapp_service.send_sticker(
                        numero_telefono,
                        sticker_id=sticker_media_id,
                    )
                else:
                    sticker_enviado = meta_whatsapp_service.send_sticker(
                        numero_telefono,
                        sticker_url=sticker_url,
                    )
                tiempo_sticker = (time.time() - inicio) * 1000
                logger.info(f"✅ Sticker enviado en {tiempo_sticker:.0f}ms: {sticker_enviado}")
                
                # ===== MENSAJE 3: MENÚ =====
                
                logger.info(f"⚡ [Background] Enviando menú a {numero_telefono}")
                inicio = time.time()
                
                # Enviar menú con botones interactivos (siempre)
                success = ChatbotRules.send_menu_interactivo(numero_telefono, nombre_usuario)
                tipo_menu = "interactivo"
                
                tiempo_menu = (time.time() - inicio) * 1000
                logger.info(f"✅ Menú {tipo_menu} enviado en {tiempo_menu:.0f}ms: {success}")
                
            except Exception as e:
                logger.error(f"❌ Error en flujo de saludo para {numero_telefono}: {str(e)}")
                # Sin fallback a texto: el menú debe ser interactivo
        
        # Ejecutar todo en un único thread background
        thread = threading.Thread(target=enviar_todo_secuencial)
        thread.daemon = True
        thread.start()
        
        logger.info(f"🚀 Thread de saludo iniciado para {numero_telefono}, webhook continuará sin esperar")
        
        # Retornar vacío inmediatamente - el webhook responde en ~15ms
        return ""
    
    @staticmethod
    def get_mensaje_recoleccion_datos_simplificado(tipo_consulta: TipoConsulta) -> str:
        return """📧 Email
📍 Dirección
🕒 Horario de visita
📝 Qué necesitas

💡 Escribe "menú" si quieres volver al inicio."""

    @staticmethod
    def _reset_presupuesto_temp(numero_telefono: str, preserve_contact=False):
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        preserved = {}
        if preserve_contact:
            for key in ("descripcion", "email", "direccion", "horario_visita", "razon_social", "cuit"):
                if key in conversacion.datos_temporales:
                    preserved[key] = conversacion.datos_temporales[key]
        conversacion.datos_temporales = preserved

    @staticmethod
    def _get_company_address() -> str:
        profile = get_active_company_profile()
        return profile.get("address", "nuestra sucursal")

    @staticmethod
    def _get_extintor_info_message(producto: dict) -> str:
        return (
            f"Las recargas normalmente se realizan en el momento o en un plazo de {producto['plazo']}.\n"
            f"{producto['detalle_plazo']}\n\n"
            f"Podés encontrarnos en {ChatbotRules._get_company_address()}\n"
            f"Te esperamos! 🤗"
        )

    @staticmethod
    def _get_presupuesto_farewell_message() -> str:
        return (
            "¡Gracias por contactarte con Argenfuego! 😊\n"
            'Si necesitás algo más, escribí "hola" para comenzar de nuevo.'
        )

    @staticmethod
    def _get_presupuesto_legacy_opening() -> str:
        return ChatbotRules.get_mensaje_inicio_secuencial(TipoConsulta.PRESUPUESTO)

    @staticmethod
    def _start_presupuesto_menu(numero_telefono: str) -> str:
        ChatbotRules._reset_presupuesto_temp(numero_telefono)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_MENU)
        if ChatbotRules.send_presupuesto_menu(numero_telefono):
            return ""
        return (
            "Seleccioná qué tipo de presupuesto necesitás:\n"
            "🧯 Extintores\n"
            "💧 IFCI\n"
            "🧯+💧 Ambos\n\n"
            "Ingresá 'hola' para volver a empezar."
        )

    @staticmethod
    def _start_extintor_menu(numero_telefono: str) -> str:
        ChatbotRules._reset_presupuesto_temp(numero_telefono)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO)
        if ChatbotRules.send_extintor_menu(numero_telefono):
            return ""
        return (
            "Seleccioná el tipo de matafuego/extintor:\n"
            "Vehicular (1 kg)\n"
            "Extintor 5kg PQ (ABC)\n"
            "Extintor 10kg PQ (ABC)\n"
            "Extintor 5kg CO2 (BC)\n"
            "Otro"
        )

    @staticmethod
    def _start_presupuesto_legacy(numero_telefono: str, mensaje: str = "", source: str = "legacy") -> str:
        ChatbotRules._reset_presupuesto_temp(numero_telefono)
        if source in {"keyword", "nlu"} and mensaje and len(mensaje.strip()) > 15:
            conversation_manager.set_datos_temporales(numero_telefono, "_descripcion_inicial", mensaje.strip())
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
        return ChatbotRules._get_presupuesto_legacy_opening()

    @staticmethod
    def _start_ifci_flow(numero_telefono: str) -> str:
        ChatbotRules._reset_presupuesto_temp(numero_telefono)
        conversation_manager.set_datos_temporales(numero_telefono, "_ifci_flow", "1")
        conversation_manager.set_datos_temporales(numero_telefono, "descripcion", "Consulta IFCI (Hidrantes)")
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
        return ChatbotRules._get_pregunta_campo_secuencial("email", TipoConsulta.PRESUPUESTO)

    @staticmethod
    def _start_ifci_questions(numero_telefono: str) -> str:
        conversation_manager.set_datos_temporales(numero_telefono, "_ifci_questions_done", "")
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_NIVEL)
        if ChatbotRules.send_ifci_nivel_menu(numero_telefono):
            return ""
        return (
            "Ahora te voy a hacer unas preguntas para poder darte una atención más personalizada al comunicarme con vos.\n\n"
            "¿Cuál es el nivel de la instalación?\n"
            "1. Nivel 1: Cañería seca\n"
            "2. Nivel 2: Cañería humeda\n"
            "3. Nivel 3: Cañería humeda\n"
            "4. No sé"
        )

    @staticmethod
    def _build_presupuesto_description(numero_telefono: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        producto = conversacion.datos_temporales.get("_presupuesto_producto")
        servicio = conversacion.datos_temporales.get("_presupuesto_servicio")
        cantidad = conversacion.datos_temporales.get("_presupuesto_cantidad")
        if not producto or not servicio or not cantidad:
            return ""
        tipo_accion = "compra" if servicio == "compra" else "mantenimiento"
        return f"{tipo_accion} de {cantidad} extintores de {producto['capacidad']} {producto['tipo']}."

    @staticmethod
    def _build_ifci_description(numero_telefono: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        nivel = conversacion.datos_temporales.get("ifci_nivel", "No especificado")
        hidrantes = conversacion.datos_temporales.get("ifci_hidrantes", "No especificado")
        establecimiento = conversacion.datos_temporales.get("ifci_establecimiento", "No especificado")
        detectores = conversacion.datos_temporales.get("ifci_detectores", "No especificado")
        plano = conversacion.datos_temporales.get("ifci_plano", "No especificado")
        return (
            "Consulta IFCI (Hidrantes)\n"
            f"- Nivel de instalación: {nivel}\n"
            f"- Cantidad de hidrantes: {hidrantes}\n"
            f"- Pisos/subsuelo/estacionamiento: {establecimiento}\n"
            f"- Detectores de humo: {detectores}\n"
            f"- Plano de incendio: {plano}"
        )

    @staticmethod
    def _refresh_ifci_description(numero_telefono: str) -> tuple[bool, Optional[str]]:
        conversation_manager.set_datos_temporales(numero_telefono, "descripcion", ChatbotRules._build_ifci_description(numero_telefono))
        return conversation_manager.validar_y_guardar_datos(numero_telefono)

    @staticmethod
    def _get_ifci_confirmacion(numero_telefono: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        datos = conversacion.datos_contacto
        parts = ["📋 *Resumen de tu solicitud:*\n", "🧾 *Tipo de consulta:* Presupuesto IFCI"]
        if datos.email and datos.email != "no_proporcionado@ejemplo.com":
            parts.append(f"📧 *Email:* {datos.email}")
        if datos.direccion and datos.direccion != "No proporcionada":
            parts.append(f"📍 *Dirección:* {datos.direccion}")
        if datos.horario_visita and datos.horario_visita != "No especificado":
            parts.append(f"🕒 *Horario de visita:* {datos.horario_visita}")
        if getattr(datos, "razon_social", None):
            parts.append(f"🏢 *Razón social:* {datos.razon_social}")
        if getattr(datos, "cuit", None):
            parts.append(f"🧾 *CUIT:* {datos.cuit}")
        parts.extend(
            [
                f"📶 *Nivel de instalación:* {conversacion.datos_temporales.get('ifci_nivel', 'No especificado')}",
                f"🚰 *Cantidad de hidrantes:* {conversacion.datos_temporales.get('ifci_hidrantes', 'No especificado')}",
                f"🏢 *Pisos / subsuelo / estacionamiento:* {conversacion.datos_temporales.get('ifci_establecimiento', 'No especificado')}",
                f"📡 *Detectores de humo:* {conversacion.datos_temporales.get('ifci_detectores', 'No especificado')}",
                f"📐 *Plano de incendio:* {conversacion.datos_temporales.get('ifci_plano', 'No especificado')}",
                "",
                "¿Es correcta toda la información?",
            ]
        )
        return "\n".join(parts)

    @staticmethod
    def _get_ifci_correction_menu() -> str:
        return (
            "❌ Entendido, vamos a corregir la información.\n\n"
            "¿Qué querés modificar?\n"
            "1️⃣ Email\n"
            "2️⃣ Dirección\n"
            "3️⃣ Horario de visita\n"
            "4️⃣ Razón social\n"
            "5️⃣ CUIT\n"
            "6️⃣ Nivel de instalación\n"
            "7️⃣ Cantidad de hidrantes\n"
            "8️⃣ Pisos / subsuelo / estacionamiento\n"
            "9️⃣ Detectores de humo\n"
            "🔟 Plano de incendio\n"
            "1️⃣1️⃣ Todo\n\n"
            "Respondé con el número del campo que querés corregir."
        )

    @staticmethod
    def _send_text_and_followup(numero_telefono: str, message: str, followup_callable) -> bool:
        from services.meta_whatsapp_service import meta_whatsapp_service

        text_sent = meta_whatsapp_service.send_text_message(numero_telefono, message)
        followup_sent = followup_callable()
        return text_sent and followup_sent

    @staticmethod
    def _get_presupuesto_contact_prompt_fallback() -> str:
        return (
            "¿Querés dejarnos tus datos para que te contactemos?\n"
            "- Sí\n"
            "- No, muchas gracias\n"
            "- Volver al menú anterior"
        )

    @staticmethod
    def _get_presupuesto_service_prompt_fallback() -> str:
        return (
            "Dejanos tus datos y nos comunicamos con vos.\n"
            "1. Equipo nuevo\n"
            "2. Mantenimiento"
        )

    @staticmethod
    def _get_presupuesto_cantidad_prompt_fallback() -> str:
        return (
            "¿Cuántos equipos necesitás?\n"
            "1\n"
            "2\n"
            "Otra cantidad"
        )

    @staticmethod
    def _get_presupuesto_cantidad_manual_prompt() -> str:
        return "¿Cuántos equipos necesitás?"

    @staticmethod
    def _get_ifci_hidrantes_prompt() -> str:
        return (
            "¿Qué cantidad de hidrantes tiene? (incluyendo la toma de impulsión)\n"
            "(ejemplo: 20 o No sé)\n\n"
            "Podés escribir No sé o saltar para pasar a la siguiente pregunta."
        )

    @staticmethod
    def _get_ifci_establecimiento_prompt() -> str:
        return (
            "¿Qué cantidad de pisos tiene el establecimiento? ¿Tiene subsuelo? ¿Tiene estacionamiento?\n"
            "\nPodés escribir No sé o saltar para pasar a la siguiente pregunta."
        )

    @staticmethod
    def _get_ifci_detectores_prompt() -> str:
        return (
            "¿La instalación tiene detectores de humo?\n"
            "\nPodés escribir No sé o saltar para pasar a la siguiente pregunta."
        )

    @staticmethod
    def _get_ifci_plano_prompt() -> str:
        return (
            "¿Tenés el plano de incendio de la instalación?\n"
            "\nPodés escribir No sé o saltar para pasar a la siguiente pregunta."
        )

    @staticmethod
    def _normalize_ifci_free_text_answer(mensaje: str) -> Optional[str]:
        valor = mensaje.strip()
        if not valor:
            return None
        if ChatbotRules._matches_choice(valor, "saltar", "skip", "no", "no se", "no sé", "n/a", "na"):
            return "No sé"
        return valor

    @staticmethod
    def _parse_ifci_binary_answer(mensaje: str) -> Optional[str]:
        if ChatbotRules._matches_choice(mensaje, "ifci_si", "si", "sí", "yes"):
            return "Sí"
        if ChatbotRules._matches_choice(mensaje, "ifci_no", "no"):
            return "No"
        if ChatbotRules._matches_choice(mensaje, "ifci_no_se", "no se", "no sé", "saltar", "skip", "n/a", "na"):
            return "No sé"
        return None

    @staticmethod
    def _start_ifci_detectores(numero_telefono: str) -> str:
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_DETECTORES)
        if ChatbotRules.send_ifci_binary_buttons(numero_telefono, ChatbotRules._get_ifci_detectores_prompt()):
            return ""
        return (
            f"{ChatbotRules._get_ifci_detectores_prompt()}\n"
            "Sí / No / No sé"
        )

    @staticmethod
    def _start_ifci_plano(numero_telefono: str) -> str:
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_PLANO)
        if ChatbotRules.send_ifci_binary_buttons(numero_telefono, ChatbotRules._get_ifci_plano_prompt()):
            return ""
        return (
            f"{ChatbotRules._get_ifci_plano_prompt()}\n"
            "Sí / No / No sé"
        )

    @staticmethod
    def _finalize_ifci_confirmation(numero_telefono: str, prefix: str = "") -> str:
        valido, error = ChatbotRules._refresh_ifci_description(numero_telefono)
        if not valido:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
            return f"❌ Hay algunos errores en los datos:\n{error}"
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
        mensaje_confirmacion = ChatbotRules._get_ifci_confirmacion(numero_telefono)
        mensaje_final = f"{prefix}\n\n{mensaje_confirmacion}" if prefix else mensaje_confirmacion
        return ChatbotRules._send_confirmation_summary(numero_telefono, mensaje_final)

    @staticmethod
    def _finish_ifci_correction(numero_telefono: str, success_message: str = "✅ Campo actualizado correctamente.") -> str:
        conversation_manager.set_datos_temporales(numero_telefono, "_ifci_correction_field", None)
        return ChatbotRules._finalize_ifci_confirmation(numero_telefono, success_message)

    @staticmethod
    def _complete_presupuesto_extintor(numero_telefono: str, cantidad: str) -> str:
        conversation_manager.set_datos_temporales(numero_telefono, "_presupuesto_cantidad", cantidad)
        descripcion = ChatbotRules._build_presupuesto_description(numero_telefono)
        conversation_manager.set_datos_temporales(numero_telefono, "descripcion", descripcion)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
        return (
            f"✅ Perfecto. Voy anotando: {descripcion}\n"
            f"{ChatbotRules._get_pregunta_campo_secuencial('email', TipoConsulta.PRESUPUESTO)}"
        )
    
    @staticmethod
    def get_mensaje_inicio_secuencial(tipo_consulta: TipoConsulta) -> str:
        """Mensaje inicial para el flujo secuencial conversacional"""
        if tipo_consulta == TipoConsulta.OTRAS:
            return """Perfecto 👌🏻 Para poder ayudarte de la mejor manera, me gustaría conocer más detalles sobre tu consulta.

📝 Por favor, contános qué necesitas (ej: información sobre productos, horarios de atención, servicios, etc.)"""
        
        elif tipo_consulta == TipoConsulta.URGENCIA:
            return """Entiendo que tienes una urgencia 🚨 Para poder asistirte de inmediato, necesito conocer los detalles.

📝 Por favor, contános qué está sucediendo y cómo podemos ayudarte urgentemente."""
        
        elif tipo_consulta == TipoConsulta.PRESUPUESTO:
            return """Perfecto 👌🏻 Para poder preparar tu presupuesto de manera precisa, necesito conocer los detalles de lo que necesitas.

📝 Por favor, contános qué productos o servicios necesitas (ej: tipo y cantidad de extintores, mantenimiento anual, mantenimiento de instalaciones fijas contra incendios, instalaciones, etc.)"""
        
        # Fallback para otros tipos
        return """Perfecto 👌🏻 Para poder ayudarte de la mejor manera, necesito conocer más detalles.

📝 Por favor, contános qué necesitas."""
    
    @staticmethod
    def get_mensaje_recoleccion_datos(tipo_consulta: TipoConsulta) -> str:
        consulta_texto = {
            TipoConsulta.PRESUPUESTO: "un presupuesto",
            TipoConsulta.VISITA_TECNICA: "coordinar una visita técnica",
            TipoConsulta.URGENCIA: "atender tu urgencia",
            TipoConsulta.OTRAS: "resolver tu consulta"
        }
        
        return f"""Perfecto! Para poder ayudarte con {consulta_texto[tipo_consulta]}, necesito que me proporciones la siguiente información:

📧 *Email de contacto*
📍 *Dirección* 
🕒 *Horario en que se puede visitar el lugar*
📝 *Cuéntanos más sobre lo que necesitas*

Por favor envíame toda esta información en un solo mensaje para poder proceder.

_💡 También puedes escribir "menú" para volver al menú principal en cualquier momento._"""
    
    @staticmethod
    def get_mensaje_confirmacion(conversacion) -> str:
        datos = conversacion.datos_contacto
        tipo_texto = {
            TipoConsulta.PRESUPUESTO: "Presupuesto",
            TipoConsulta.VISITA_TECNICA: "Visita técnica",
            TipoConsulta.URGENCIA: "Urgencia",
            TipoConsulta.OTRAS: "Consulta general"
        }
        
        mensaje_confirmacion = f"""📋 *Resumen de tu solicitud:*

🏷️ *Tipo de consulta:* {tipo_texto[conversacion.tipo_consulta]}"""

        # Solo mostrar email si fue proporcionado (no es el valor por defecto)
        if datos.email and datos.email != "no_proporcionado@ejemplo.com":
            mensaje_confirmacion += f"""
📧 *Email:* {datos.email}"""

        # Para consultas que no sean OTRAS, mostrar campos adicionales solo si fueron proporcionados
        if conversacion.tipo_consulta != TipoConsulta.OTRAS:
            if datos.direccion and datos.direccion != "No proporcionada":
                mensaje_confirmacion += f"""
📍 *Dirección:* {datos.direccion}"""
            
            if datos.horario_visita and datos.horario_visita != "No especificado":
                mensaje_confirmacion += f"""
🕒 *Horario de visita:* {datos.horario_visita}"""
            
            if hasattr(datos, 'razon_social') and datos.razon_social:
                mensaje_confirmacion += f"""
🏢 *Razón social:* {datos.razon_social}"""
            
            if hasattr(datos, 'cuit') and datos.cuit:
                mensaje_confirmacion += f"""
🧾 *CUIT:* {datos.cuit}"""

        mensaje_confirmacion += f"""
📝 *Descripción:* {datos.descripcion}

¿Es correcta toda la información?"""

        return mensaje_confirmacion
    
    @staticmethod
    def send_confirmacion_interactiva(numero_telefono: str, conversacion) -> bool:
        """
        Envía mensaje de confirmación con botones interactivos
        """
        from services.meta_whatsapp_service import meta_whatsapp_service
        import logging
        logger = logging.getLogger(__name__)
        
        # Obtener mensaje de confirmación
        mensaje = ChatbotRules.get_mensaje_confirmacion(conversacion)
        
        # Enviar con botones
        success = ChatbotRules.send_confirmation_buttons(numero_telefono, mensaje)
        
        if success:
            logger.info(f"✅ Confirmación interactiva enviada a {numero_telefono}")
        else:
            logger.error(f"❌ Error enviando confirmación interactiva a {numero_telefono}")
        
        return success
    
    @staticmethod
    def _get_texto_tipo_consulta(tipo_consulta: TipoConsulta) -> str:
        textos = {
            TipoConsulta.PRESUPUESTO: "un presupuesto",
            TipoConsulta.VISITA_TECNICA: "coordinar una visita técnica", 
            TipoConsulta.URGENCIA: "atender una urgencia",
            TipoConsulta.OTRAS: "resolver una consulta"
        }
        return textos.get(tipo_consulta, "ayuda")
    
    @staticmethod
    def _get_pregunta_campo_individual(campo: str) -> str:
        preguntas = {
            'email': "📧 ¿Cuál es tu email de contacto?",
            'direccion': "📍 ¿Cuál es la dirección donde necesitas el servicio?(aclarar CABA o Provincia)",
            'horario_visita': "🕒 ¿Cuál es tu horario disponible para la visita? (ej: lunes a viernes 9-17h)",
            'descripcion': """📝 Por favor, describe tu necesidad para que podamos preparar un presupuesto preciso. Puedes incluir:
• Tipo de servicio (ej. mantenimiento anual, compra de equipo nuevo)
• Tipo de equipo (ej. polvo químico, CO2)
• Capacidad (ej. 5 kg, 10 kg)
• Cantidad (ej. 2 equipos)
""",
            'razon_social': "🏢 ¿Cuál es la razón social de la empresa? (si sos particular, escribí tu nombre y apellido)",
            'cuit': "🧾 ¿Podrías brindarme un CUIT? (empresa o personal, según corresponda)",
        }
        return preguntas.get(campo, "Por favor proporciona más información.")
    
    @staticmethod
    def _get_pregunta_campo_secuencial(campo: str, tipo_consulta: TipoConsulta = None) -> str:
        """Preguntas específicas para el flujo secuencial"""
        if campo == 'descripcion':
            if tipo_consulta == TipoConsulta.PRESUPUESTO:
                return """📝 Por favor, contános qué productos o servicios necesitas (ej: tipo y cantidad de extintores, mantenimiento anual, mantenimiento de instalaciones fijas contra incendios, instalaciones, etc.)"""
            elif tipo_consulta == TipoConsulta.URGENCIA:
                return """📝 Por favor, contános qué está sucediendo y cómo podemos ayudarte urgentemente."""
            elif tipo_consulta == TipoConsulta.OTRAS:
                return """📝 Por favor, contános qué necesitas (ej: información sobre productos, horarios de atención, servicios, etc.)"""
            else:
                return """📝 Por favor, contános qué necesitas."""
        
        # Preguntas para datos de contacto (opcionales)
        preguntas = {
            'email': "📧 ¿Cuál es tu email de contacto? (opcional, para poder ayudarte de manera más efectiva)\n\n💡 Puedes escribir 'saltar' si prefieres no proporcionarlo.",
            'direccion': "📍 ¿Cuál es la dirección donde necesitas el servicio? (opcional)",
            'horario_visita': "🕒 ¿En qué horario se puede visitar el lugar? (opcional)",
            'razon_social': "🏢 ¿Cuál es la razón social de la empresa? (si sos particular, escribí tu nombre y apellido) (opcional)",
            'cuit': "🧾 ¿Podrías brindarme un CUIT? (empresa o personal, según corresponda) (opcional)",
        }
        return preguntas.get(campo, "Por favor proporciona más información.")
    
    @staticmethod
    def _get_mensaje_confirmacion_campo(campo: str, valor: str) -> str:
        """Mensajes de confirmación para cada campo con emojis blancos"""
        confirmaciones = {
            'email': f"¡Gracias! 🙌🏻 Anoté tu email: {valor}",
            'direccion': f"Perfecto 👌🏻 Dirección guardada: {valor}.",
            'horario_visita': f"Genial 🙌🏻. Entonces el horario es: {valor}.",
            'descripcion': f"✅ Perfecto! Descripción guardada: {valor}",
            'razon_social': f"¡Gracias! 🙌🏻 Razón social: {valor}",
            'cuit': f"Perfecto 👌🏻 CUIT guardado: {valor}.",
        }
        return confirmaciones.get(campo, f"✅ {valor} guardado correctamente.")

    @staticmethod
    def _send_confirmation_summary(numero_telefono: str, mensaje: str) -> str:
        if ChatbotRules.send_confirmation_buttons(numero_telefono, mensaje):
            return ""
        return mensaje
    
    @staticmethod
    def _procesar_campo_secuencial(numero_telefono: str, mensaje: str) -> str:
        """Procesa un campo en el flujo secuencial conversacional"""
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        campo_actual = conversation_manager.get_campo_siguiente(numero_telefono)
        
        if not campo_actual:
            # Todos los campos están completos, proceder a confirmación
            valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
            
            if not valido:
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
                primer_campo = conversation_manager.get_campo_siguiente(numero_telefono)
                return f"❌ Hay algunos errores en los datos:\n{error}\n\n{ChatbotRules._get_pregunta_campo_secuencial(primer_campo, conversacion.tipo_consulta)}"

            if conversacion.datos_temporales.get("_ifci_flow") and not conversacion.datos_temporales.get("_ifci_questions_done"):
                return ChatbotRules._start_ifci_questions(numero_telefono)

            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            return ChatbotRules._send_confirmation_summary(
                numero_telefono,
                ChatbotRules.get_mensaje_confirmacion(conversacion),
            )
        
        # Verificar si el usuario quiere saltar el campo (solo para campos opcionales)
        if mensaje.strip().lower() in ['saltar', 'skip', 'no', 'n/a', 'na'] and campo_actual in ['email', 'direccion', 'horario_visita', 'razon_social', 'cuit']:
            # Marcar campo como saltado
            conversation_manager.marcar_campo_completado(numero_telefono, campo_actual, "")
            confirmacion = ""  # Sin mensaje de confirmación para campos saltados
        else:
            # Validar campo actual
            if not ChatbotRules._validar_campo_individual(campo_actual, mensaje.strip()):
                error_msg = ChatbotRules._get_error_campo_individual(campo_actual)
                return f"❌ {error_msg}\n{ChatbotRules._get_pregunta_campo_secuencial(campo_actual, conversacion.tipo_consulta)}"
            
            # Guardar campo válido
            conversation_manager.marcar_campo_completado(numero_telefono, campo_actual, mensaje.strip())
            confirmacion = ChatbotRules._get_mensaje_confirmacion_campo(campo_actual, mensaje.strip())
        
        # VALIDACIÓN GEOGRÁFICA para direcciones (solo si no se saltó el campo)
        if campo_actual == 'direccion' and mensaje.strip().lower() not in ['saltar', 'skip', 'no', 'n/a', 'na']:
            ubicacion = ChatbotRules._validar_ubicacion_geografica(mensaje.strip()) #todo revisar
            
            if ubicacion == 'UNCLEAR':
                # Necesita validación manual - guardar dirección pendiente
                conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', mensaje.strip())
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.VALIDANDO_UBICACION)
                
                confirmacion = ChatbotRules._get_mensaje_confirmacion_campo(campo_actual, mensaje.strip())
                return f"{confirmacion}\n{ChatbotRules._get_mensaje_seleccion_ubicacion()}"
        
        # La confirmación ya se generó arriba según si se saltó o se validó el campo
        
        # Verificar si es el último campo
        if conversation_manager.es_ultimo_campo(numero_telefono, campo_actual):
            # Si hay una descripción inicial pre-guardada y este es el campo descripción, 
            # usar esa en lugar de pedir al usuario que escriba otra
            conversacion_temp = conversation_manager.get_conversacion(numero_telefono)
            descripcion_inicial = conversacion_temp.datos_temporales.get('_descripcion_inicial')
            
            if campo_actual == 'descripcion' and descripcion_inicial:
                # Usar la descripción inicial en lugar de la del usuario
                conversation_manager.marcar_campo_completado(numero_telefono, 'descripcion', descripcion_inicial)
                # Limpiar descripción temporal
                conversation_manager.set_datos_temporales(numero_telefono, '_descripcion_inicial', None)
                confirmacion = ChatbotRules._get_mensaje_confirmacion_campo('descripcion', descripcion_inicial)
            
            # Proceder a confirmación final
            conversacion_actualizada = conversation_manager.get_conversacion(numero_telefono)
            valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
            
            if not valido:
                return f"❌ Hay algunos errores en los datos:\n{error}"

            if conversacion_actualizada.datos_temporales.get("_ifci_flow") and not conversacion_actualizada.datos_temporales.get("_ifci_questions_done"):
                from services.meta_whatsapp_service import meta_whatsapp_service

                siguiente_tramo = ChatbotRules._start_ifci_questions(numero_telefono)
                if siguiente_tramo:
                    return f"{confirmacion}\n\n{siguiente_tramo}" if confirmacion else siguiente_tramo
                if confirmacion:
                    meta_whatsapp_service.send_text_message(numero_telefono, confirmacion)
                return ""
            
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            mensaje_confirmacion = ChatbotRules.get_mensaje_confirmacion(conversacion_actualizada)
            mensaje_final = f"{confirmacion}\n\n{mensaje_confirmacion}" if confirmacion else mensaje_confirmacion
            return ChatbotRules._send_confirmation_summary(numero_telefono, mensaje_final)
        else:
            # Pedir siguiente campo
            siguiente_campo = conversation_manager.get_campo_siguiente(numero_telefono)
            siguiente_pregunta = ChatbotRules._get_pregunta_campo_secuencial(siguiente_campo, conversacion.tipo_consulta)
            return f"{confirmacion}\n{siguiente_pregunta}" if confirmacion else siguiente_pregunta
    
    @staticmethod
    def _procesar_campo_individual(numero_telefono: str, mensaje: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        campos_faltantes = conversacion.datos_temporales.get('_campos_faltantes', [])
        indice_actual = conversacion.datos_temporales.get('_campo_actual', 0)
        
        if indice_actual >= len(campos_faltantes):
            # Error, no deberíamos estar aquí
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
            return "🤖 Hubo un error. Escribe 'hola' para comenzar de nuevo."
        
        campo_actual = campos_faltantes[indice_actual]
        
        # Validar y guardar la respuesta
        if ChatbotRules._validar_campo_individual(campo_actual, mensaje.strip()):
            conversation_manager.set_datos_temporales(numero_telefono, campo_actual, mensaje.strip())
            
            # Avanzar al siguiente campo
            siguiente_indice = indice_actual + 1
            conversation_manager.set_datos_temporales(numero_telefono, '_campo_actual', siguiente_indice)
            
            if siguiente_indice >= len(campos_faltantes):
                # Ya tenemos todos los campos, proceder a validación final
                conversation_manager.set_datos_temporales(numero_telefono, '_campos_faltantes', None)
                conversation_manager.set_datos_temporales(numero_telefono, '_campo_actual', None)
                
                valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
                
                if not valido:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                    return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
                
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                return ChatbotRules._send_confirmation_summary(
                    numero_telefono,
                    ChatbotRules.get_mensaje_confirmacion(conversacion),
                )
            else:
                # Preguntar por el siguiente campo
                siguiente_campo = campos_faltantes[siguiente_indice]
                return f"✅ Perfecto!\n\n{ChatbotRules._get_pregunta_campo_individual(siguiente_campo)}"
        else:
            # Campo inválido, pedir de nuevo
            error_msg = ChatbotRules._get_error_campo_individual(campo_actual)
            return f"❌ {error_msg}\n\n{ChatbotRules._get_pregunta_campo_individual(campo_actual)}"
    
    @staticmethod
    def _validar_campo_individual(campo: str, valor: str) -> bool:
        if campo == 'email':
            import re
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            return bool(re.search(email_pattern, valor))
        elif campo == 'direccion':
            return len(valor) >= 5
        elif campo == 'horario_visita':
            return len(valor) >= 3
        elif campo == 'descripcion':
            return len(valor) >= 10
        elif campo == 'razon_social':
            return len(valor) >= 2  # Minimo 2 caracteres (ej: "SA")
        elif campo == 'cuit':
            import re
            cuit_clean = re.sub(r'[^0-9]', '', valor)
            return len(cuit_clean) == 11  # 11 digitos
        return False
    
    @staticmethod
    def _get_error_campo_individual(campo: str) -> str:
        errores = {
            'email': "El email no tiene un formato válido.",
            'direccion': "La dirección debe tener al menos 5 caracteres.",
            'horario_visita': "El horario debe tener al menos 3 caracteres.",
            'descripcion': "La descripción debe tener al menos 10 caracteres.",
            'razon_social': "La razón social debe tener al menos 2 caracteres.",
            'cuit': "El CUIT debe tener 11 dígitos (ej: 20-12345678-9)."
        }
        return errores.get(campo, "El formato no es válido.")
    
    @staticmethod
    def _validar_ubicacion_geografica(direccion: str) -> str:
        """
        Valida si una dirección especifica CABA o Provincia usando comparación de keywords
        Retorna: 'CABA', 'PROVINCIA', o 'UNCLEAR'
        """
        direccion_lower = direccion.lower()
        
        # Buscar keywords en la dirección
        try:
            for sinonimo in SINONIMOS_CABA:
                if sinonimo in direccion_lower:
                    return 'CABA'
            
            for sinonimo in SINONIMOS_PROVINCIA:
                if sinonimo in direccion_lower:
                    return 'PROVINCIA'
        except Exception:
            print('LOCATION ERROR: NO SE PUDO VALIDAR CON KEYWORDS SI ES CABA O PROVINCIA')
            return 'UNCLEAR'
            
        # Si no encuentra keywords, retornar UNCLEAR para que el usuario seleccione manualmente
        return 'UNCLEAR'
    
    @staticmethod
    def _get_mensaje_seleccion_ubicacion() -> str:
        return """📍 *¿Tu dirección es en...*
1️⃣ *CABA*
2️⃣ *Provincia de Buenos Aires*
"""
    
    @staticmethod
    def _procesar_seleccion_ubicacion(numero_telefono: str, mensaje: str) -> str:
        """
        Procesa la selección del usuario para CABA o Provincia
        Acepta números (1, 2) y texto (caba, provincia, capital federal, bs as, etc.)
        """
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        direccion_original = conversacion.datos_temporales.get('_direccion_pendiente', '')
        
        # Normalizar entrada del usuario (con acentos y mayúsculas)
        texto_normalizado = normalizar_texto(mensaje)
        
        # Verificar si es CABA (opción 1 o sinónimos normalizados)
        if texto_normalizado == '1' or texto_normalizado in SINONIMOS_CABA_NORM:
            # Actualizar la dirección con CABA
            direccion_final = f"{direccion_original}, CABA"
            conversation_manager.set_datos_temporales(numero_telefono, 'direccion', direccion_final)
            conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', None)
            
            # Continuar con el flujo normal
            return ChatbotRules._continuar_despues_validacion_ubicacion(numero_telefono)
            
        # Verificar si es Provincia (opción 2 o sinónimos normalizados)
        elif texto_normalizado == '2' or texto_normalizado in SINONIMOS_PROVINCIA_NORM:
            # Actualizar la dirección con Provincia
            direccion_final = f"{direccion_original}, Provincia de Buenos Aires"
            conversation_manager.set_datos_temporales(numero_telefono, 'direccion', direccion_final)
            conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', None)
            
            # Continuar con el flujo normal
            return ChatbotRules._continuar_despues_validacion_ubicacion(numero_telefono)
        else:
            return "❌ Por favor responde *1* para CABA, *2* para Provincia, o escribe el nombre de tu ubicación (ej: CABA, Provincia, Capital Federal, Buenos Aires)."
    
    @staticmethod
    def _continuar_despues_validacion_ubicacion(numero_telefono: str) -> str:
        """
        Continúa el flujo después de validar la ubicación geográfica
        """
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        # Verificar si estábamos en flujo de datos individuales
        campos_faltantes = conversacion.datos_temporales.get('_campos_faltantes', [])
        indice_actual = conversacion.datos_temporales.get('_campo_actual', 0)
        
        if campos_faltantes and indice_actual is not None:
            # Volver al flujo de preguntas individuales
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES)
            
            if indice_actual >= len(campos_faltantes):
                # Ya tenemos todos los campos, proceder a validación final
                valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
                
                if not valido:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                    return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
                
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                return ChatbotRules._send_confirmation_summary(
                    numero_telefono,
                    ChatbotRules.get_mensaje_confirmacion(conversacion),
                )
            else:
                # Continuar con el siguiente campo faltante
                siguiente_campo = campos_faltantes[indice_actual]
                return f"✅ Perfecto!\n\n{ChatbotRules._get_pregunta_campo_individual(siguiente_campo)}"
        else:
            # VERIFICAR SI ESTAMOS EN FLUJO SECUENCIAL
            if conversacion.estado_anterior == EstadoConversacion.RECOLECTANDO_SECUENCIAL or len([k for k in conversacion.datos_temporales.keys() if not k.startswith('_')]) <= 2:
                # Continuar flujo secuencial - pedir siguiente campo
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
                siguiente_campo = conversation_manager.get_campo_siguiente(numero_telefono)
                
                if siguiente_campo:
                    conversacion_actualizada = conversation_manager.get_conversacion(numero_telefono)
                    return ChatbotRules._get_pregunta_campo_secuencial(siguiente_campo, conversacion_actualizada.tipo_consulta)
                else:
                    # Todos los campos están completos
                    valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
                    
                    if not valido:
                        # Reportar validación final fallida como fricción
                        try:
                            error_reporter.capture_experience_issue(
                                ErrorTrigger.VALIDATION_REPEAT,
                                {
                                    "conversation_id": numero_telefono,
                                    "numero_telefono": numero_telefono,
                                    "estado_actual": conversacion.estado,
                                    "estado_anterior": conversacion.estado_anterior,
                                    "tipo_consulta": conversacion.tipo_consulta,
                                    "validation_info": {"error": error},
                                }
                            )
                        except Exception:
                            pass
                        return f"❌ Hay algunos errores en los datos:\n{error}"

                    if conversacion.datos_temporales.get("_ifci_flow") and not conversacion.datos_temporales.get("_ifci_questions_done"):
                        return ChatbotRules._start_ifci_questions(numero_telefono)

                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                    return ChatbotRules._send_confirmation_summary(
                        numero_telefono,
                        ChatbotRules.get_mensaje_confirmacion(conversacion),
                    )
            else:
                # Flujo normal, proceder a confirmación
                valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
                
                if not valido:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                    return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
                
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                return ChatbotRules._send_confirmation_summary(
                    numero_telefono,
                    ChatbotRules.get_mensaje_confirmacion(conversacion),
                )
    
    @staticmethod
    def _extraer_datos_con_llm(mensaje: str) -> dict:
        """
        Usa el servicio NLU para extraer datos cuando el parsing básico no es suficiente
        """
        try:
            from services.nlu_service import nlu_service
            return nlu_service.extraer_datos_estructurados(mensaje)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error en extracción LLM: {str(e)}")
            return {}
    
    @staticmethod
    def get_mensaje_final_exito() -> str:
        return """¡Perfecto! Tu solicitud ha sido enviada exitosamente 📤.

Nuestro staff la revisará y se pondrá en contacto con vos a la brevedad al e-mail proporcionado.

¡Gracias por confiar en nosotros!, estamos para ayudarte 🤝🏻

*Argenfuego SRL*.
"""
# _Para una nueva consulta, escribe "hola"._"""
    
    @staticmethod
    def get_mensaje_error_opcion() -> str:
        opciones = []
        for idx, option in enumerate(ChatbotRules.MENU_OPTIONS, start=1):
            opciones.append(f"• *{idx}* para {option['text']}")
        opciones_texto = "\n".join(opciones)
        return f"""❌ No entendí tu selección.

Por favor responde con:
{opciones_texto}

_💡 También puedes describir tu necesidad con tus propias palabras y yo intentaré entenderte._"""
    
    @staticmethod
    def get_mensaje_datos_incompletos() -> str:
        return """⚠️ Parece que falta información importante. 

Necesito que me envíes en un mensaje:
📧 Email de contacto
📍 Dirección completa
🕒 Horario de visita
📝 Descripción de lo que necesitas

Por favor envíame todos estos datos juntos."""
    
    @staticmethod
    def _get_mensaje_pregunta_campo_a_corregir() -> str:
        return """❌ Entendido que hay información incorrecta.

¿Qué campo deseas corregir?
1️⃣ Email
2️⃣ Dirección
3️⃣ Horario de visita
4️⃣ Descripción
5️⃣ Todo (reiniciar todos los datos)

Responde con el número del campo que deseas modificar."""
    
    @staticmethod
    def _procesar_correccion_campo(numero_telefono: str, mensaje: str) -> str:
        opciones_correccion = {
            '1': 'email',
            '2': 'direccion', 
            '3': 'horario_visita',
            '4': 'descripcion',
            '5': 'todo'
        }
        
        campo = opciones_correccion.get(mensaje)
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        if not campo:
            return "❌ No entendí tu selección. " + ChatbotRules._get_mensaje_pregunta_campo_a_corregir()
        
        if campo == 'todo':
            # Reiniciar todos los datos
            conversation_manager.clear_datos_temporales(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
            return f"✏️ Entendido. {ChatbotRules.get_mensaje_recoleccion_datos(conversacion.tipo_consulta)}"
        else:
            # Preparar para corregir solo un campo específico
            conversation_manager.set_datos_temporales(numero_telefono, '_campo_a_corregir', campo)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CORRIGIENDO_CAMPO)
            return f"✅ Perfecto. Por favor envía el nuevo valor para: {ChatbotRules._get_pregunta_campo_individual(campo)}"
        
    @staticmethod
    def _procesar_correccion_campo_especifico(numero_telefono: str, mensaje: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        campo = conversacion.datos_temporales.get('_campo_a_corregir')
        
        if not campo:
            # Error, volver al inicio
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return "🤖 Hubo un error. Escribe 'hola' para comenzar de nuevo."
        
        # Validar y actualizar el campo específico
        if ChatbotRules._validar_campo_individual(campo, mensaje.strip()):
            conversation_manager.set_datos_temporales(numero_telefono, campo, mensaje.strip())
            
            # Actualizar también el objeto datos_contacto para que se refleje en la confirmación
            valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
            
            if not valido:
                # Esto no debería pasar porque acabamos de validar el campo individualmente
                return f"❌ Error al actualizar: {error}"
            
            # Limpiar campo temporal y volver a confirmación
            conversation_manager.set_datos_temporales(numero_telefono, '_campo_a_corregir', None)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            
            # Obtener la conversación actualizada
            conversacion_actualizada = conversation_manager.get_conversacion(numero_telefono)
            return ChatbotRules._send_confirmation_summary(
                numero_telefono,
                f"✅ Campo actualizado correctamente.\n\n{ChatbotRules.get_mensaje_confirmacion(conversacion_actualizada)}",
            )
        else:
            # Campo inválido, pedir de nuevo
            error_msg = ChatbotRules._get_error_campo_individual(campo)
            return f"❌ {error_msg}\n\nPor favor envía un valor válido para: {ChatbotRules._get_pregunta_campo_individual(campo)}"

    @staticmethod
    def _procesar_presupuesto_menu(numero_telefono: str, mensaje: str) -> str:
        if ChatbotRules._detectar_volver_local(mensaje):
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            return ChatbotRules._manejar_menu_principal(numero_telefono, conversacion.nombre_usuario or "")

        row = ChatbotRules._find_row_by_id(ChatbotRules.PRESUPUESTO_MENU_ROWS, mensaje) or ChatbotRules._find_row_by_text(
            ChatbotRules.PRESUPUESTO_MENU_ROWS, mensaje
        )
        if not row:
            return (
                "No entendí esa opción.\n"
                "Elegí una de estas alternativas:\n"
                "🧯 Extintores\n"
                "💧 IFCI\n"
                "🧯+💧 Ambos\n\n"
                "Ingresá 'hola' para volver a empezar."
            )

        if row["id"] == "presupuesto_extintores":
            return ChatbotRules._start_extintor_menu(numero_telefono)

        if row["id"] == "presupuesto_ifci":
            return ChatbotRules._start_ifci_flow(numero_telefono)

        return ChatbotRules._start_presupuesto_legacy(numero_telefono)

    @staticmethod
    def _procesar_presupuesto_extintor_tipo(numero_telefono: str, mensaje: str) -> str:
        from services.meta_whatsapp_service import meta_whatsapp_service

        if ChatbotRules._detectar_volver_local(mensaje):
            return ChatbotRules._start_presupuesto_menu(numero_telefono)

        row = ChatbotRules._find_row_by_id(ChatbotRules.EXTINTOR_PRODUCT_ROWS, mensaje) or ChatbotRules._find_row_by_text(
            ChatbotRules.EXTINTOR_PRODUCT_ROWS, mensaje
        )
        if not row:
            return (
                "No entendí esa opción.\n"
                "Elegí un tipo de matafuego/extintor o escribí `Otro`."
            )

        if row["id"] == "extintor_otro":
            return ChatbotRules._start_presupuesto_legacy(numero_telefono)

        conversation_manager.set_datos_temporales(numero_telefono, "_presupuesto_producto", row)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_EXTINTOR_CONFIRMAR_CONTACTO)

        info_message = ChatbotRules._get_extintor_info_message(row)
        if meta_whatsapp_service.send_text_message(numero_telefono, info_message):
            if ChatbotRules.send_presupuesto_contact_buttons(numero_telefono):
                return ""
            meta_whatsapp_service.send_text_message(numero_telefono, ChatbotRules._get_presupuesto_contact_prompt_fallback())
            return ""

        return f"{info_message}\n\n{ChatbotRules._get_presupuesto_contact_prompt_fallback()}"

    @staticmethod
    def _procesar_presupuesto_contacto(numero_telefono: str, mensaje: str) -> str:
        if ChatbotRules._matches_choice(mensaje, "presupuesto_contacto_back") or ChatbotRules._detectar_volver_local(mensaje):
            return ChatbotRules._start_extintor_menu(numero_telefono)

        if ChatbotRules._matches_choice(
            mensaje,
            "presupuesto_contacto_no",
            "no",
            "no muchas gracias",
            "no, muchas gracias",
            "no gracias",
            "no, gracias",
        ):
            conversation_manager.finalizar_conversacion(numero_telefono)
            return ChatbotRules._get_presupuesto_farewell_message()

        if ChatbotRules._matches_choice(mensaje, "presupuesto_contacto_si", "si", "sí"):
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_EXTINTOR_SERVICIO)
            if ChatbotRules.send_presupuesto_servicio_buttons(numero_telefono):
                return ""
            return ChatbotRules._get_presupuesto_service_prompt_fallback()

        return (
            "Por favor elegí una opción válida:\n"
            "- Sí\n"
            "- No, muchas gracias\n"
            "- Volver al menú anterior"
        )

    @staticmethod
    def _procesar_presupuesto_servicio(numero_telefono: str, mensaje: str) -> str:
        if ChatbotRules._matches_choice(
            mensaje,
            "presupuesto_compra",
            "1",
            "compra",
            "compra nuevo",
            "compra de equipo nuevo",
            "equipo nuevo",
        ):
            conversation_manager.set_datos_temporales(numero_telefono, "_presupuesto_servicio", "compra")
        elif ChatbotRules._matches_choice(mensaje, "presupuesto_mantenimiento", "2", "mantenimiento"):
            conversation_manager.set_datos_temporales(numero_telefono, "_presupuesto_servicio", "mantenimiento")
        else:
            return (
                "Por favor elegí una opción válida:\n"
                "1. Equipo nuevo\n"
                "2. Mantenimiento"
            )

        conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD)
        if ChatbotRules.send_presupuesto_cantidad_menu(numero_telefono):
            return ""
        return ChatbotRules._get_presupuesto_cantidad_prompt_fallback()

    @staticmethod
    def _procesar_presupuesto_cantidad(numero_telefono: str, mensaje: str) -> str:
        row = ChatbotRules._find_row_by_id(ChatbotRules.PRESUPUESTO_CANTIDAD_ROWS, mensaje) or ChatbotRules._find_row_by_text(
            ChatbotRules.PRESUPUESTO_CANTIDAD_ROWS, mensaje
        )
        if not row:
            return (
                "Por favor elegí una opción válida:\n"
                "1\n"
                "2\n"
                "Otra cantidad"
            )

        if row["id"] == "cantidad_otra":
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD_MANUAL)
            return ChatbotRules._get_presupuesto_cantidad_manual_prompt()

        return ChatbotRules._complete_presupuesto_extintor(numero_telefono, row["title"])

    @staticmethod
    def _procesar_presupuesto_cantidad_manual(numero_telefono: str, mensaje: str) -> str:
        cantidad = mensaje.strip()
        if not re.fullmatch(r"\d+", cantidad):
            return "Ingresá un número mayor o igual a 3."

        cantidad_int = int(cantidad)
        if cantidad_int < 3 or cantidad_int > 99:
            return "Ingresá un número mayor o igual a 3."

        return ChatbotRules._complete_presupuesto_extintor(numero_telefono, str(cantidad_int))

    @staticmethod
    def _procesar_ifci_nivel(numero_telefono: str, mensaje: str) -> str:
        row = ChatbotRules._find_row_by_id(ChatbotRules.IFCI_NIVEL_ROWS, mensaje) or ChatbotRules._find_row_by_text(
            ChatbotRules.IFCI_NIVEL_ROWS, mensaje
        )
        if not row:
            return (
                "Por favor elegí una opción válida para el nivel de instalación.\n"
                "Nivel 1: Cañería seca\n"
                "Nivel 2: Cañería humeda\n"
                "Nivel 3: Cañería humeda\n"
                "No sé"
            )

        conversation_manager.set_datos_temporales(numero_telefono, "ifci_nivel", row.get("value", row["title"]))

        if conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field") == "ifci_nivel":
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_HIDRANTES)
        return ChatbotRules._get_ifci_hidrantes_prompt()

    @staticmethod
    def _procesar_ifci_hidrantes(numero_telefono: str, mensaje: str) -> str:
        valor = ChatbotRules._normalize_ifci_free_text_answer(mensaje)
        if not valor:
            return ChatbotRules._get_ifci_hidrantes_prompt()

        conversation_manager.set_datos_temporales(numero_telefono, "ifci_hidrantes", valor)

        if conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field") == "ifci_hidrantes":
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_ESTABLECIMIENTO)
        return ChatbotRules._get_ifci_establecimiento_prompt()

    @staticmethod
    def _procesar_ifci_establecimiento(numero_telefono: str, mensaje: str) -> str:
        valor = ChatbotRules._normalize_ifci_free_text_answer(mensaje)
        if not valor:
            return ChatbotRules._get_ifci_establecimiento_prompt()

        conversation_manager.set_datos_temporales(numero_telefono, "ifci_establecimiento", valor)

        if conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field") == "ifci_establecimiento":
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        return ChatbotRules._start_ifci_detectores(numero_telefono)

    @staticmethod
    def _procesar_ifci_detectores(numero_telefono: str, mensaje: str) -> str:
        valor = ChatbotRules._parse_ifci_binary_answer(mensaje)
        if not valor:
            return (
                "Por favor elegí una opción válida:\n"
                "Sí / No / No sé"
            )

        conversation_manager.set_datos_temporales(numero_telefono, "ifci_detectores", valor)

        if conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field") == "ifci_detectores":
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        return ChatbotRules._start_ifci_plano(numero_telefono)

    @staticmethod
    def _procesar_ifci_plano(numero_telefono: str, mensaje: str) -> str:
        valor = ChatbotRules._parse_ifci_binary_answer(mensaje)
        if not valor:
            return (
                "Por favor elegí una opción válida:\n"
                "Sí / No / No sé"
            )

        conversation_manager.set_datos_temporales(numero_telefono, "ifci_plano", valor)

        if conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field") == "ifci_plano":
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        conversation_manager.set_datos_temporales(numero_telefono, "_ifci_questions_done", "1")
        return ChatbotRules._finalize_ifci_confirmation(numero_telefono)

    @staticmethod
    def _procesar_ifci_correccion(numero_telefono: str, mensaje: str) -> str:
        opcion = ChatbotRules.IFCI_CORRECTION_OPTIONS.get(mensaje.strip())
        if not opcion:
            return ChatbotRules._get_ifci_correction_menu()

        if opcion == "todo":
            return ChatbotRules._start_ifci_flow(numero_telefono)

        conversation_manager.set_datos_temporales(numero_telefono, "_ifci_correction_field", opcion)

        if opcion in {"email", "direccion", "horario_visita", "razon_social", "cuit"}:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_CORRIGIENDO_CAMPO)
            return ChatbotRules._get_pregunta_campo_secuencial(opcion, TipoConsulta.PRESUPUESTO)

        if opcion == "ifci_nivel":
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_NIVEL)
            if ChatbotRules.send_ifci_nivel_menu(numero_telefono):
                return ""
            return (
                "¿Cuál es el nivel de la instalación?\n"
                "Nivel 1: Cañería seca\n"
                "Nivel 2: Cañería humeda\n"
                "Nivel 3: Cañería humeda\n"
                "No sé"
            )

        if opcion == "ifci_hidrantes":
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_CORRIGIENDO_CAMPO)
            return ChatbotRules._get_ifci_hidrantes_prompt()

        if opcion == "ifci_establecimiento":
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_CORRIGIENDO_CAMPO)
            return ChatbotRules._get_ifci_establecimiento_prompt()

        if opcion == "ifci_detectores":
            return ChatbotRules._start_ifci_detectores(numero_telefono)

        if opcion == "ifci_plano":
            return ChatbotRules._start_ifci_plano(numero_telefono)

        return ChatbotRules._get_ifci_correction_menu()

    @staticmethod
    def _procesar_ifci_correccion_campo(numero_telefono: str, mensaje: str) -> str:
        campo = conversation_manager.get_datos_temporales(numero_telefono, "_ifci_correction_field")
        if not campo:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            return ChatbotRules._send_confirmation_summary(
                numero_telefono,
                ChatbotRules._get_ifci_confirmacion(numero_telefono),
            )

        if campo in {"ifci_hidrantes", "ifci_establecimiento"}:
            valor = ChatbotRules._normalize_ifci_free_text_answer(mensaje)
            if not valor:
                if campo == "ifci_hidrantes":
                    return ChatbotRules._get_ifci_hidrantes_prompt()
                return ChatbotRules._get_ifci_establecimiento_prompt()
            conversation_manager.set_datos_temporales(numero_telefono, campo, valor)
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        mensaje_limpio = mensaje.strip()
        if mensaje_limpio.lower() in ['saltar', 'skip', 'no', 'n/a', 'na'] and campo in ['email', 'direccion', 'horario_visita', 'razon_social', 'cuit']:
            conversation_manager.set_datos_temporales(numero_telefono, campo, "")
            return ChatbotRules._finish_ifci_correction(numero_telefono)

        if not ChatbotRules._validar_campo_individual(campo, mensaje_limpio):
            return (
                f"❌ {ChatbotRules._get_error_campo_individual(campo)}\n"
                f"{ChatbotRules._get_pregunta_campo_secuencial(campo, TipoConsulta.PRESUPUESTO)}"
            )

        conversation_manager.set_datos_temporales(numero_telefono, campo, mensaje_limpio)
        return ChatbotRules._finish_ifci_correction(numero_telefono)
    
    @staticmethod
    def procesar_mensaje(numero_telefono: str, mensaje: str, nombre_usuario: str = "") -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        # Guardar nombre de usuario si es la primera vez que lo vemos
        if nombre_usuario and not conversacion.nombre_usuario:
            conversation_manager.set_nombre_usuario(numero_telefono, nombre_usuario)

        mensaje_limpio = mensaje.strip().lower()

        if mensaje_limpio in ['hola', 'hi', 'hello', 'inicio', 'empezar']:
            conversation_manager.reset_conversacion(numero_telefono)
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            
            # Guardar nombre de usuario en la nueva conversación
            if nombre_usuario:
                conversation_manager.set_nombre_usuario(numero_telefono, nombre_usuario)
            
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            
            # Ejecutar metrics en background para no bloquear
            try:
                import threading
                threading.Thread(target=lambda: metrics_service.on_conversation_started(), daemon=True).start()
            except Exception:
                pass
            
            # Enviar flujo de 3 mensajes: saludo + imagen + presentación (todo en background)
            return ChatbotRules._enviar_flujo_saludo_completo(numero_telefono, nombre_usuario)
        
        # INTERCEPTAR CONSULTAS DE CONTACTO EN CUALQUIER MOMENTO (Contextual Intent Interruption)
        from services.nlu_service import nlu_service
        if nlu_service.detectar_consulta_contacto(mensaje):
            respuesta_contacto = nlu_service.generar_respuesta_contacto(mensaje)
            
            # Si estamos en un flujo activo, agregar mensaje para continuar
            if conversacion.estado not in [EstadoConversacion.INICIO, EstadoConversacion.ESPERANDO_OPCION]:
                respuesta_contacto += "\n\n💬 *Ahora sigamos con tu consulta anterior...*"
            
            return respuesta_contacto
        
        # INTERCEPTAR SOLICITUD DE HABLAR CON HUMANO EN CUALQUIER MOMENTO -> activar handoff
        if nlu_service.detectar_solicitud_humano(mensaje):
            ChatbotRules._activar_handoff(numero_telefono, mensaje)

            # Enviar mensaje de handoff con botones interactivos
            try:
                success = ChatbotRules.send_handoff_buttons(numero_telefono)
                if success:
                    return ""  # Los botones se enviaron exitosamente
                else:
                    # Fallback a mensaje de texto normal
                    profile = get_active_company_profile()
                    fuera_horario = ChatbotRules._esta_fuera_de_horario(profile.get('hours', ''))
                    base = (
                        "Ya me contacté con el staff de Argenfuego; en breve uno de nuestros asesores se unirá a la charla. 🙌\n"
                        "Por favor aguardá un momento."
                    )
                    if fuera_horario:
                        base += "\n\n🕒 En este momento estamos fuera de horario. Tomaremos tu caso y te responderemos a la brevedad."
                    return base
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error enviando botones de handoff: {str(e)}")
                # Fallback a mensaje de texto normal
                profile = get_active_company_profile()
                fuera_horario = ChatbotRules._esta_fuera_de_horario(profile.get('hours', ''))
                base = (
                    "Ya me contacté con el staff de Argenfuego; en breve uno de nuestros asesores se unirá a la charla. 🙌\n"
                    "Por favor aguardá un momento."
                )
                if fuera_horario:
                    base += "\n\n🕒 En este momento estamos fuera de horario. Tomaremos tu caso y te responderemos a la brevedad."
                return base
        
        # INTERCEPTAR SOLICITUDES DE VOLVER AL MENÚ EN CUALQUIER MOMENTO
        local_back_states = {
            EstadoConversacion.PRESUPUESTO_MENU,
            EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO,
            EstadoConversacion.PRESUPUESTO_EXTINTOR_CONFIRMAR_CONTACTO,
        }
        if (
            ChatbotRules._detectar_volver_menu(mensaje)
            and conversacion.estado not in [EstadoConversacion.INICIO, EstadoConversacion.ESPERANDO_OPCION]
            and conversacion.estado not in local_back_states
        ):
            return ChatbotRules._manejar_menu_principal(numero_telefono, conversacion.nombre_usuario or "")
        
        if conversacion.estado == EstadoConversacion.INICIO:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules._enviar_flujo_saludo_completo(numero_telefono, conversacion.nombre_usuario or nombre_usuario)
        
        elif conversacion.estado == EstadoConversacion.ESPERANDO_OPCION:
            return ChatbotRules._procesar_seleccion_opcion(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_MENU:
            return ChatbotRules._procesar_presupuesto_menu(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO:
            return ChatbotRules._procesar_presupuesto_extintor_tipo(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CONFIRMAR_CONTACTO:
            return ChatbotRules._procesar_presupuesto_contacto(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_SERVICIO:
            return ChatbotRules._procesar_presupuesto_servicio(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD:
            return ChatbotRules._procesar_presupuesto_cantidad(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD_MANUAL:
            return ChatbotRules._procesar_presupuesto_cantidad_manual(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS:
            return ChatbotRules._procesar_datos_contacto(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES:
            return ChatbotRules._procesar_campo_individual(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL:
            return ChatbotRules._procesar_campo_secuencial(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.VALIDANDO_UBICACION:
            return ChatbotRules._procesar_seleccion_ubicacion(numero_telefono, mensaje_limpio)

        elif conversacion.estado == EstadoConversacion.IFCI_NIVEL:
            return ChatbotRules._procesar_ifci_nivel(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.IFCI_HIDRANTES:
            return ChatbotRules._procesar_ifci_hidrantes(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.IFCI_ESTABLECIMIENTO:
            return ChatbotRules._procesar_ifci_establecimiento(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.IFCI_DETECTORES:
            return ChatbotRules._procesar_ifci_detectores(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.IFCI_PLANO:
            return ChatbotRules._procesar_ifci_plano(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.CONFIRMANDO:
            return ChatbotRules._procesar_confirmacion(numero_telefono, mensaje_limpio)

        elif conversacion.estado == EstadoConversacion.CORRIGIENDO:
            return ChatbotRules._procesar_correccion_campo(numero_telefono, mensaje_limpio)

        elif conversacion.estado == EstadoConversacion.CORRIGIENDO_CAMPO:
            return ChatbotRules._procesar_correccion_campo_especifico(numero_telefono, mensaje)

        elif conversacion.estado == EstadoConversacion.IFCI_CORRIGIENDO:
            return ChatbotRules._procesar_ifci_correccion(numero_telefono, mensaje_limpio)

        elif conversacion.estado == EstadoConversacion.IFCI_CORRIGIENDO_CAMPO:
            return ChatbotRules._procesar_ifci_correccion_campo(numero_telefono, mensaje)

        else:
            return "🤖 Hubo un error. Escribe 'hola' para comenzar de nuevo."

    @staticmethod
    def _esta_fuera_de_horario(hours_text: str) -> bool:
        """Heurística simple para fuera de horario. Si no se puede parsear, False.
        Aproximación AR (UTC-3): LV 8-17, S 9-13.
        """
        try:
            ahora = datetime.utcnow() - timedelta(hours=3)
            wd = ahora.weekday()  # 0 lunes
            h = ahora.hour
            if wd <= 4:
                return not (8 <= h < 17)
            if wd == 5:
                return not (9 <= h < 13)
            return True
        except Exception:
            return False
    
    @staticmethod
    def _procesar_seleccion_opcion(numero_telefono: str, mensaje: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        opcion, source = ChatbotRules._match_menu_option(mensaje)
        if opcion:
            return ChatbotRules._aplicar_opcion_menu(numero_telefono, opcion, mensaje, source)

        # Fallback: usar NLU para mapear mensaje a intención
        from services.nlu_service import nlu_service
        tipo_consulta_nlu = nlu_service.mapear_intencion(mensaje)

        if tipo_consulta_nlu:
            return ChatbotRules._aplicar_tipo_consulta(numero_telefono, tipo_consulta_nlu, mensaje, "nlu")

        # Reportar intención no clara (fricción NLU)
        try:
            error_reporter.capture_experience_issue(
                ErrorTrigger.NLU_UNCLEAR,
                {
                    "conversation_id": numero_telefono,
                    "numero_telefono": numero_telefono,
                    "estado_actual": conversacion.estado,
                    "estado_anterior": conversacion.estado_anterior,
                    "nlu_snapshot": {"input": mensaje},
                    "recommended_action": "Revisar patrones y prompt de clasificación",
                }
            )
        except Exception:
            pass
        try:
            metrics_service.on_nlu_unclear()
        except Exception:
            pass
        return ChatbotRules.get_mensaje_error_opcion()
    
    @staticmethod
    def _procesar_datos_contacto(numero_telefono: str, mensaje: str) -> str:
        # ENFOQUE LLM-FIRST: Usar OpenAI como parser primario
        datos_parseados = {}
        
        # Intentar extracción LLM primero (más potente para casos complejos)
        if len(mensaje) > 20:
            datos_llm = ChatbotRules._extraer_datos_con_llm(mensaje)
            if datos_llm:
                datos_parseados = datos_llm.copy()
        
        # Fallback: Si LLM no extrajo suficientes campos, usar parser básico
        campos_encontrados_llm = sum(1 for v in datos_parseados.values() if v and v != "")
        if campos_encontrados_llm < 2:
            datos_basicos = ChatbotRules._parsear_datos_contacto_basico(mensaje)
            # Combinar resultados, dando prioridad a LLM pero completando con parsing básico
            for key, value in datos_basicos.items():
                if value and not datos_parseados.get(key):
                    datos_parseados[key] = value
        
        # Limpiar el campo tipo_consulta que no necesitamos aquí
        if 'tipo_consulta' in datos_parseados:
            del datos_parseados['tipo_consulta']
        
        # Guardar los datos que sí se pudieron extraer
        campos_encontrados = []
        for key, value in datos_parseados.items():
            if value and value.strip():
                conversation_manager.set_datos_temporales(numero_telefono, key, value.strip())
                campos_encontrados.append(key)
        
        # VALIDACIÓN GEOGRÁFICA: Si tenemos dirección, validar ubicación
        if 'direccion' in campos_encontrados:
            direccion = datos_parseados['direccion']
            ubicacion = ChatbotRules._validar_ubicacion_geografica(direccion)
            
            if ubicacion == 'UNCLEAR':
                # Necesita validación manual - guardar dirección pendiente y cambiar estado
                conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', direccion)
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.VALIDANDO_UBICACION)
                
                # Mostrar campos encontrados y preguntar ubicación
                mensaje_encontrados = ""
                if len(campos_encontrados) > 1:  # Más campos además de dirección
                    nombres_campos = {
                        'email': '📧 Email',
                        'direccion': '📍 Dirección', 
                        'horario_visita': '🕒 Horario',
                        'descripcion': '📝 Descripción'
                    }
                    campos_texto = [nombres_campos[campo] for campo in campos_encontrados if campo != 'direccion']
                    if campos_texto:
                        mensaje_encontrados = "Ya tengo:\n"
                        for campo in campos_texto:
                            mensaje_encontrados += f"{campo} ✅\n"
                
                return mensaje_encontrados + f"📍 Dirección detectada: *{direccion}*\n\n" + ChatbotRules._get_mensaje_seleccion_ubicacion()
        
        # Determinar qué campos faltan
        campos_requeridos = ['email', 'direccion', 'horario_visita', 'descripcion']
        campos_faltantes = [campo for campo in campos_requeridos if not datos_parseados.get(campo) or not datos_parseados.get(campo).strip()]
        
        if not campos_faltantes:
            # Todos los campos están presentes, proceder con validación final
            valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
            
            if not valido:
                return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
            
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            return ChatbotRules._send_confirmation_summary(
                numero_telefono,
                ChatbotRules.get_mensaje_confirmacion(conversacion),
            )
        else:
            # Faltan campos, cambiar a modo de preguntas individuales
            conversation_manager.set_datos_temporales(numero_telefono, '_campos_faltantes', campos_faltantes)
            conversation_manager.set_datos_temporales(numero_telefono, '_campo_actual', 0)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES)
            
            # Mostrar qué se encontró y preguntar por el primer campo faltante
            mensaje_encontrados = ""
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            
            # Incluir campos pre-guardados en datos_temporales
            campos_temporales = conversacion.datos_temporales or {}
            todos_los_campos = set(campos_encontrados)
            for campo in ['email', 'direccion', 'horario_visita', 'descripcion']:
                if campos_temporales.get(campo):
                    todos_los_campos.add(campo)
            
            if todos_los_campos:
                nombres_campos = {
                    'email': '📧 Email',
                    'direccion': '📍 Dirección', 
                    'horario_visita': '🕒 Horario',
                    'descripcion': '📝 Descripción'
                }
                campos_texto = [nombres_campos[campo] for campo in todos_los_campos if campo in nombres_campos]
                mensaje_encontrados = "Ya tengo:\n"
                for campo in campos_texto:
                    mensaje_encontrados += f"{campo} ✅\n"
                mensaje_encontrados += "\n"
            
            return mensaje_encontrados + ChatbotRules._get_pregunta_campo_individual(campos_faltantes[0])
    
    @staticmethod
    def _procesar_confirmacion(numero_telefono: str, mensaje: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)

        if mensaje in ['si', 'sí', 'yes', 'confirmo', 'ok', 'correcto', '1', '1️⃣']:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ENVIANDO)
            return "⏳ Procesando tu solicitud..."
        elif mensaje in ['no', 'nope', 'incorrecto', 'error', '2', '2️⃣']:
            # Cambiar a estado de corrección y preguntar qué campo modificar
            if conversacion.datos_temporales.get("_ifci_flow"):
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.IFCI_CORRIGIENDO)
                return ChatbotRules._get_ifci_correction_menu()
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CORRIGIENDO)
            return ChatbotRules._get_mensaje_pregunta_campo_a_corregir()
        else:
            return "🤔 Por favor responde *SI* para confirmar o *NO* para corregir la información."
    
    @staticmethod
    def _parsear_datos_contacto_basico(mensaje: str) -> dict:
        import re
        
        # Buscar email con regex mejorado
        email_pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
        email_match = re.search(email_pattern, mensaje)
        email = email_match.group() if email_match else ""
        
        # Buscar CUIT (11 dígitos con o sin guiones)
        cuit_pattern = r"\b\d{2}-?\d{8}-?\d\b"
        cuit_match = re.search(cuit_pattern, mensaje)
        cuit = cuit_match.group() if cuit_match else ""
        
        # Dividir el mensaje en líneas para buscar patrones
        lineas = [linea.strip() for linea in mensaje.split('\n') if linea.strip()]
        
        direccion = ""
        horario = ""
        descripcion = ""
        razon_social = ""
        
        # Keywords mejoradas con scoring
        keywords_direccion = [
            'dirección', 'direccion', 'domicilio', 'ubicación', 'ubicacion', 
            'domicilio', 'ubicado', 'calle', 'avenida', 'av.', 'av ', 'barrio'
        ]
        keywords_horario = [
            'horario', 'hora', 'disponible', 'visita', 'lunes', 'martes', 
            'miércoles', 'miercoles', 'jueves', 'viernes', 'sabado', 'sábado', 'domingo', 'mañana', 
            'tarde', 'noche', 'am', 'pm'
        ]
        keywords_descripcion = [
            'necesito', 'descripción', 'descripcion', 'detalle', 'matafuego',
            'extintor', 'incendio', 'seguridad', 'oficina', 'empresa', 'local'
        ]
        
        # Buscar patrones con scoring
        for linea in lineas:
            linea_lower = linea.lower()
            
            # Saltar líneas que solo contienen email (ya lo tenemos)
            if email and linea.strip() == email:
                continue
            
            # Scoring para direccion
            score_direccion = sum(1 for kw in keywords_direccion if kw in linea_lower)
            # Scoring para horario
            score_horario = sum(1 for kw in keywords_horario if kw in linea_lower)
            # Scoring para descripcion
            score_descripcion = sum(1 for kw in keywords_descripcion if kw in linea_lower)
            
            # Determinar el valor extraído de la línea
            valor_extraido = linea.split(':', 1)[-1].strip() if ':' in linea else linea
            
            # Solo procesar si el valor no es el email ya encontrado
            if valor_extraido == email:
                continue
                
            # Asignar basado en scores
            if score_direccion > 0 and score_direccion >= score_horario and score_direccion >= score_descripcion and not direccion:
                direccion = valor_extraido
            elif score_horario > 0 and score_horario >= score_direccion and score_horario >= score_descripcion and not horario:
                horario = valor_extraido
            elif score_descripcion > 0 and score_descripcion >= score_direccion and score_descripcion >= score_horario and not descripcion:
                descripcion = valor_extraido
            elif len(linea) > 15 and score_direccion == score_horario == score_descripcion == 0:
                # Sin keywords específicas, clasificar por longitud y posición
                if not descripcion and any(word in linea_lower for word in ['necesito', 'quiero', 'para', 'equipar']):
                    descripcion = linea
                elif not direccion and len(linea) > 8:
                    direccion = linea
                elif not horario and len(linea) > 5:
                    horario = linea
        
        # Fallback: buscar por posición si no encontramos nada estructurado
        if not direccion and not horario and not descripcion and len(lineas) >= 3:
            mensaje_sin_email = mensaje
            if email:
                mensaje_sin_email = mensaje.replace(email, "").strip()
            
            partes = [parte.strip() for parte in mensaje_sin_email.split('\n') if parte.strip()]
            if len(partes) >= 3:
                direccion = partes[0] if not direccion else direccion
                horario = partes[1] if not horario else horario  
                descripcion = " ".join(partes[2:]) if not descripcion else descripcion
        
        # Validación mínima de longitud
        if len(direccion) < 5:
            direccion = ""
        if len(horario) < 3:
            horario = ""
        if len(descripcion) < 10:
            descripcion = ""
        if len(razon_social) < 2:
            razon_social = ""
        
        return {
            'email': email,
            'direccion': direccion,
            'horario_visita': horario,
            'descripcion': descripcion,
            'razon_social': razon_social,
            'cuit': cuit,
        }
