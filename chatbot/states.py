from typing import Dict, Optional
from .models import ConversacionData, EstadoConversacion, TipoConsulta, DatosContacto
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
    
    def finalizar_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]
    
    def reset_conversacion(self, numero_telefono: str):
        if numero_telefono in self.conversaciones:
            del self.conversaciones[numero_telefono]

conversation_manager = ConversationManager()