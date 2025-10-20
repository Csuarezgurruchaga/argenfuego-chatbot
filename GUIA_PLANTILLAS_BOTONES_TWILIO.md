# Guía para Botones Interactivos con Plantillas de Twilio

> ⚠️ **Aviso**: Este documento se conserva solo como referencia histórica. El proyecto actual utiliza la WhatsApp Cloud API de Meta y no depende de Twilio. Usa esta guía únicamente si necesitas revisar el enfoque anterior.

## 🎯 **SOLUCIÓN SIMPLIFICADA: PLANTILLAS DE TWILIO**

En lugar de configurar variables complejas de Facebook, puedes usar **plantillas de Twilio** que son mucho más simples.

## ✅ **VENTAJAS DE LAS PLANTILLAS DE TWILIO**

- ✅ **No necesitas** variables de Facebook
- ✅ **Solo usas Twilio** (que ya tienes configurado)
- ✅ **Botones interactivos** funcionan perfectamente
- ✅ **Configuración simple** en Railway
- ❌ **Requiere aprobación** de WhatsApp (24-48 horas)

## 🔧 **PASO 1: CREAR PLANTILLA EN TWILIO**

### **1.1 Ir a Twilio Console**
1. **Ve a [console.twilio.com](https://console.twilio.com/)**
2. **Navega a**: Messaging → Senders → Content Template Builder
3. **Haz clic en**: "Create new"

### **1.2 Configurar la Plantilla**
```
Template Name: menu_buttons
Category: UTILITY
Language: Spanish (es)
Content Type: Interactive Message
```

### **1.3 Configurar Botones**
```
Body: {{1}}

[{{2}}] [{{3}}] [{{4}}]
```

**Variables:**
- `{{1}}`: Mensaje principal (ej: "¿En qué puedo ayudarte hoy?")
- `{{2}}`: Botón 1 (ej: "📋 Presupuesto")
- `{{3}}`: Botón 2 (ej: "🚨 Urgencia")
- `{{4}}`: Botón 3 (ej: "❓ Otras consultas")

### **1.4 Enviar para Aprobación**
1. **Haz clic en**: "Save and submit for WhatsApp approval"
2. **Espera la aprobación** (24-48 horas)
3. **Anota el Template SID** (lo necesitarás)

## 🔧 **PASO 2: CONFIGURAR EN RAILWAY**

### **2.1 Agregar Variable de Entorno**
En Railway, agrega esta variable:

```bash
MENU_BUTTONS_TEMPLATE_SID=HX8c5dc18e13830ed556f47c1dcd5f9aa3
```

**Reemplaza** `HX8c5dc18e13830ed556f47c1dcd5f9aa3` con tu Template SID real.

### **2.2 Redesplegar**
1. **Guarda** la variable
2. **Espera** que se redespliegue automáticamente

## 🧪 **PASO 3: PROBAR**

### **3.1 Probar Botones**
```bash
curl -X POST 'https://tu-app.railway.app/test-interactive-buttons' \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'test_number=+5491135722871'
```

### **3.2 Resultado Esperado**
Deberías ver botones interactivos reales como:
```
¿En qué puedo ayudarte hoy?

[📋 Presupuesto] [🚨 Urgencia] [❓ Otras consultas]
```

## 📋 **PLANTILLAS ADICIONALES RECOMENDADAS**

### **Plantilla de Handoff**
```
Template Name: handoff_buttons
Body: {{1}}

[{{2}}] [{{3}}]
```

**Variables:**
- `{{1}}`: "Te conecto con un agente humano ahora mismo..."
- `{{2}}`: "⬅️ Volver al menú"
- `{{3}}`: "✋ Finalizar chat"

### **Plantilla de Confirmación**
```
Template Name: confirmation_buttons
Body: {{1}}

[{{2}}] [{{3}}] [{{4}}]
```

**Variables:**
- `{{1}}`: Mensaje de confirmación
- `{{2}}`: "✅ Sí"
- `{{3}}`: "❌ No"
- `{{4}}`: "⬅️ Menú"

## 🔄 **FLUJO DE FUNCIONAMIENTO**

### **Con Plantilla Configurada:**
1. **Usuario envía "hola"**
2. **Sistema usa plantilla** de Twilio
3. **Usuario ve botones** interactivos reales
4. **Usuario hace clic** en botón
5. **Sistema procesa** la respuesta

### **Sin Plantilla (Fallback):**
1. **Usuario envía "hola"**
2. **Sistema usa texto** mejorado
3. **Usuario ve menú** con formato visual
4. **Usuario escribe** número
5. **Sistema procesa** la respuesta

## ⚠️ **LIMITACIONES IMPORTANTES**

### **Plantillas de Twilio:**
- ✅ **Botones interactivos** reales
- ✅ **Solo Twilio** (sin Facebook)
- ❌ **Requiere aprobación** (24-48 horas)
- ❌ **Plantillas estáticas** (no dinámicas)

### **Fallback (Sin Plantilla):**
- ✅ **Funciona inmediatamente**
- ✅ **Sin aprobación** requerida
- ✅ **Totalmente dinámico**
- ❌ **Solo texto** (no botones reales)

## 🎯 **RECOMENDACIÓN FINAL**

### **Para Producción:**
1. **Crea las plantillas** en Twilio
2. **Configura las variables** en Railway
3. **Disfruta de botones** interactivos reales

### **Para Desarrollo/Pruebas:**
1. **No configures plantillas**
2. **Usa el fallback** automático
3. **Funciona perfectamente** sin configuración adicional

## 📞 **SOPORTE**

Si tienes problemas:
1. **Verifica** que la plantilla esté aprobada
2. **Confirma** que el Template SID sea correcto
3. **Revisa logs** de Railway para errores
4. **Prueba** con el endpoint de testing

¡Esta es la solución más simple y efectiva! 🚀
