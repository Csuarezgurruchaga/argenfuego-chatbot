# Configuración para Botones Interactivos de WhatsApp

## 🎯 **Para Implementar Botones Interactivos Reales**

Para que funcionen los botones interactivos como los de la imagen que enviaste, necesitas configurar las siguientes variables de entorno en Railway:

### **Variables de Entorno Requeridas**

```bash
# Token de acceso de WhatsApp Business API
WHATSAPP_ACCESS_TOKEN=tu_token_de_acceso_aqui

# ID del número de teléfono de WhatsApp Business
WHATSAPP_PHONE_NUMBER_ID=tu_phone_number_id_aqui
```

## 🔧 **Cómo Obtener Estas Variables**

### **1. WHATSAPP_ACCESS_TOKEN**
1. Ve a [Facebook Developers](https://developers.facebook.com/)
2. Selecciona tu aplicación de WhatsApp Business
3. Ve a **WhatsApp > API Setup**
4. Copia el **Temporary Access Token** o genera un **Permanent Access Token**

### **2. WHATSAPP_PHONE_NUMBER_ID**
1. En la misma página de **API Setup**
2. Busca **Phone Number ID**
3. Copia el ID (es un número largo)

## 📱 **Configuración en Railway**

1. **Ve a tu proyecto en Railway**
2. **Selecciona tu servicio**
3. **Ve a Variables**
4. **Agrega las nuevas variables**:
   - `WHATSAPP_ACCESS_TOKEN` = tu token
   - `WHATSAPP_PHONE_NUMBER_ID` = tu phone number ID
5. **Guarda y redespliega**

## 🧪 **Probar Botones Interactivos**

Una vez configurado, puedes probar:

```bash
# Probar menú interactivo
curl -X POST 'https://tu-app.railway.app/test-interactive-buttons' \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'test_number=+5491139061038'
```

## ⚠️ **Limitaciones Importantes**

### **Botones Interactivos Reales**
- ✅ **Solo en conversaciones iniciadas por el usuario**
- ✅ **Dentro de la ventana de 24 horas**
- ✅ **Máximo 3 botones por mensaje**
- ✅ **Máximo 20 caracteres por botón**

### **Fallback Automático**
Si los botones interactivos fallan, el sistema automáticamente envía el menú de texto con formato mejorado.

## 🔄 **Flujo de Funcionamiento**

1. **Usuario envía "hola"**
2. **Sistema intenta enviar botones interactivos**
3. **Si funciona**: Usuario ve botones clicables
4. **Si falla**: Usuario ve menú de texto mejorado
5. **Usuario responde** (botón o texto)
6. **Sistema procesa** la respuesta

## 🎨 **Tipos de Botones Disponibles**

### **1. Menú Principal**
```
[📋 Presupuesto] [🚨 Urgencia] [❓ Otras consultas]
```

### **2. Botones de Handoff**
```
[⬅️ Volver al menú] [✋ Finalizar chat]
```

### **3. Botones de Confirmación**
```
[✅ Sí] [❌ No] [⬅️ Menú]
```

## 🚀 **Próximos Pasos**

1. **Configurar variables de entorno** en Railway
2. **Probar botones interactivos** con el endpoint
3. **Verificar funcionamiento** en WhatsApp
4. **Personalizar textos** y emojis según necesites

## 📞 **Soporte**

Si tienes problemas:
1. **Verifica** que las variables estén configuradas correctamente
2. **Revisa logs** de Railway para errores
3. **Confirma** que el token de acceso sea válido
4. **Verifica** que el Phone Number ID sea correcto
