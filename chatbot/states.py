from typing import Dict, Optional
from .models import ConversacionData, EstadoConversacion, TipoConsulta, DatosContacto, DatosConsultaGeneral
from pydantic import ValidationError

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
        
        try:
            # Para "Otras consultas" usar modelo simplificado
            if conversacion.tipo_consulta == TipoConsulta.OTRAS:
                datos_contacto = DatosConsultaGeneral(
                    email=datos_temp.get('email', ''),
                    descripcion=datos_temp.get('descripcion', '')
                )
            else:
                # Para presupuestos y visitas técnicas usar modelo completo
                datos_contacto = DatosContacto(
                    email=datos_temp.get('email', ''),
                    direccion=datos_temp.get('direccion', ''),
                    horario_visita=datos_temp.get('horario_visita', ''),
                    descripcion=datos_temp.get('descripcion', '')
                )
            
            conversacion.datos_contacto = datos_contacto
            return True, None
        except ValidationError as e:
            error_msgs = []
            for error in e.errors():
                field = error['loc'][0] if error['loc'] else 'campo'
                if field == 'email':
                    error_msgs.append("📧 Email inválido. Ejemplo: juan@empresa.com")
                elif field == 'direccion':
                    error_msgs.append("📍 Dirección debe tener al menos 5 caracteres")
                elif field == 'horario_visita':
                    error_msgs.append("🕒 Horario debe tener al menos 3 caracteres")
                elif field == 'descripcion':
                    error_msgs.append("📝 Descripción debe tener al menos 10 caracteres")
            return False, "\n".join(error_msgs)
    
    def clear_datos_temporales(self, numero_telefono: str):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.datos_temporales.clear()
    
    def set_nombre_usuario(self, numero_telefono: str, nombre: str):
        conversacion = self.get_conversacion(numero_telefono)
        conversacion.nombre_usuario = nombre
    
    def finalizar_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]
    
    def reset_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]
    
    # Métodos para manejo secuencial de campos
    def get_campo_siguiente(self, numero_telefono: str) -> str:
        """Retorna el próximo campo que necesita ser recolectado"""
        conversacion = self.get_conversacion(numero_telefono)
        datos_temp = conversacion.datos_temporales
        
        # Para "Otras consultas" solo pedimos descripción y email
        if conversacion.tipo_consulta == TipoConsulta.OTRAS:
            campos_orden = ['descripcion', 'email']
        else:
            # Para presupuestos y visitas técnicas pedimos todos los campos
            campos_orden = ['email', 'direccion', 'horario_visita', 'descripcion']
        
        for campo in campos_orden:
            if not datos_temp.get(campo) or not datos_temp.get(campo).strip():
                return campo
        
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
            # Para otros tipos: la descripción es el último campo
            return campo_actual == 'descripcion'
    
    def get_progreso_campos(self, numero_telefono: str) -> tuple[int, int]:
        """Retorna (campos_completados, total_campos) para mostrar progreso"""
        conversacion = self.get_conversacion(numero_telefono)
        datos_temp = conversacion.datos_temporales
        
        # Para "Otras consultas" solo pedimos descripción y email
        if conversacion.tipo_consulta == TipoConsulta.OTRAS:
            campos_orden = ['descripcion', 'email']
        else:
            # Para presupuestos y visitas técnicas pedimos todos los campos
            campos_orden = ['email', 'direccion', 'horario_visita', 'descripcion']
            
        completados = sum(1 for campo in campos_orden if datos_temp.get(campo) and datos_temp.get(campo).strip())
        
        return completados, len(campos_orden)

conversation_manager = ConversationManager()