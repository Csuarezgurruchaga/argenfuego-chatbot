from pydantic import BaseModel, EmailStr, Field, validator
from enum import Enum
from typing import Optional

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
    VALIDANDO_DATOS = "validando_datos"
    CONFIRMANDO = "confirmando"
    ENVIANDO = "enviando"
    FINALIZADO = "finalizado"

class DatosContacto(BaseModel):
    email: EmailStr
    direccion: str = Field(..., min_length=5, max_length=200)
    horario_visita: str = Field(..., min_length=3, max_length=100)
    descripcion: str = Field(..., min_length=10, max_length=500)
    
    @validator('direccion')
    def validar_direccion(cls, v):
        if not v.strip():
            raise ValueError('La dirección no puede estar vacía')
        return v.strip()
    
    @validator('horario_visita')
    def validar_horario(cls, v):
        if not v.strip():
            raise ValueError('El horario no puede estar vacío')
        return v.strip()
    
    @validator('descripcion')
    def validar_descripcion(cls, v):
        if not v.strip():
            raise ValueError('La descripción no puede estar vacía')
        return v.strip()

class ConversacionData(BaseModel):
    numero_telefono: str
    estado: EstadoConversacion
    tipo_consulta: Optional[TipoConsulta] = None
    datos_contacto: Optional[DatosContacto] = None
    datos_temporales: dict = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True