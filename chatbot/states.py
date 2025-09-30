from typing import Dict, Optional, List
from .models import ConversacionData, EstadoConversacion, TipoConsulta, DatosContacto, DatosConsultaGeneral
from pydantic import ValidationError
from services.metrics_service import metrics_service
from datetime import datetime

class ConversationManager:
    def __init__(self):
        self.conversaciones: Dict[str, ConversacionData] = {}

        # Sistema de cola FIFO para handoffs
        self.handoff_queue: List[str] = []  # Lista de números de teléfono en orden FIFO
        self.active_handoff: Optional[str] = None  # Número de teléfono activo actualmente
    
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

    # ========== MÉTODOS PARA GESTIÓN DE COLA DE HANDOFFS ==========

    def add_to_handoff_queue(self, numero_telefono: str) -> int:
        """
        Agrega una conversación a la cola de handoffs.
        Si no hay conversación activa, la activa automáticamente.

        Args:
            numero_telefono: Número de teléfono del cliente

        Returns:
            int: Posición en la cola (1-indexed)
        """
        # Solo agregar si no está ya en la cola
        if numero_telefono not in self.handoff_queue:
            self.handoff_queue.append(numero_telefono)

        # Si no hay conversación activa, activar esta
        if self.active_handoff is None:
            self.activate_next_handoff()

        # Retornar posición (1-indexed)
        try:
            return self.handoff_queue.index(numero_telefono) + 1
        except ValueError:
            return 1

    def activate_next_handoff(self) -> Optional[str]:
        """
        Activa la siguiente conversación en la cola (la primera).

        Returns:
            Optional[str]: Número de teléfono activado o None si la cola está vacía
        """
        if self.handoff_queue:
            self.active_handoff = self.handoff_queue[0]
            return self.active_handoff
        else:
            self.active_handoff = None
            return None

    def get_active_handoff(self) -> Optional[str]:
        """
        Obtiene el número de teléfono de la conversación activa.

        Returns:
            Optional[str]: Número activo o None
        """
        return self.active_handoff

    def get_queue_position(self, numero_telefono: str) -> Optional[int]:
        """
        Obtiene la posición de un número en la cola.

        Args:
            numero_telefono: Número a buscar

        Returns:
            Optional[int]: Posición (1-indexed) o None si no está en cola
        """
        try:
            return self.handoff_queue.index(numero_telefono) + 1
        except ValueError:
            return None

    def get_queue_size(self) -> int:
        """
        Obtiene la cantidad de conversaciones en la cola.

        Returns:
            int: Tamaño de la cola
        """
        return len(self.handoff_queue)

    def close_active_handoff(self) -> Optional[str]:
        """
        Cierra la conversación activa, la remueve de la cola,
        y activa automáticamente la siguiente.

        Returns:
            Optional[str]: Número del siguiente activado o None
        """
        if self.active_handoff and self.active_handoff in self.handoff_queue:
            # Remover de la cola
            self.handoff_queue.remove(self.active_handoff)

            # Finalizar conversación
            self.finalizar_conversacion(self.active_handoff)

            # Reset activo
            self.active_handoff = None

            # Activar siguiente
            return self.activate_next_handoff()

        return None

    def move_to_next_in_queue(self) -> Optional[str]:
        """
        Mueve la conversación activa al final de la cola
        y activa la siguiente.

        Returns:
            Optional[str]: Número del siguiente activado o None
        """
        if self.active_handoff and self.active_handoff in self.handoff_queue:
            # Mover al final
            self.handoff_queue.remove(self.active_handoff)
            self.handoff_queue.append(self.active_handoff)

            # Activar el nuevo primero
            return self.activate_next_handoff()

        return None

    def get_handoff_by_index(self, index: int) -> Optional[str]:
        """
        Obtiene el número de teléfono por posición en la cola.

        Args:
            index: Posición en la cola (1-indexed)

        Returns:
            Optional[str]: Número de teléfono o None si índice inválido
        """
        try:
            return self.handoff_queue[index - 1]
        except IndexError:
            return None

    def remove_from_handoff_queue(self, numero_telefono: str) -> bool:
        """
        Remueve un número de la cola de handoffs.
        Si era el activo, activa el siguiente automáticamente.

        Args:
            numero_telefono: Número a remover

        Returns:
            bool: True si fue removido, False si no estaba en cola
        """
        if numero_telefono not in self.handoff_queue:
            return False

        was_active = (self.active_handoff == numero_telefono)

        # Remover de la cola
        self.handoff_queue.remove(numero_telefono)

        # Si era el activo, activar siguiente
        if was_active:
            self.active_handoff = None
            self.activate_next_handoff()

        return True

    def format_queue_status(self) -> str:
        """
        Genera un mensaje formateado con el estado completo de la cola.

        Returns:
            str: Mensaje formateado
        """
        if not self.handoff_queue:
            return "📋 *COLA DE HANDOFFS*\n\n✅ No hay conversaciones activas.\n\nTodas las consultas han sido atendidas."

        lines = ["┌────────────────────────────────────────┐"]
        lines.append("│ 📋 *COLA DE HANDOFFS*                   │")
        lines.append("│                                        │")

        for i, numero in enumerate(self.handoff_queue):
            conversacion = self.get_conversacion(numero)
            is_active = (numero == self.active_handoff)

            # Calcular tiempo desde el inicio del handoff
            tiempo_desde_inicio = ""
            if conversacion.handoff_started_at:
                delta = datetime.utcnow() - conversacion.handoff_started_at
                minutos = int(delta.total_seconds() / 60)
                if minutos < 60:
                    tiempo_desde_inicio = f"{minutos} min"
                else:
                    horas = minutos // 60
                    mins = minutos % 60
                    tiempo_desde_inicio = f"{horas}h {mins}min"

            # Calcular tiempo desde último mensaje
            tiempo_ultimo_mensaje = ""
            if conversacion.last_client_message_at:
                delta = datetime.utcnow() - conversacion.last_client_message_at
                segundos = int(delta.total_seconds())
                if segundos < 60:
                    tiempo_ultimo_mensaje = f"{segundos} seg"
                else:
                    minutos = segundos // 60
                    tiempo_ultimo_mensaje = f"{minutos} min"

            if is_active:
                lines.append("│ [ACTIVO] 🟢 " + (conversacion.nombre_usuario or "Sin nombre")[:20].ljust(20) + " │")
                lines.append("│           " + numero[:25].ljust(25) + " │")
                if tiempo_desde_inicio:
                    lines.append("│           Iniciado hace " + tiempo_desde_inicio.ljust(13) + " │")
                if tiempo_ultimo_mensaje:
                    lines.append("│           Último msj hace " + tiempo_ultimo_mensaje.ljust(11) + " │")
            else:
                lines.append(f"│ [#{i+1}] ⏳ " + (conversacion.nombre_usuario or "Sin nombre")[:20].ljust(20) + " │")
                lines.append("│      " + numero[:30].ljust(30) + " │")
                if tiempo_desde_inicio:
                    lines.append("│      Esperando hace " + tiempo_desde_inicio.ljust(15) + " │")

                # Mostrar fragmento del mensaje inicial
                if conversacion.mensaje_handoff_contexto:
                    fragmento = conversacion.mensaje_handoff_contexto[:30]
                    if len(conversacion.mensaje_handoff_contexto) > 30:
                        fragmento += "..."
                    lines.append("│      Mensaje: \"" + fragmento[:22].ljust(22) + "\" │")

            lines.append("│                                        │")

        lines.append("│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │")
        lines.append(f"│ Total: {len(self.handoff_queue)} conversación(es)".ljust(40) + " │")

        # Calcular tiempo promedio de espera
        if len(self.handoff_queue) > 1:
            tiempos_espera = []
            for numero in self.handoff_queue[1:]:  # Excluir el activo
                conv = self.get_conversacion(numero)
                if conv.handoff_started_at:
                    delta = datetime.utcnow() - conv.handoff_started_at
                    tiempos_espera.append(delta.total_seconds() / 60)

            if tiempos_espera:
                promedio = int(sum(tiempos_espera) / len(tiempos_espera))
                lines.append(f"│ Tiempo promedio espera: {promedio} min".ljust(40) + " │")

        lines.append("└────────────────────────────────────────┘")

        return "\n".join(lines)

conversation_manager = ConversationManager()