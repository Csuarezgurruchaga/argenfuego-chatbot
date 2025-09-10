from .models import EstadoConversacion, TipoConsulta
from .states import conversation_manager
from config.company_profiles import get_urgency_redirect_message

# Mapeo de sinónimos para validación geográfica
SINONIMOS_CABA = [
    'caba', 'c.a.b.a', 'ciudad autonoma', 'ciudad autónoma', 
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
    'avellaneda', 'lanus', 'berazategui', 'florencio varela'
]

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
2️⃣ Coordinar una visita técnica para evaluar la dotación necesaria del lugar
3️⃣ Reportar una urgencia
4️⃣ Otras consultas

Responde con el número de la opción que necesitas 📱"""
        
        return saludo + menu
    
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
        
        return f"""📋 *Resumen de tu solicitud:*

🏷️ *Tipo de consulta:* {tipo_texto[conversacion.tipo_consulta]}
📧 *Email:* {datos.email}
📍 *Dirección:* {datos.direccion}
🕒 *Horario de visita:* {datos.horario_visita}
📝 *Descripción:* {datos.descripcion}

¿Es correcta toda la información? 

✅ Responde *"SI"* para confirmar y enviar la solicitud
❌ Responde *"NO"* si hay algo que corregir ✏️"""
    
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
            'descripcion': "📝 ¿Podrías describir qué necesitas específicamente? (ej: tipo de equipo <polvo quimico, CO2>, capacidad <5kg, 10kg> y Cantidad)"
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
    def _validar_ubicacion_geografica(direccion: str) -> str:
        """
        Valida si una dirección especifica CABA o Provincia, usando primero regex y luego LLM
        Retorna: 'CABA', 'PROVINCIA', o 'UNCLEAR'
        """
        direccion_lower = direccion.lower()
        
        # Primero intentar con regex/keywords (más rápido)
        for sinonimo in SINONIMOS_CABA:
            if sinonimo in direccion_lower:
                return 'CABA'
        
        for sinonimo in SINONIMOS_PROVINCIA:
            if sinonimo in direccion_lower:
                return 'PROVINCIA'
        
        # Si no encuentra con keywords, usar LLM como fallback
        try:
            from services.nlu_service import nlu_service
            resultado_llm = nlu_service.detectar_ubicacion_geografica(direccion)
            
            if resultado_llm.get('confianza', 0) >= 7:
                return resultado_llm.get('ubicacion_detectada', 'UNCLEAR')
            else:
                return 'UNCLEAR'
        except Exception:
            return 'UNCLEAR'
    
    @staticmethod
    def _get_mensaje_seleccion_ubicacion() -> str:
        return """📍 *¿Tu dirección es en:*

1️⃣ *CABA* (Ciudad Autónoma de Buenos Aires / Capital Federal)
2️⃣ *Provincia de Buenos Aires*

Por favor responde *1* para CABA o *2* para Provincia."""
    
    @staticmethod
    def _procesar_seleccion_ubicacion(numero_telefono: str, mensaje: str) -> str:
        """
        Procesa la selección del usuario para CABA o Provincia
        """
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        direccion_original = conversacion.datos_temporales.get('_direccion_pendiente', '')
        
        if mensaje in ['1', 'caba']:
            # Actualizar la dirección con CABA
            direccion_final = f"{direccion_original}, CABA"
            conversation_manager.set_datos_temporales(numero_telefono, 'direccion', direccion_final)
            conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', None)
            
            # Continuar con el flujo normal
            return ChatbotRules._continuar_despues_validacion_ubicacion(numero_telefono)
            
        elif mensaje in ['2', 'provincia']:
            # Actualizar la dirección con Provincia
            direccion_final = f"{direccion_original}, Provincia de Buenos Aires"
            conversation_manager.set_datos_temporales(numero_telefono, 'direccion', direccion_final)
            conversation_manager.set_datos_temporales(numero_telefono, '_direccion_pendiente', None)
            
            # Continuar con el flujo normal
            return ChatbotRules._continuar_despues_validacion_ubicacion(numero_telefono)
        else:
            return "❌ Por favor responde *1* para CABA o *2* para Provincia de Buenos Aires."
    
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
        return """✅ ¡Perfecto! Tu solicitud ha sido enviada exitosamente.

Nuestro equipo la revisará y se pondrá en contacto contigo a la brevedad en el email proporcionado.

¡Gracias por contactar a Argenfuego! 🔥

_Para una nueva consulta, puedes escribir "hola" en cualquier momento._"""
    
    @staticmethod
    def get_mensaje_error_opcion() -> str:
        return """❌ No entendí tu selección. 

Por favor responde con:
• *1* para Solicitar un presupuesto
• *2* para Visita técnica  
• *3* para Reportar urgencia
• *4* para Otras consultas"""
    
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
            
            # Limpiar campo temporal y volver a confirmación
            conversation_manager.set_datos_temporales(numero_telefono, '_campo_a_corregir', None)
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CONFIRMANDO)
            
            return f"✅ Campo actualizado correctamente.\n\n{ChatbotRules.get_mensaje_confirmacion(conversacion)}"
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
        
        mensaje_limpio = mensaje.strip().lower()
        
        if mensaje_limpio in ['hola', 'hi', 'hello', 'inicio', 'empezar']:
            conversation_manager.reset_conversacion(numero_telefono)
            conversacion = conversation_manager.get_conversacion(numero_telefono)
            
            # Guardar nombre de usuario en la nueva conversación
            if nombre_usuario:
                conversation_manager.set_nombre_usuario(numero_telefono, nombre_usuario)
            
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
        
        if conversacion.estado == EstadoConversacion.INICIO:
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
            return ChatbotRules.get_mensaje_inicial_personalizado(conversacion.nombre_usuario or nombre_usuario)
        
        elif conversacion.estado == EstadoConversacion.ESPERANDO_OPCION:
            return ChatbotRules._procesar_seleccion_opcion(numero_telefono, mensaje_limpio)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS:
            return ChatbotRules._procesar_datos_contacto(numero_telefono, mensaje)
        
        elif conversacion.estado == EstadoConversacion.RECOLECTANDO_DATOS_INDIVIDUALES:
            return ChatbotRules._procesar_campo_individual(numero_telefono, mensaje)
        
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
            
            # REDIRECCIÓN INMEDIATA PARA URGENCIAS
            if tipo_consulta == TipoConsulta.URGENCIA:
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.FINALIZADO)
                return get_urgency_redirect_message()
            
            # Para otras consultas, continuar flujo normal
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
            return ChatbotRules.get_mensaje_recoleccion_datos(tipo_consulta)
        else:
            # Fallback: usar NLU para mapear mensaje a intención
            from services.nlu_service import nlu_service
            tipo_consulta_nlu = nlu_service.mapear_intencion(mensaje)
            
            if tipo_consulta_nlu:
                conversation_manager.set_tipo_consulta(numero_telefono, tipo_consulta_nlu)
                
                # REDIRECCIÓN INMEDIATA PARA URGENCIAS (NLU)
                if tipo_consulta_nlu == TipoConsulta.URGENCIA:
                    conversation_manager.update_estado(numero_telefono, EstadoConversacion.FINALIZADO)
                    return f"✅ Entendí que tienes una urgencia.\n\n{get_urgency_redirect_message()}"
                
                # Para otras consultas, continuar flujo normal
                conversation_manager.update_estado(numero_telefono, EstadoConversacion.RECOLECTANDO_DATOS)
                return f"✅ Entendí que necesitas {ChatbotRules._get_texto_tipo_consulta(tipo_consulta_nlu)}.\n\n{ChatbotRules.get_mensaje_recoleccion_datos(tipo_consulta_nlu)}"
            else:
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
                        mensaje_encontrados = f"✅ Ya tengo: {', '.join(campos_texto)}\n\n"
                
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
            # Cambiar a estado de corrección y preguntar qué campo modificar
            conversation_manager.update_estado(numero_telefono, EstadoConversacion.CORRIGIENDO)
            return ChatbotRules._get_mensaje_pregunta_campo_a_corregir()
        else:
            return "🤔 Por favor responde *SI* para confirmar o *NO* para corregir la información."
    
    @staticmethod
    def _parsear_datos_contacto_basico(mensaje: str) -> dict:
        import re
        import dateparser
        from datetime import datetime
        
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