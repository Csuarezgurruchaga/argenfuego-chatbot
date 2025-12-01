import os
import unicodedata
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
    def get_mensaje_inicial() -> str:
        return """¡Hola! 👋 Mi nombre es Eva, soy la asistente virtual de Argenfuego.

¿En qué puedo ayudarte hoy? Por favor selecciona una opción:

1️⃣ Solicitar un presupuesto
2️⃣ Otras consultas

Responde con el número de la opción que necesitas 📱"""
    
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
        
        # Menú de opciones
        menu = """

¿En qué puedo ayudarte hoy? Por favor selecciona una opción:

1️⃣ Solicitar un presupuesto
2️⃣ Otras consultas

Responde con el número de la opción que necesitas 📱"""
        
        return saludo + menu
    
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
            {"id": "presupuesto", "title": "📋 Presupuesto"},
            {"id": "urgencia", "title": "🚨 Urgencia"},
            {"id": "otras", "title": "❓ Otras consultas"}
        ]

        header_text = f"¡Hola {nombre_usuario}!" if nombre_usuario else None
        footer_text = "Seleccioná una opción para continuar"

        success = meta_whatsapp_service.send_interactive_buttons(
            numero_telefono,
            body_text=mensaje_menu,
            buttons=buttons,
            header_text=header_text,
            footer_text=footer_text
        )

        if success:
            logger.info(f"✅ Menú interactivo enviado a {numero_telefono}")
            return True

        logger.error(f"❌ Error enviando menú interactivo a {numero_telefono}")
        mensaje_fallback = ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
        meta_whatsapp_service.send_text_message(numero_telefono, mensaje_fallback)
        return False
    
    @staticmethod
    def send_handoff_buttons(numero_telefono: str):
        """
        Envía botones de navegación después del handoff
        """
        from services.meta_whatsapp_service import meta_whatsapp_service
        import logging
        logger = logging.getLogger(__name__)
        
        mensaje = f"""Ya contacté al staff de Argenfuego; en breve uno de nuestros asesores se une a la charla. 🙌

Si preferís no esperar, podés usar estas opciones:
1️⃣ Volver al menú
✋ Finalizar chat

💡 *Responde con el número de la opción que necesitas*"""
        
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
        
        mensaje_completo = f"""{mensaje}

┌─────────────────────────────┐
│  ✅ 1. Sí, confirmar         │
│  ❌ 2. No, corregir          │
│  ⬅️ 3. Volver al menú        │
└─────────────────────────────┘

💡 *Responde con el número de la opción que necesitas*"""
        
        # Enviar mensaje
        success = meta_whatsapp_service.send_text_message(numero_telefono, mensaje_completo)
        
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
        
        return f"""Soy la asistente virtual de {company_name}.

¿En qué puedo ayudarte hoy? Por favor selecciona una opción:

1️⃣ Solicitar un presupuesto
2️⃣ Reportar una urgencia
3️⃣ Otras consultas

Responde con el número de la opción que necesitas 📱"""
    
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
        
        # Verificar si los botones interactivos están habilitados
        use_interactive_buttons = os.getenv("USE_INTERACTIVE_BUTTONS", "false").lower() == "true"
        
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
                # Delay de 0.3s para que el saludo llegue primero
                time.sleep(0.3)
                
                logger.info(f"⚡ [Background] Enviando sticker a {numero_telefono}")
                inicio = time.time()
                profile = get_active_company_profile()
                company_name = profile['name'].lower()
                sticker_url = f"https://raw.githubusercontent.com/Csuarezgurruchaga/argenfuego-chatbot/main/assets/{company_name}.webp"
                
                sticker_enviado = meta_whatsapp_service.send_sticker(numero_telefono, sticker_url)
                tiempo_sticker = (time.time() - inicio) * 1000
                logger.info(f"✅ Sticker enviado en {tiempo_sticker:.0f}ms: {sticker_enviado}")
                
                # ===== MENSAJE 3: MENÚ =====
                # Delay de 1.5s desde el sticker (total 1.8s desde inicio)
                time.sleep(1.5)
                
                logger.info(f"⚡ [Background] Enviando menú a {numero_telefono}")
                inicio = time.time()
                
                if use_interactive_buttons:
                    # Enviar menú con botones interactivos
                    success = ChatbotRules.send_menu_interactivo(numero_telefono, nombre_usuario)
                    tipo_menu = "interactivo"
                else:
                    # Enviar menú tradicional
                    mensaje_completo = ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
                    success = meta_whatsapp_service.send_text_message(numero_telefono, mensaje_completo)
                    tipo_menu = "tradicional"
                
                tiempo_menu = (time.time() - inicio) * 1000
                logger.info(f"✅ Menú {tipo_menu} enviado en {tiempo_menu:.0f}ms: {success}")
                
            except Exception as e:
                logger.error(f"❌ Error en flujo de saludo para {numero_telefono}: {str(e)}")
                # Fallback: intentar enviar al menos el mensaje completo
                try:
                    mensaje_completo = ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
                    meta_whatsapp_service.send_text_message(numero_telefono, mensaje_completo)
                except Exception as fallback_error:
                    logger.error(f"❌ Error en fallback: {fallback_error}")
        
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
"""
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
            'horario_visita': "🕒 ¿En qué horario se puede visitar el lugar? (opcional)"
        }
        return preguntas.get(campo, "Por favor proporciona más información.")
    
    @staticmethod
    def _get_mensaje_confirmacion_campo(campo: str, valor: str) -> str:
        """Mensajes de confirmación para cada campo con emojis blancos"""
        confirmaciones = {
            'email': f"¡Gracias! 🙌🏻 Anoté tu email: {valor}",
            'direccion': f"Perfecto 👌🏻 Dirección guardada: {valor}.",
            'horario_visita': f"Genial 🙌🏻. Entonces el horario es: {valor}.",
            'descripcion': f"✅ Perfecto! Descripción guardada: {valor}"
        }
        return confirmaciones.get(campo, f"✅ {valor} guardado correctamente.")
    
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
            
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            return ChatbotRules.get_mensaje_confirmacion(conversacion)
        
        # Verificar si el usuario quiere saltar el campo (solo para campos opcionales)
        if mensaje.strip().lower() in ['saltar', 'skip', 'no', 'n/a', 'na'] and campo_actual in ['email', 'direccion', 'horario_visita']:
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
            
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            return f"{confirmacion}\n\n{ChatbotRules.get_mensaje_confirmacion(conversacion_actualizada)}"
        else:
            # Pedir siguiente campo
            siguiente_campo = conversation_manager.get_campo_siguiente(numero_telefono)
            siguiente_pregunta = ChatbotRules._get_pregunta_campo_secuencial(siguiente_campo, conversacion.tipo_consulta)
            return f"{confirmacion}\n{siguiente_pregunta}"
    
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
                return ChatbotRules.get_mensaje_confirmacion(conversacion)
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
        return False
    
    @staticmethod
    def _get_error_campo_individual(campo: str) -> str:
        errores = {
            'email': "El email no tiene un formato válido.",
            'direccion': "La dirección debe tener al menos 5 caracteres.",
            'horario_visita': "El horario debe tener al menos 3 caracteres.",
            'descripcion': "La descripción debe tener al menos 10 caracteres."
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
                return ChatbotRules.get_mensaje_confirmacion(conversacion)
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
                    
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                    return ChatbotRules.get_mensaje_confirmacion(conversacion)
            else:
                # Flujo normal, proceder a confirmación
                valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
                
                if not valido:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                    return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
                
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
                return ChatbotRules.get_mensaje_confirmacion(conversacion)
    
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
        return """❌ No entendí tu selección. 

Por favor responde con:
• *1* para Solicitar un presupuesto
• *2* para Otras consultas
• *3* para Otras consultas

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
            return f"✅ Campo actualizado correctamente.\n\n{ChatbotRules.get_mensaje_confirmacion(conversacion_actualizada)}"
        else:
            # Campo inválido, pedir de nuevo
            error_msg = ChatbotRules._get_error_campo_individual(campo)
            return f"❌ {error_msg}\n\nPor favor envía un valor válido para: {ChatbotRules._get_pregunta_campo_individual(campo)}"
    
    @staticmethod
    def procesar_mensaje(numero_telefono: str, mensaje: str, nombre_usuario: str = "") -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        # Guardar nombre de usuario si es la primera vez que lo vemos
        if nombre_usuario and not conversacion.nombre_usuario:
            conversation_manager.set_nombre_usuario(numero_telefono, nombre_usuario)
        
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
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ATENDIDO_POR_HUMANO)
            conversacion.atendido_por_humano = True
            conversacion.handoff_started_at = datetime.utcnow()
            # Guardar el mensaje que disparó el handoff como contexto
            conversacion.mensaje_handoff_contexto = mensaje
            # Agregar a la cola de handoffs (la notificación se hace en main.py)
            conversation_manager.add_to_handoff_queue(numero_telefono)

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
                        "Ya contacté al staff de Argenfuego; en breve uno de nuestros asesores se une a la charla. 🙌\n"
                        "Si preferís no esperar, podés usar estas opciones:\n"
                        "1️⃣ Volver al menú\n"
                        "✋ Finalizar chat"
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
                    "Ya contacté al staff de Argenfuego; en breve uno de nuestros asesores se une a la charla. 🙌\n"
                    "Si preferís no esperar, podés usar estas opciones:\n"
                    "1️⃣ Volver al menú\n"
                    "✋ Finalizar chat"
                )
                if fuera_horario:
                    base += "\n\n🕒 En este momento estamos fuera de horario. Tomaremos tu caso y te responderemos a la brevedad."
                return base
        
        # INTERCEPTAR SOLICITUDES DE VOLVER AL MENÚ EN CUALQUIER MOMENTO
        if ChatbotRules._detectar_volver_menu(mensaje) and conversacion.estado not in [EstadoConversacion.INICIO, EstadoConversacion.ESPERANDO_OPCION]:
            # Limpiar datos temporales y volver al menú
            conversation_manager.clear_datos_temporales(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return "↩️ *Volviendo al menú principal...*\n\n" + ChatbotRules.get_mensaje_inicial_personalizado(conversacion.nombre_usuario)
        
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
        
        if conversacion.estado == EstadoConversacion.INICIO:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules._enviar_flujo_saludo_completo(numero_telefono, conversacion.nombre_usuario or nombre_usuario)
        
        elif conversacion.estado == EstadoConversacion.ESPERANDO_OPCION:
            return ChatbotRules._procesar_seleccion_opcion(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS:
            return ChatbotRules._procesar_datos_contacto(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES:
            return ChatbotRules._procesar_campo_individual(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL:
            return ChatbotRules._procesar_campo_secuencial(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.VALIDANDO_UBICACION:
            return ChatbotRules._procesar_seleccion_ubicacion(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.CONFIRMANDO:
            return ChatbotRules._procesar_confirmacion(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.CORRIGIENDO:
            return ChatbotRules._procesar_correccion_campo(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.CORRIGIENDO_CAMPO:
            return ChatbotRules._procesar_correccion_campo_especifico(numero_telefono, mensaje)
        
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
        opciones = {
            '1': TipoConsulta.PRESUPUESTO,
            '2': TipoConsulta.OTRAS,
            'presupuesto': TipoConsulta.PRESUPUESTO,
            'urgencia': TipoConsulta.URGENCIA,
            'otras': TipoConsulta.OTRAS,
            'visita': TipoConsulta.OTRAS,  # Visitas técnicas ahora van a OTRAS
            'consulta': TipoConsulta.OTRAS
        }
        
        tipo_consulta = opciones.get(mensaje)
        if tipo_consulta:
            conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta)
            try:
                metrics_service.on_intent(tipo_consulta.value)
            except Exception:
                pass
            
            # Si NLU detecta urgencia, iniciar handoff a humano
            if tipo_consulta == TipoConsulta.URGENCIA:
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.ATENDIDO_POR_HUMANO)
                conversacion = conversation_manager.get_conversacion(numero_telefono)
                conversacion.atendido_por_humano = True
                conversacion.handoff_started_at = __import__('datetime').datetime.utcnow()
                # Guardar el mensaje que disparó el handoff como contexto
                conversacion.mensaje_handoff_contexto = mensaje
                # Agregar a la cola de handoffs
                conversation_manager.add_to_handoff_queue(numero_telefono)
                return "Detectamos una urgencia. Te conecto con un agente ahora mismo. 🚨"
            
            # Para otras consultas, usar flujo secuencial conversacional
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
            return ChatbotRules.get_mensaje_inicio_secuencial(tipo_consulta)
        else:
            # Fallback: usar NLU para mapear mensaje a intención
            from services.nlu_service import nlu_service
            tipo_consulta_nlu = nlu_service.mapear_intencion(mensaje)
            
            if tipo_consulta_nlu:
                conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta_nlu)
                try:
                    metrics_service.on_intent(tipo_consulta_nlu.value)
                except Exception:
                    pass
                
                # Si NLU detecta urgencia, iniciar handoff a humano
                if tipo_consulta_nlu == TipoConsulta.URGENCIA:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.ATENDIDO_POR_HUMANO)
                    conversacion = conversation_manager.get_conversacion(numero_telefono)
                    conversacion.atendido_por_humano = True
                    conversacion.handoff_started_at = __import__('datetime').datetime.utcnow()
                    # Guardar el mensaje que disparó el handoff como contexto
                    conversacion.mensaje_handoff_contexto = mensaje
                    # Agregar a la cola de handoffs
                    conversation_manager.add_to_handoff_queue(numero_telefono)
                    return "Detectamos una urgencia. Te conecto con un agente ahora mismo. 🚨"
                
                # Para otras consultas, usar flujo secuencial conversacional
                # PRE-GUARDAR MENSAJE INICIAL COMO DESCRIPCIÓN si es sustancial
                if len(mensaje.strip()) > 15:
                    conversation_manager.set_datos_temporales(numero_telefono, '_descripcion_inicial', mensaje.strip())
                
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_SECUENCIAL)
                
                if tipo_consulta_nlu == TipoConsulta.OTRAS:
                    return ChatbotRules.get_mensaje_inicio_secuencial(tipo_consulta_nlu)
                else:
                    return f"¡Listo! 📝 Entendí que necesitás {ChatbotRules._get_texto_tipo_consulta(tipo_consulta_nlu)}.\n\n{ChatbotRules.get_mensaje_inicio_secuencial(tipo_consulta_nlu)}"
            else:
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
            return ChatbotRules.get_mensaje_confirmacion(conversacion)
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
        if mensaje in ['si', 'sí', 'yes', 'confirmo', 'ok', 'correcto']:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ENVIANDO)
            return "⏳ Procesando tu solicitud..."
        elif mensaje in ['no', 'nope', 'incorrecto', 'error']:
            # Cambiar a estado de corrección y preguntar qué campo modificar
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
        
        # Dividir el mensaje en líneas para buscar patrones
        lineas = [linea.strip() for linea in mensaje.split('\n') if linea.strip()]
        
        direccion = ""
        horario = ""
        descripcion = ""
        
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
        
        return {
            'email': email,
            'direccion': direccion,
            'horario_visita': horario,
            'descripcion': descripcion
        }
