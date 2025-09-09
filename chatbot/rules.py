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
            'descripcion': "📝 ¿Podrías describir qué necesitas específicamente? (ej: tipo de equipos (polvo quimico, CO2), capacidad (5kg, 10kg) y Cantidad)"
        }
        return preguntas.get(campo, "Por favor proporciona más información.")
    
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
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES:
            return ChatbotRules._procesar_campo_individual(numero_telefono, mensaje)
        
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
            # Fallback: usar NLU para mapear mensaje a intención
            from services.nlu_service import nlu_service
            tipo_consulta_nlu = nlu_service.mapear_intencion(mensaje)
            
            if tipo_consulta_nlu:
                conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta_nlu)
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                return f"✅ Entendí que necesitas {ChatbotRules._get_texto_tipo_consulta(tipo_consulta_nlu)}.\n\n{ChatbotRules.get_mensaje_recoleccion_datos(tipo_consulta_nlu)}"
            else:
                return ChatbotRules.get_mensaje_error_opcion()
    
    @staticmethod
    def _procesar_datos_contacto(numero_telefono: str, mensaje: str) -> str:
        datos_parseados = ChatbotRules._parsear_datos_contacto(mensaje)
        
        # Si el parsing básico no obtuvo buenos resultados, intentar con LLM
        campos_encontrados_basicos = sum(1 for v in datos_parseados.values() if v)
        if campos_encontrados_basicos < 2 and len(mensaje) > 50:
            datos_llm = ChatbotRules._extraer_datos_con_llm(mensaje)
            if datos_llm:
                # Combinar resultados, dando prioridad al LLM para campos que no encontró el parser básico
                for key, value in datos_llm.items():
                    if key != 'tipo_consulta' and value and not datos_parseados.get(key):
                        datos_parseados[key] = value
        
        # Guardar los datos que sí se pudieron extraer
        campos_encontrados = []
        for key, value in datos_parseados.items():
            if value:
                conversation_manager.set_datos_temporales(numero_telefono, key, value)
                campos_encontrados.append(key)
        
        # Determinar qué campos faltan
        campos_requeridos = ['email', 'direccion', 'horario_visita', 'descripcion']
        campos_faltantes = [campo for campo in campos_requeridos if not datos_parseados.get(campo)]
        
        if not campos_faltantes:
            # Todos los campos están presentes, proceder con validación
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
            if campos_encontrados:
                nombres_campos = {
                    'email': '📧 Email',
                    'direccion': '📍 Dirección', 
                    'horario_visita': '🕒 Horario',
                    'descripcion': '📝 Descripción'
                }
                campos_texto = [nombres_campos[campo] for campo in campos_encontrados]
                mensaje_encontrados = f"✅ Ya tengo: {', '.join(campos_texto)}\n\n"
            
            return mensaje_encontrados + ChatbotRules._get_pregunta_campo_individual(campos_faltantes[0])
    
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
        import dateparser
        from datetime import datetime
        
        # Buscar email con regex mejorado
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
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
            'domicilio', 'calle', 'avenida', 'av.', 'av ', 'barrio'
        ]
        keywords_horario = [
            'horario', 'hora', 'disponible', 'visita', 'lunes', 'martes', 
            'miércoles', 'jueves', 'viernes', 'sábado', 'domingo', 'mañana', 
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