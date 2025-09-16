from pydantic import BaseModel, EmailStr, Field
from enum import Enum
from typing import Optional
from datetime import datetime

class TipoConsulta(str, Enum):
    PRESUPUESTO = "presupuesto"
    VISITA_TECNICA = "visita_tecnica"
    URGENCIA = "urgencia"
    OTRAS = "otras"

class EstadoConversacion(str, Enum):
    INICIO = "inicio"
    ESPERANDO_OPCION = "esperando_opcion"
    RECOLECTANDO_DATOS = "recolectando_datos"
    RECOLECTANDO_DATOS_INDIVIDUALES = "recolectando_datos_individuales"
    RECOLECTANDO_SECUENCIAL = "recolectando_secuencial"  # Nuevo flujo paso a paso conversacional
    VALIDANDO_UBICACION = "validando_ubicacion"
    VALIDANDO_DATOS = "validando_datos"
    CONFIRMANDO = "confirmando"
    ENVIANDO = "enviando"
    FINALIZADO = "finalizado"
    CORRIGIENDO = "corrigiendo"  # Para preguntar qué campo corregir
    CORRIGIENDO_CAMPO = "corrigiendo_campo"  # Para recibir el nuevo valor del campo
    MENU_PRINCIPAL = "menu_principal"  # Para volver al menú principal
    ATENDIDO_POR_HUMANO = "atendido_por_humano"  # Handoff activo: bot silenciado

class DatosContacto(BaseModel):
    email: EmailStr
    direccion: str = Field(..., min_length=5, max_length=200, strip_whitespace=True)
    horario_visita: str = Field(..., min_length=3, max_length=100, strip_whitespace=True)
    descripcion: str = Field(..., min_length=10, max_length=500, strip_whitespace=True)

class DatosConsultaGeneral(BaseModel):
    """Modelo simplificado para consultas generales (TipoConsulta.OTRAS)"""
    email: EmailStr
    descripcion: str = Field(..., min_length=10, max_length=500, strip_whitespace=True)

class ConversacionData(BaseModel):
    numero_telefono: str
    estado: EstadoConversacion
    estado_anterior: Optional[EstadoConversacion] = None
    tipo_consulta: Optional[TipoConsulta] = None
    datos_contacto: Optional[DatosContacto] = None
    datos_temporales: dict = Field(default_factory=dict)
    nombre_usuario: Optional[str] = None
    # Campos para handoff a humano
    atendido_por_humano: bool = False
    slack_thread_ts: Optional[str] = None  # Thread de Slack asociado a la conversación
    slack_channel_id: Optional[str] = None
    handoff_started_at: Optional[datetime] = None
    last_client_message_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True
        
