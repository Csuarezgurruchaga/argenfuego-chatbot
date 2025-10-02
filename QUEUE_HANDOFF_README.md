# Sistema de Cola FIFO para Handoffs

## 📋 Descripción General

Este documento describe el nuevo sistema de cola FIFO (First-In-First-Out) implementado para gestionar múltiples handoffs simultáneos en el chatbot de Argenfuego.

**Problema resuelto**: Antes de esta implementación, cuando había múltiples handoffs activos simultáneamente, todos los mensajes del agente se enviaban automáticamente al cliente más reciente, causando confusión y mensajes cruzados.

**Solución**: Sistema de cola ordenada donde siempre hay UNA conversación activa clara. Los mensajes del agente van automáticamente al cliente activo, eliminando toda ambigüedad.

## 🎯 Conceptos Clave

### Conversación Activa
- En todo momento hay **máximo una conversación activa**
- Todos los mensajes del agente van automáticamente a la conversación activa
- El agente ve claramente cuál es la conversación activa

### Cola de Espera
- Las conversaciones nuevas entran en la cola si ya hay una activa
- Se procesan en orden FIFO (First-In-First-Out)
- El agente puede ver el estado completo de la cola en cualquier momento

## 📱 Comandos Disponibles para el Agente

### Comandos Principales

#### `/done` (o `/d`, `/resuelto`, `/r`)
Finaliza la conversación activa y activa automáticamente la siguiente en cola.

**Uso típico**:
```
Agente está hablando con Juan.
Agente escribe: /done
→ Sistema cierra conversación con Juan
→ Sistema activa conversación con María (siguiente en cola)
→ Agente recibe notificación de nueva conversación activa
```

**Aliases**: `/done`, `/d`, `/resuelto`, `/r`, `/finalizar`, `/cerrar`

---

#### `/next` (o `/n`, `/siguiente`)
Mueve la conversación activa al final de la cola y activa la siguiente.

**Uso típico** (cuando necesitas cambiar temporalmente a otro cliente):
```
Cola: [ACTIVO] Juan, [#2] María
Agente escribe: /next
→ Sistema mueve Juan al final
→ Sistema activa María
→ Nueva cola: [ACTIVO] María, [#2] Juan
```

**Aliases**: `/next`, `/n`, `/siguiente`, `/skip`

---

#### `/queue` (o `/q`, `/cola`)
Muestra el estado completo de la cola con tiempos y detalles.

**Salida ejemplo**:
```
┌────────────────────────────────────────┐
│ 📋 COLA DE HANDOFFS                    │
│                                        │
│ [ACTIVO] 🟢 Juan Pérez                │
│           +5491123456789              │
│           Iniciado hace 5 min         │
│           Último msj hace 30 seg      │
│                                        │
│ [#2] ⏳ María López                    │
│      +5491123456790                   │
│      Esperando hace 3 min             │
│      Mensaje: "urgente!"              │
│                                        │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│ Total: 2 conversación(es)             │
│ Tiempo promedio espera: 3 min        │
└────────────────────────────────────────┘
```

**Aliases**: `/queue`, `/q`, `/cola`, `/list`, `/lista`

---

### Comandos de Información

#### `/active` (o `/a`, `/activo`)
Muestra información sobre la conversación actualmente activa.

**Salida ejemplo**:
```
🟢 CONVERSACIÓN ACTIVA

Cliente: Juan Pérez
Teléfono: +5491123456789
Tiempo activo: 5 min

━━━━━━━━━━━━━━━━━━━━━━━

📋 Cola: 3 conversación(es) total(es)

💬 Los mensajes que escribas irán a Juan Pérez.

Usa /queue para ver todas las conversaciones o /next para cambiar.
```

**Aliases**: `/active`, `/current`, `/a`, `/activo`, `/actual`

---

#### `/help` (o `/h`, `/ayuda`)
Muestra la lista completa de comandos disponibles con descripciones.

**Aliases**: `/help`, `/h`, `/ayuda`, `/?`, `/comandos`

---

## 🔄 Flujos de Uso Comunes

### Flujo 1: Atención Secuencial Básica

```
T=0min: Cliente A pide handoff
│
├─ Sistema: Agrega a cola (posición #1)
├─ Sistema: Activa conversación de Cliente A automáticamente
└─ Agente recibe: 🔔 HANDOFF ACTIVADO [1/1]
                   Cliente: Cliente A
                   Mensaje: "quiero hablar con un humano"

Agente escribe: "Hola, ¿en qué puedo ayudarte?"
└─ Sistema: Envía mensaje a Cliente A ✅

Cliente A: "Necesito un presupuesto"
└─ Agente recibe: 💬 Cliente A: "Necesito un presupuesto"

Agente escribe: "Perfecto, cuéntame más"
└─ Sistema: Envía mensaje a Cliente A ✅

Agente escribe: /done
│
├─ Sistema: Cierra conversación con Cliente A
├─ Sistema: Envía mensaje de cierre a Cliente A
└─ Agente recibe: ✅ Conversación finalizada. Cola vacía.
```

### Flujo 2: Múltiples Handoffs Simultáneos

```
T=0min: Cliente A pide handoff
│
└─ Sistema: Activa Cliente A [ACTIVO: A]

T=3min: Cliente B pide handoff (mientras A está activo)
│
├─ Sistema: Agrega B a la cola [ACTIVO: A] [#2: B]
└─ Agente recibe: 🔔 NUEVO HANDOFF EN COLA [#2/2]
                   Cliente: Cliente B
                   Mensaje: "urgente!"

                   📋 Cola actual:
                     [ACTIVO] 🟢 Cliente A
                     [#2] ⏳ Cliente B ← NUEVA

Agente sigue hablando con Cliente A normalmente:
Agente: "¿Algo más Cliente A?"
└─ Sistema: Envía a Cliente A ✅ (B espera en cola)

Cliente A: "No, eso es todo"

Agente escribe: /done
│
├─ Sistema: Cierra conversación con Cliente A
├─ Sistema: Activa Cliente B automáticamente
└─ Agente recibe: 🔔 HANDOFF ACTIVADO [1/1]
                   Cliente: Cliente B
                   Mensaje: "urgente!"

Agente escribe: "Hola Cliente B, ¿qué necesitas?"
└─ Sistema: Envía a Cliente B ✅
```

### Flujo 3: Cliente en Cola Envía Mensaje

```
Estado inicial: [ACTIVO: A] [#2: B]

Cliente B (en cola) envía: "¿Cuánto falta?"
│
├─ Agente recibe: 💬 [#2] Cliente B: "¿Cuánto falta?" (en cola)
└─ Agente recibe: ℹ️ Este mensaje es del cliente en posición #2.
                   Los mensajes que escribas irán al cliente activo.
                   Usa /next para cambiar o /queue para ver la cola.

Agente continúa hablando con Cliente A:
Agente: "Ok Cliente A, te envío el presupuesto"
└─ Sistema: Envía a Cliente A ✅ (NO a Cliente B)

Cliente B sigue esperando en cola hasta que:
- El agente use /done para cerrar A y pasar a B
- O el agente use /next para cambiar a B sin cerrar A
```

### Flujo 4: Cambiar de Cliente sin Cerrar

```
Estado inicial: [ACTIVO: A] [#2: B]

Agente escribe: /next
│
├─ Sistema: Mueve A al final de la cola
├─ Sistema: Activa B
├─ Nueva cola: [ACTIVO: B] [#2: A]
└─ Agente recibe: 🔔 HANDOFF ACTIVADO [1/1]
                   Cliente: Cliente B

Agente puede hablar con B ahora:
Agente: "Hola Cliente B"
└─ Sistema: Envía a Cliente B ✅

Cuando termine con B, puede hacer /next para volver a A:
Agente: /next
│
├─ Nueva cola: [ACTIVO: A] [#2: B]
└─ Agente puede continuar con A donde lo dejó
```

---

## 🚨 Casos Especiales

### Timeout por Inactividad (TTL Sweep)

El sistema cierra automáticamente conversaciones inactivas después de 120 minutos. Si la conversación cerrada era la activa, el sistema activa automáticamente la siguiente en cola.

```
Estado: [ACTIVO: A hace 125 min] [#2: B]

Cron job ejecuta TTL sweep:
│
├─ Sistema: Detecta que A excede TTL (120 min)
├─ Sistema: Cierra A automáticamente
├─ Sistema: Activa B automáticamente
└─ Agente recibe: 🔔 HANDOFF ACTIVADO [1/1]
                   Cliente: Cliente B
                   (conversación anterior cerrada por inactividad)
```

### Cliente Inactivo No Es el Activo

Si un cliente en cola (no activo) excede el TTL, se remueve de la cola sin afectar al activo:

```
Estado: [ACTIVO: A] [#2: B hace 125 min] [#3: C]

TTL sweep:
│
├─ Sistema: Detecta que B excede TTL
├─ Sistema: Remueve B de la cola
├─ Nueva cola: [ACTIVO: A] [#2: C]
└─ A sigue siendo el activo, C pasa a posición #2
```

---

## 📊 Arquitectura Técnica

### Componentes Modificados

1. **`chatbot/states.py`**
   - `ConversationManager` ahora tiene:
     - `handoff_queue: List[str]` - Lista ordenada de números en cola
     - `active_handoff: Optional[str]` - Número activo actualmente
   - 10 métodos nuevos para gestión de cola

2. **`services/agent_command_service.py`** (NUEVO)
   - Servicio centralizado para parsing y ejecución de comandos
   - Maneja todos los comandos del agente (`/done`, `/next`, etc.)

3. **`main.py`**
   - `handle_agent_message()` completamente reescrito
   - Notificaciones diferenciadas (activo vs. en cola)
   - TTL sweep ajustado para respetar cola
   - 3 funciones nuevas de formateo de notificaciones

4. **`chatbot/rules.py`**
   - Llama a `conversation_manager.add_to_handoff_queue()` en 3 ubicaciones
   - Integración transparente con sistema de cola

### Flujo de Datos

```
Cliente envía mensaje
    ↓
webhook en main.py recibe mensaje
    ↓
rules.py detecta solicitud de handoff
    ↓
conversation_manager.add_to_handoff_queue(numero)
    ↓
  ┌─────────────────────────────────┐
  │ ¿Hay conversación activa?       │
  └─────────────────────────────────┘
           ↓                ↓
         NO               SÍ
           ↓                ↓
    Activar esta       Agregar a cola
    automáticamente    en posición N
           ↓                ↓
    Notificar agente   Notificar agente
    como ACTIVO       como EN COLA (#N)
```

### Estructura de la Cola

```python
# Estado interno del ConversationManager
{
    "handoff_queue": ["+5491123456789", "+5491123456790", "+5491123456791"],
    "active_handoff": "+5491123456789"
}

# Representación visual para el agente:
# [ACTIVO] 🟢 +5491123456789
# [#2] ⏳ +5491123456790
# [#3] ⏳ +5491123456791
```

---

## ✅ Ventajas del Sistema

1. **Elimina ambigüedad 100%**: Siempre queda claro a qué cliente van los mensajes
2. **UX simple**: El agente solo escribe mensajes normalmente
3. **Prevención de errores**: Imposible enviar al cliente equivocado por accidente
4. **Orden justo**: Los clientes son atendidos en orden de llegada (FIFO)
5. **Visibilidad completa**: El agente siempre sabe el estado de la cola
6. **Flexibilidad**: Comandos `/next` permiten cambiar orden cuando es necesario

---

## 🔧 Troubleshooting

### Problema: "No hay conversación activa"

**Causa**: No hay ningún cliente en handoff actualmente.

**Solución**: Esperar a que un cliente solicite handoff. Usar `/queue` para verificar.

### Problema: Mensajes no llegan al cliente esperado

**Verificación**:
1. Usar `/active` para ver qué conversación está activa
2. Usar `/queue` para ver el orden completo
3. Los mensajes **siempre** van al cliente activo

**Solución**: Usar `/next` para cambiar al cliente deseado antes de escribir el mensaje.

### Problema: Cliente en cola lleva mucho tiempo esperando

**Opción 1**: Usar `/next` para atenderlo antes (lo activa inmediatamente)

**Opción 2**: Finalizar rápidamente con el cliente activo usando `/done`

### Problema: ¿Cómo volver al cliente anterior?

Si usaste `/next` y quieres volver al cliente anterior, simplemente usa `/next` de nuevo hasta que vuelva a ser el activo (se rotará la cola).

Alternativamente, usa `/queue` para ver las posiciones y luego `/next` repetidamente hasta alcanzar el cliente deseado.

---

## 📈 Métricas y Monitoreo

El sistema registra:
- Tiempo de espera promedio en cola
- Tiempo activo por conversación
- Cantidad de conversaciones cerradas por TTL
- Cantidad de conversaciones en cola simultáneas

Ver estas métricas usando el comando `/queue`.

---

## 🚀 Próximas Mejoras Futuras (No Implementadas)

Posibles extensiones futuras del sistema:

1. **Priorización**: Marcar ciertos clientes como "urgentes" para atender primero
2. **Múltiples agentes**: Asignar conversaciones diferentes a agentes diferentes
3. **Recordatorios automáticos**: Notificar al agente si un cliente lleva >10 min en cola
4. **Estadísticas detalladas**: Dashboard con métricas de handoff por período
5. **Prefix override**: Sistema `@2 mensaje` para enviar a cliente específico sin cambiar contexto

---

## 📝 Notas Importantes

- **Backward Compatibility**: Este sistema reemplaza completamente el sistema anterior de "más reciente"
- **Testing**: Se recomienda testing exhaustivo antes de usar en producción
- **Rollback**: Si hay problemas, se puede hacer rollback a la branch `main`
- **Documentación adicional**: Ver commits de la branch `feature/fix-concurrency-handoff`

---

Última actualización: Enero 2025
Versión del sistema: 2.0.0
Branch: `feature/fix-concurrency-handoff`