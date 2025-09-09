from typing import Tuple
from .models import EstadoConversacion, TipoConsulta
from .states import conversation_manager

class ChatbotRules:
    
    @staticmethod
    def get_mensaje_inicial() -> str:
        return """¡Hola! 👋 Mi nombre es Eva, soy la asistente virtual de Argenfuego.

¿En qué puedo ayudarte hoy? Por favor selecciona una opción:

1️⃣ Solicitar un presupuesto
2️⃣ Coordinar una visita técnica para evaluar la dotación necesaria del lugar
3️⃣ Reportar una urgencia
4️⃣ Otras consultas

Responde con el número de la opción que necesitas 📱"""
    
    @staticmethod
    def get_mensaje_recoleccion_datos(tipo_consulta: TipoConsulta) -> str:
        consulta_texto = {
            TipoConsulta.PRESUPUESTO: "un presupuesto",
            TipoConsulta.VISITA_TECNICA: "coordinar una visita técnica",
            TipoConsulta.URGENCIA: "atender tu urgencia",
            TipoConsulta.OTRAS: "resolver tu consulta"
        }
        
        return f"""Perfecto! Para poder ayudarte con {consulta_texto[tipo_consulta]}, necesito que me proporciones la siguiente información:

📧 **Email de contacto**
📍 **Dirección** 
🕒 **Horario en que se puede visitar el lugar**
📝 **Cuéntanos más sobre lo que necesitas**

Por favor envíame toda esta información en un solo mensaje para poder proceder."""
    
    @staticmethod
    def get_mensaje_confirmacion(conversacion) -> str:
        datos = conversacion.datos_contacto
        tipo_texto = {
            TipoConsulta.PRESUPUESTO: "Presupuesto",
            TipoConsulta.VISITA_TECNICA: "Visita técnica",
            TipoConsulta.URGENCIA: "Urgencia",
            TipoConsulta.OTRAS: "Consulta general"
        }
        
        return f"""📋 **Resumen de tu solicitud:**

🏷️ **Tipo de consulta:** {tipo_texto[conversacion.tipo_consulta]}
📧 **Email:** {datos.email}
📍 **Dirección:** {datos.direccion}
🕒 **Horario de visita:** {datos.horario_visita}
📝 **Descripción:** {datos.descripcion}

¿Es correcta toda la información? 

✅ Responde **"SI"** para confirmar y enviar la solicitud
✏️ Responde **"NO"** si hay algo que corregir"""
    
    @staticmethod
    def get_mensaje_final_exito() -> str:
        return """✅ ¡Perfecto! Tu solicitud ha sido enviada exitosamente.

Nuestro equipo la revisará y se pondrá en contacto contigo a la brevedad en el email proporcionado.

¡Gracias por contactar a Argenfuego! 🔥

_Para una nueva consulta, puedes escribir "hola" en cualquier momento._"""
    
    @staticmethod
    def get_mensaje_error_opcion() -> str:
        return """❌ No entendí tu selección. 

Por favor responde con:
• **1** para Solicitar un presupuesto
• **2** para Visita técnica  
• **3** para Reportar urgencia
• **4** para Otras consultas"""
    
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
    def procesar_mensaje(numero_telefono: str, mensaje: str) -> str:
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        mensaje_limpio = mensaje.strip().lower()
        
        if mensaje_limpio in ['hola', 'hi', 'hello', 'inicio', 'empezar']:
            conversation_manager.reset_conversacion(numero_telefono)
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules.get_mensaje_inicial()
        
        if conversacion.estado == EstadoConversacion.INICIO:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules.get_mensaje_inicial()
        
        elif conversacion.estado == EstadoConversacion.ESPERANDO_OPCION:
            return ChatbotRules._procesar_seleccion_opcion(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS:
            return ChatbotRules._procesar_datos_contacto(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.CONFIRMANDO:
            return ChatbotRules._procesar_confirmacion(numero_telefono, mensaje_limpio)
        
        else:
            return "🤖 Hubo un error. Escribe 'hola' para comenzar de nuevo."
    
    @staticmethod
    def _procesar_seleccion_opcion(numero_telefono: str, mensaje: str) -> str:
        opciones = {
            '1': TipoConsulta.PRESUPUESTO,
            '2': TipoConsulta.VISITA_TECNICA,
            '3': TipoConsulta.URGENCIA,
            '4': TipoConsulta.OTRAS,
            'presupuesto': TipoConsulta.PRESUPUESTO,
            'visita': TipoConsulta.VISITA_TECNICA,
            'urgencia': TipoConsulta.URGENCIA,
            'otras': TipoConsulta.OTRAS
        }
        
        tipo_consulta = opciones.get(mensaje)
        if tipo_consulta:
            conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
            return ChatbotRules.get_mensaje_recoleccion_datos(tipo_consulta)
        else:
            return ChatbotRules.get_mensaje_error_opcion()
    
    @staticmethod
    def _procesar_datos_contacto(numero_telefono: str, mensaje: str) -> str:
        datos_parseados = ChatbotRules._parsear_datos_contacto(mensaje)
        
        if not all(datos_parseados.values()):
            return ChatbotRules.get_mensaje_datos_incompletos()
        
        for key, value in datos_parseados.items():
            conversation_manager.set_datos_temporales(numero_telefono, key, value)
        
        valido, error = conversation_manager.validar_y_guardar_datos(numero_telefono)
        
        if not valido:
            return f"❌ Hay algunos errores en los datos:\n\n{error}\n\nPor favor corrige y envía la información nuevamente."
        
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
        return ChatbotRules.get_mensaje_confirmacion(conversacion)
    
    @staticmethod
    def _procesar_confirmacion(numero_telefono: str, mensaje: str) -> str:
        if mensaje in ['si', 'sí', 'yes', 'confirmo', 'ok', 'correcto']:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ENVIANDO)
            return "📤 Enviando tu solicitud..."
        elif mensaje in ['no', 'nope', 'incorrecto', 'error']:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
            conversation_manager.clear_datos_temporales(numero_telefono)
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            return f"✏️ Entendido. {ChatbotRules.get_mensaje_recoleccion_datos(conversacion.tipo_consulta)}"
        else:
            return "🤔 Por favor responde **SI** para confirmar o **NO** para corregir la información."
    
    @staticmethod
    def _parsear_datos_contacto(mensaje: str) -> dict:
        import re
        
        # Buscar email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, mensaje)
        email = email_match.group() if email_match else ""
        
        # Dividir el mensaje en líneas para buscar patrones
        lineas = [linea.strip() for linea in mensaje.split('\n') if linea.strip()]
        
        direccion = ""
        horario = ""
        descripcion = ""
        
        # Buscar patrones comunes
        for linea in lineas:
            linea_lower = linea.lower()
            if any(palabra in linea_lower for palabra in ['dirección', 'direccion', 'domicilio', 'ubicación']):
                direccion = linea.split(':', 1)[-1].strip() if ':' in linea else linea
            elif any(palabra in linea_lower for palabra in ['horario', 'hora', 'disponible', 'visita']):
                horario = linea.split(':', 1)[-1].strip() if ':' in linea else linea
            elif any(palabra in linea_lower for palabra in ['necesito', 'descripción', 'descripcion', 'detalle']):
                descripcion = linea.split(':', 1)[-1].strip() if ':' in linea else linea
        
        # Si no encontramos datos estructurados, intentar extraer por posición
        if not direccion and not horario and not descripcion and len(lineas) >= 3:
            # Asumir que después del email viene: dirección, horario, descripción
            mensaje_sin_email = mensaje
            if email:
                mensaje_sin_email = mensaje.replace(email, "").strip()
            
            partes = [parte.strip() for parte in mensaje_sin_email.split('\n') if parte.strip()]
            if len(partes) >= 3:
                direccion = partes[0] if not direccion else direccion
                horario = partes[1] if not horario else horario  
                descripcion = " ".join(partes[2:]) if not descripcion else descripcion
        
        return {
            'email': email,
            'direccion': direccion,
            'horario_visita': horario,
            'descripcion': descripcion
        }