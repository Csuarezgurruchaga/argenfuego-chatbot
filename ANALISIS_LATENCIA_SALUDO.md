# 🔍 Análisis de Latencia en Saludo Inicial

## Problema Reportado
El saludo inicial del chatbot (disparado por "hola") tarda demasiado en enviarse a pesar de tener delays configurados. El flujo consta de:
1. Mensaje inicial de saludo
2. Emoji/sticker
3. Plantilla (si está activada) con delay de 2.5s

## 🕵️ Análisis del Flujo Actual

### Secuencia de Ejecución (línea por línea)

```python
# main.py línea 441
respuesta = ChatbotRules.procesar_mensaje(numero_telefono, mensaje_usuario, profile_name)
    ↓
# chatbot/rules.py línea 945-960
if mensaje_limpio in ['hola', 'hi', 'hello', 'inicio', 'empezar']:
    conversation_manager.reset_conversacion(numero_telefono)  # ❶
    conversacion = conversation_manager.get_conversacion(numero_telefono)
    
    if nombre_usuario:
        conversation_manager.set_nombre_usuario(numero_telefono, nombre_usuario)
    
    conversation_manager.update_estado(numero_telefono, EstadoConversacion.ESPERANDO_OPCION)
    metrics_service.on_conversation_started()  # ❷ (puede hacer llamada a Sheets)
    
    return ChatbotRules._enviar_flujo_saludo_completo(numero_telefono, nombre_usuario)
```

### Dentro de `_enviar_flujo_saludo_completo()` (línea 222-309)

```python
# 1. ENVÍO INMEDIATO del saludo (SÍNCRONO - BLOQUEA EL WEBHOOK)
saludo = "¡Hola {nombre}! 👋🏻 Mi nombre es Eva"
saludo_enviado = twilio_service.send_whatsapp_message(numero_telefono, saludo)  # ❸
# ⏱️ Esta llamada HTTP a Twilio API bloquea el webhook ~200-500ms

# 2. Crear threads para sticker y menú (ASÍNCRONOS)
thread1 = threading.Thread(target=enviar_sticker_primero)
thread1.start()  # ❹ Ejecuta en background

thread2 = threading.Thread(target=enviar_menu)
thread2.start()  # ❺ Ejecuta en background con delay de 2.5s

# 3. Retornar respuesta vacía
return ""  # El webhook responde inmediatamente después
```

### Dentro de los threads (background):

**Thread 1 - Sticker:**
```python
def enviar_sticker_primero():
    profile = get_active_company_profile()  # ❻ (lectura de config)
    company_name = profile['name'].lower()
    image_url = f"https://raw.githubusercontent.com/..."
    twilio_service.send_whatsapp_media(numero_telefono, image_url)  # ❼
    # ⏱️ Llamada HTTP a Twilio ~300-800ms
```

**Thread 2 - Menú:**
```python
def enviar_menu():
    time.sleep(2.5)  # ❽ Delay intencional
    
    if use_interactive_buttons:
        # Enviar plantilla de botones
        ChatbotRules.send_menu_interactivo(numero_telefono, nombre_usuario)  # ❾
        # ⏱️ Llamada HTTP a Twilio ~200-600ms
    else:
        # Enviar menú tradicional
        mensaje_completo = ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
        twilio_service.send_whatsapp_message(numero_telefono, mensaje_completo)  # ❿
        # ⏱️ Llamada HTTP a Twilio ~200-500ms
```

## 🐛 Causas Identificadas de Latencia

### 1. **CAUSA PRINCIPAL: El saludo se envía SÍNCRONO en el hilo principal** ⚠️
- **Impacto:** ALTO (200-500ms)
- **Ubicación:** `chatbot/rules.py` línea 296
- **Problema:** La llamada `twilio_service.send_whatsapp_message()` para el saludo inicial bloquea el webhook hasta que Twilio responde
- **Efecto usuario:** El primer mensaje tarda en aparecer porque el servidor está esperando la respuesta de Twilio

### 2. **Llamada a metrics_service.on_conversation_started()** 
- **Impacto:** MEDIO (50-300ms si hay Sheets habilitado)
- **Ubicación:** `chatbot/rules.py` línea 955
- **Problema:** Si `ENABLE_SHEETS_METRICS=true`, esto hace una llamada HTTP a Google Sheets API ANTES de enviar cualquier mensaje
- **Código relevante:**
```python
try:
    metrics_service.on_conversation_started()  # Puede llamar a Sheets
except Exception:
    pass
```

### 3. **Múltiples llamadas HTTP síncronas a Twilio API**
- **Impacto:** MEDIO (acumulado 600-1800ms)
- **Problema:** Cada llamada a Twilio espera respuesta antes de continuar:
  - Saludo: ~200-500ms (BLOQUEA)
  - Sticker: ~300-800ms (en thread, no bloquea)
  - Menú: ~200-600ms (en thread + 2.5s delay, no bloquea)

### 4. **No hay lazy initialization de cliente Twilio**
- **Impacto:** BAJO (~10-50ms solo en cold start)
- **Ubicación:** `services/twilio_service.py` línea 21
- **Problema:** El cliente de Twilio se instancia cada vez (aunque es singleton)

### 5. **Lectura de variables de entorno en cada flujo**
- **Impacto:** BAJO (~5-20ms)
- **Ubicación:** Múltiples lugares (`os.getenv()` repetido)
- **Problema:** Se lee `USE_INTERACTIVE_BUTTONS`, perfiles de compañía, etc. en cada ejecución

### 6. **Race condition potencial: orden de mensajes**
- **Impacto:** UX (no latencia, pero confuso)
- **Problema:** Los threads no están sincronizados, por lo que el orden de llegada puede ser:
  - Escenario A: Saludo → Sticker → Menú ✅ (ideal)
  - Escenario B: Sticker → Saludo → Menú ❌ (sticker llegó primero)
  - Escenario C: Saludo → Menú → Sticker ❌ (menú llegó antes del delay)

## 📊 Tiempos Estimados Actuales

| Paso | Tiempo (ms) | ¿Bloquea webhook? |
|------|-------------|-------------------|
| 1. Reset conversación | 5-10 | Sí |
| 2. Actualizar estado | 5-10 | Sí |
| 3. Metrics (si Sheets) | 50-300 | Sí |
| 4. **Enviar saludo (HTTP Twilio)** | **200-500** | **Sí ⚠️** |
| 5. Crear threads | 1-5 | Sí |
| 6. Webhook responde 200 OK | - | - |
| 7. Enviar sticker (thread) | 300-800 | No (background) |
| 8. Delay menú | 2500 | No (background) |
| 9. Enviar menú (thread) | 200-600 | No (background) |
| **TOTAL bloqueo webhook** | **~260-825ms** | - |
| **TOTAL percibido por usuario** | **~3200-4200ms** | - |

## 🎯 Plan de Acción para Resolver la Latencia

### **SOLUCIÓN 1: Mover TODOS los envíos a threads asíncronos** ⭐ (RECOMENDADA)

**Objetivo:** Que el webhook responda en <50ms, todos los mensajes se envíen en background

**Cambios:**
```python
def _enviar_flujo_saludo_completo(numero_telefono: str, nombre_usuario: str = "") -> str:
    import threading
    import time
    
    def enviar_todo_secuencial():
        # 1. Saludo (inmediato)
        if nombre_usuario:
            saludo = f"¡Hola {nombre_usuario}! 👋🏻 Mi nombre es Eva"
        else:
            saludo = "¡Hola! 👋🏻 Mi nombre es Eva"
        
        twilio_service.send_whatsapp_message(numero_telefono, saludo)
        
        # 2. Sticker (mini-delay de 0.3s para que saludo llegue primero)
        time.sleep(0.3)
        profile = get_active_company_profile()
        company_name = profile['name'].lower()
        image_url = f"https://raw.githubusercontent.com/..."
        twilio_service.send_whatsapp_media(numero_telefono, image_url)
        
        # 3. Menú (delay de 1.5s desde el sticker = 1.8s total)
        time.sleep(1.5)
        if use_interactive_buttons:
            ChatbotRules.send_menu_interactivo(numero_telefono, nombre_usuario)
        else:
            mensaje_completo = ChatbotRules.get_mensaje_inicial_personalizado(nombre_usuario)
            twilio_service.send_whatsapp_message(numero_telefono, mensaje_completo)
    
    # Ejecutar todo en un solo thread secuencial
    thread = threading.Thread(target=enviar_todo_secuencial)
    thread.daemon = True
    thread.start()
    
    return ""  # Webhook responde inmediatamente
```

**Beneficios:**
- ✅ Webhook responde en ~15-30ms (solo operaciones de memoria)
- ✅ Usuario no percibe latencia en el chatbot
- ✅ Orden garantizado: Saludo → Sticker → Menú
- ✅ Control total sobre timing entre mensajes

**Desventajas:**
- ⚠️ Si el thread falla, no hay forma de notificar al usuario (pero ya retornamos "")

---

### **SOLUCIÓN 2: Mover metrics a background**

**Objetivo:** Eliminar llamada síncrona a Google Sheets

**Cambios:**
```python
# En chatbot/rules.py línea 954-957
try:
    # Ejecutar en thread separado
    threading.Thread(target=lambda: metrics_service.on_conversation_started()).start()
except Exception:
    pass
```

**Beneficios:**
- ✅ Elimina 50-300ms de latencia
- ✅ No afecta funcionalidad

**Desventajas:**
- ⚠️ Métricas pueden perderse si el servidor se cae (pero es aceptable)

---

### **SOLUCIÓN 3: Cache de configuraciones** (complementaria)

**Objetivo:** Evitar lecturas repetidas de env vars y perfiles

**Cambios:**
```python
# En chatbot/rules.py (nivel módulo)
_USE_INTERACTIVE_BUTTONS = os.getenv("USE_INTERACTIVE_BUTTONS", "false").lower() == "true"
_COMPANY_PROFILE = get_active_company_profile()
_STICKER_URL = f"https://raw.githubusercontent.com/.../_{COMPANY_PROFILE['name'].lower()}.webp"

def _enviar_flujo_saludo_completo(...):
    # Usar las variables cacheadas
    if _USE_INTERACTIVE_BUTTONS:
        ...
```

**Beneficios:**
- ✅ Elimina 5-20ms por request
- ✅ Reduce carga en lecturas de env

**Desventajas:**
- ⚠️ Requiere restart para cambiar configuración (pero es aceptable en producción)

---

### **SOLUCIÓN 4: HTTP/2 persistent connections a Twilio** (avanzada)

**Objetivo:** Reducir latencia de red con Twilio API

**Cambios:**
```python
# En services/twilio_service.py
class TwilioService:
    def __init__(self):
        # ... existing code ...
        # Usar session con keep-alive
        import requests
        self.session = requests.Session()
        self.session.headers.update({'Connection': 'keep-alive'})
```

**Beneficios:**
- ✅ Reduce latencia de cada llamada en ~50-100ms
- ✅ Mejor uso de recursos de red

**Desventajas:**
- ⚠️ Requiere modificar SDK de Twilio (no recomendado)

---

## 🚀 Recomendación Final: Plan de Implementación

### **FASE 1: Cambios de alto impacto (70% mejora)** ⭐

1. **Mover saludo inicial a thread asíncrono** (SOLUCIÓN 1)
   - Tiempo: 30 min
   - Impacto: -200-500ms de latencia percibida
   - Riesgo: Bajo

2. **Mover metrics a background** (SOLUCIÓN 2)
   - Tiempo: 10 min
   - Impacto: -50-300ms
   - Riesgo: Muy bajo

3. **Ajustar delays para mejor UX**
   - Cambiar delay total de 2.5s a 1.8s (0.3s + 1.5s)
   - Tiempo: 5 min
   - Impacto: -700ms de tiempo total
   - Riesgo: Muy bajo

**Resultado esperado FASE 1:**
- Webhook responde en ~15-30ms (vs ~260-825ms actual)
- Usuario ve primer mensaje en ~200-500ms (vs ~600-1200ms actual)
- Flujo completo en ~2.3s (vs ~3.2-4.2s actual)
- **Mejora total: ~1.5-2 segundos** 🎉

### **FASE 2: Optimizaciones adicionales (20% mejora)**

4. **Cache de configuraciones** (SOLUCIÓN 3)
   - Tiempo: 20 min
   - Impacto: -5-20ms por request
   - Riesgo: Bajo

5. **Lazy loading de recursos**
   - Tiempo: 30 min
   - Impacto: -10-30ms
   - Riesgo: Bajo

### **FASE 3: Mejoras avanzadas (10% mejora, opcional)**

6. **Optimizar cliente Twilio con pooling**
   - Tiempo: 1-2 horas
   - Impacto: -50-100ms por llamada
   - Riesgo: Medio

## 📝 Checklist de Implementación

```markdown
FASE 1 (PRIORITARIA):
- [ ] Crear función `enviar_todo_secuencial()` con orden garantizado
- [ ] Mover saludo inicial a thread asíncrono
- [ ] Mover metrics a thread asíncrono
- [ ] Ajustar delays: 0.3s (sticker), 1.5s (menú)
- [ ] Testing en desarrollo con logs de timing
- [ ] Validar orden de mensajes: Saludo → Sticker → Menú
- [ ] Deploy a producción
- [ ] Monitorear logs de timing por 24h

FASE 2 (SECUNDARIA):
- [ ] Cachear USE_INTERACTIVE_BUTTONS
- [ ] Cachear company_profile y sticker URL
- [ ] Cachear otras env vars frecuentes
- [ ] Testing y deploy

FASE 3 (OPCIONAL):
- [ ] Investigar HTTP/2 con Twilio SDK
- [ ] Implementar connection pooling
- [ ] Benchmark de mejoras
```

## 🔍 Métricas a Monitorear Post-Implementación

1. **Tiempo de respuesta del webhook** (target: <50ms)
2. **Tiempo hasta primer mensaje del bot** (target: <500ms)
3. **Tiempo total del flujo de saludo** (target: <2.5s)
4. **Tasa de error en threads** (target: <0.1%)
5. **Orden correcto de mensajes** (target: >99%)

---

**Documento creado:** 2025-10-01
**Autor:** AI Assistant (Claude)
**Estado:** Pendiente de revisión e implementación

