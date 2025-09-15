from typing import Dict, Optional
from .models import ConversacionData, EstadoConversacion, TipoConsulta, DatosContacto, DatosConsultaGeneral
from pydantic import ValidationError
from services.metrics_service import metrics_service

class ConversationManager:
    def __init__(self):
        self.conversaciones: Dict[str, ConversacionData] = {}
    
    def get_conversacion(self, numero_telefono: str) -> ConversacionData:
        if numero_telefono not in self.conversaciones:
            self.conversaciones[numero_telefono] = ConversacionData(
                numero_telefono=numero_telefono,
                estado=EstadoConversacion.INICIO
            )
        return self.conversaciones[numero_telefono]
    
    def update_estado(self, numero_telefono: str, nuevo_estado: EstadoConversacion):
        conversacion = self.get_conversacion(numero_telefono)
        # Guardar el estado anterior antes de cambiarlo
        conversacion.estado_anterior = conversacion.estado
        conversacion.estado = nuevo_estado
    
    def set_tipo_consulta(self, numero_telefono: str, tipo: TipoConsulta):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.tipo_consulta = tipo
    
    def set_datos_temporales(self, numero_telefono: str, key: str, value: str):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.datos_temporales[key] = value
    
    def get_datos_temporales(self, numero_telefono: str, key: str) -> Optional[str]:
        conversacion = self.get_conversacion(numero_telefono)
        return conversacion.datos_temporales.get(key)
    
    def validar_y_guardar_datos(self, numero_telefono: str) -> tuple[bool, Optional[str]]:
        conversacion = self.get_conversacion(numero_telefono)
        datos_temp = conversacion.datos_temporales
        
        # Validar campos individualmente antes de crear el modelo
        error_msgs = []
        
        # Validar email solo si tiene contenido
        email = datos_temp.get('email', '')
        if email and email.strip():
            import re
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            if not re.search(email_pattern, email):
                error_msgs.append("📧 Email inválido. Ejemplo: juan@empresa.com")
        
        # Validar descripción (siempre requerida)
        descripcion = datos_temp.get('descripcion', '')
        if not descripcion or len(descripcion.strip()) < 10:
            error_msgs.append("📝 Descripción debe tener al menos 10 caracteres")
        
        # Para presupuestos y urgencias, validar campos opcionales solo si tienen contenido
        if conversacion.tipo_consulta != TipoConsulta.OTRAS:
            direccion = datos_temp.get('direccion', '')
            if direccion and direccion.strip() and len(direccion.strip()) < 5:
                error_msgs.append("📍 Dirección debe tener al menos 5 caracteres")
            
            horario = datos_temp.get('horario_visita', '')
            if horario and horario.strip() and len(horario.strip()) < 3:
                error_msgs.append("🕒 Horario debe tener al menos 3 caracteres")
        
        if error_msgs:
            return False, "\n".join(error_msgs)
        
        # Si no hay errores, crear el modelo con valores por defecto para campos vacíos
        try:
            if conversacion.tipo_consulta == TipoConsulta.OTRAS:
                datos_contacto = DatosConsultaGeneral(
                    email=email or "no_proporcionado@ejemplo.com",  # Valor por defecto
                    descripcion=descripcion
                )
            else:
                datos_contacto = DatosContacto(
                    email=email or "no_proporcionado@ejemplo.com",  # Valor por defecto
                    direccion=direccion or "No proporcionada",
                    horario_visita=horario or "No especificado",
                    descripcion=descripcion
                )
            
            conversacion.datos_contacto = datos_contacto
            return True, None
        except ValidationError as e:
            return False, f"Error interno: {str(e)}"
    
    def clear_datos_temporales(self, numero_telefono: str):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.datos_temporales.clear()
    
    def set_nombre_usuario(self, numero_telefono: str, nombre: str):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.nombre_usuario = nombre
    
    def finalizar_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]
            try:
                metrics_service.on_conversation_finished()
            except Exception:
                pass
    
    def reset_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]
    
    # Métodos para manejo secuencial de campos
    def get_campo_siguiente(self, numero_telefono: str) -> str:
        """Retorna el próximo campo que necesita ser recolectado"""
        conversacion = self.get_conversacion(numero_telefono)
        datos_temp = conversacion.datos_temporales
        
        # Siempre empezamos con la descripción (motivo de la consulta)
        descripcion = datos_temp.get('descripcion')
        if descripcion is None:
            return 'descripcion'
        
        # Después de la descripción, pedimos datos de contacto como opcionales
        # Para "Otras consultas" solo pedimos email
        if conversacion.tipo_consulta == TipoConsulta.OTRAS:
            campos_orden = ['email']
        else:
            # Para presupuestos y urgencias pedimos todos los campos de contacto
            campos_orden = ['email', 'direccion', 'horario_visita']
        
        for campo in campos_orden:
            valor_campo = datos_temp.get(campo)
            # Un campo está incompleto si no existe o si existe pero está vacío (no saltado)
            if valor_campo is None:
                return campo
            # Si el campo existe (incluso si es string vacío), está completado
        
        return None  # Todos los campos están completos
    
    def marcar_campo_completado(self, numero_telefono: str, campo: str, valor: str):
        """Marca un campo como completado y lo guarda"""
        self.set_datos_temporales(numero_telefono, campo, valor)
    
    def es_ultimo_campo(self, numero_telefono: str, campo_actual: str) -> bool:
        """Verifica si el campo actual es el último que necesitamos"""
        conversacion = self.get_conversacion(numero_telefono)
        
        if conversacion.tipo_consulta == TipoConsulta.OTRAS:
            # Para OTRAS: el email es el último campo (descripción -> email)
            return campo_actual == 'email'
        else:
            # Para otros tipos: el horario_visita es el último campo (descripción -> email -> direccion -> horario_visita)
            return campo_actual == 'horario_visita'
    
    def get_progreso_campos(self, numero_telefono: str) -> tuple[int, int]:
        """Retorna (campos_completados, total_campos) para mostrar progreso"""
        conversacion = self.get_conversacion(numero_telefono)
        datos_temp = conversacion.datos_temporales
        
        # Para "Otras consultas" solo pedimos descripción y email
        if conversacion.tipo_consulta == TipoConsulta.OTRAS:
            campos_orden = ['descripcion', 'email']
        else:
            # Para presupuestos y urgencias pedimos todos los campos
            campos_orden = ['descripcion', 'email', 'direccion', 'horario_visita']
            
        completados = sum(1 for campo in campos_orden if datos_temp.get(campo) is not None)
        
        return completados, len(campos_orden)

conversation_manager = ConversationManager()