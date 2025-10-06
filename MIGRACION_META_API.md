# Migración a WhatsApp Cloud API (Meta)

Este documento describe la migración del sistema de **Twilio** a **WhatsApp Cloud API de Meta** para el canal de WhatsApp.

## Cambios Realizados

### 1. Nuevo Servicio: `MetaWhatsAppService`

Se creó `services/meta_whatsapp_service.py` que reemplaza a `twilio_service` para todo lo relacionado con WhatsApp.

**Funcionalidades:**
- ✅ Envío de mensajes de texto
- ✅ Envío de imágenes/media
- ✅ Envío de templates aprobados
- ✅ Botones interactivos (quick replies)
- ✅ Listas interactivas (list pickers)
- ✅ Validación de firma HMAC (X-Hub-Signature-256)
- ✅ Verificación de webhook (GET con hub.challenge)
- ✅ Extracción de mensajes del webhook
- ✅ Extracción de estados de mensajes (sent, delivered, read, failed)

### 2. Nuevo Endpoint: `/webhook/whatsapp`

Se agregó en `main.py`:

- **GET `/webhook/whatsapp`**: Verifica el webhook durante la configuración inicial en Meta Business Manager
- **POST `/webhook/whatsapp`**: Recibe mensajes, respuestas interactivas y estados de mensajes

### 3. Refactor de `WhatsAppHandoffService`

Todos los métodos ahora usan `meta_whatsapp_service` en lugar de `twilio_service`.

### 4. TwilioService (Intacto)

`twilio_service.py` se mantiene **sin cambios** y sigue siendo usado para:
- Email (si aplicaba)
- Cualquier otro canal no relacionado con WhatsApp

---

## Variables de Entorno Requeridas

### Nuevas Variables (WhatsApp Cloud API - Meta)

```bash
# Token de acceso de WhatsApp Cloud API
# Obtención: Meta Business Suite → Usuarios del sistema → Crear usuario → Generar token
# Permisos necesarios: whatsapp_business_messaging
META_WA_ACCESS_TOKEN=EAAG...

# ID del número de teléfono de WhatsApp Business
# Obtención: Meta Business Suite → WhatsApp → Configuración → ID del número de teléfono
# Nota: Usar el mismo número que usabas en Twilio
META_WA_PHONE_NUMBER_ID=123456789

# App Secret para validar firmas de webhooks
# Obtención: Configuración de la app → Básico → Clave secreta de la app
META_WA_APP_SECRET=abc123...

# Token de verificación de webhook (TÚ lo inventas)
# Usar cualquier string seguro (ej: "mi_token_secreto_123")
# Debes configurar este mismo valor en Meta cuando registres el webhook
META_WA_VERIFY_TOKEN=mi_token_secreto_123
```

### Variables Existentes (mantener)

```bash
# WhatsApp - General
AGENT_WHATSAPP_NUMBER=+5491135722871  # Número del agente humano

# Email (Twilio o SendGrid)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
# ... resto de config de email si aplica
```

---

## Configuración en Meta Business Manager

### Paso 1: Obtener Credenciales

1. **Access Token:**
   - Ve a [Meta Business Suite](https://business.facebook.com/)
   - **Configuración** → **Usuarios del sistema** → **Agregar**
   - Asigna permisos: `whatsapp_business_messaging`
   - Genera el token y cópialo a `META_WA_ACCESS_TOKEN`

2. **Phone Number ID:**
   - **WhatsApp** → **API Setup**
   - Copia el **Phone number ID** a `META_WA_PHONE_NUMBER_ID`

3. **App Secret:**
   - **Configuración** → **Básico** → **Clave secreta de la app**
   - Cópiala a `META_WA_APP_SECRET`

4. **Verify Token:**
   - Inventa un string seguro (ej: `webhook_verify_2024_secure`)
   - Guárdalo en `META_WA_VERIFY_TOKEN`

### Paso 2: Configurar Webhook

1. En Meta Business Manager, ve a **WhatsApp** → **Configuración** → **Webhooks**

2. Click en **Configurar webhook**

3. Ingresa:
   - **URL del webhook:** `https://tu-dominio.railway.app/webhook/whatsapp`
   - **Token de verificación:** El mismo valor que pusiste en `META_WA_VERIFY_TOKEN`

4. Click en **Verificar y guardar**

5. **Suscribirse a campos:**
   - Marca: ✅ `messages`
   - Opcional: ✅ `message_template_status_update` (si usas templates)

6. Click en **Guardar**

---

## Configuración en Railway

### Agregar Variables de Entorno

1. Ve a tu proyecto en [Railway](https://railway.app/)

2. **Variables** → **New Variable**

3. Agrega las 4 nuevas variables:
   ```
   META_WA_ACCESS_TOKEN
   META_WA_PHONE_NUMBER_ID
   META_WA_APP_SECRET
   META_WA_VERIFY_TOKEN
   ```

4. **Deploy** → Railway desplegará automáticamente con las nuevas variables

---

## Testing

### 1. Verificar Webhook (Manual)

Desde tu terminal:

```bash
curl -X GET "https://tu-dominio.railway.app/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=mi_token_secreto_123&hub.challenge=test123"
```

**Resultado esperado:** `test123` (el challenge)

### 2. Enviar Mensaje de Prueba

Envía un mensaje de WhatsApp al número del bot.

**Logs esperados (Railway):**
```
=== WEBHOOK WHATSAPP RECIBIDO ===
✅ Firma de webhook válida
Mensaje recibido de +5491135722871 (Usuario): Hola
```

### 3. Probar Handoff

Envía: "quiero hablar con un humano"

**Resultado esperado:**
- El agente (`AGENT_WHATSAPP_NUMBER`) recibe notificación
- Respuestas del agente llegan al cliente

---

## Diferencias Clave: Twilio vs Meta API

| Aspecto | Twilio | Meta Cloud API |
|---------|--------|----------------|
| **Formato de número** | `whatsapp:+5491135722871` | `5491135722871` (sin `+` ni prefijo) |
| **Autenticación** | Auth Token | Bearer Token |
| **Webhooks** | Form data | JSON + firma HMAC |
| **Verificación** | Opcional | Obligatoria (GET con challenge) |
| **Templates** | Content SID | Nombre + idioma + componentes |
| **Botones** | Limitado | Nativo (reply buttons, listas) |

---

## Rollback (si fuera necesario)

Si necesitas volver a Twilio temporalmente:

1. Revierte los cambios en `WhatsAppHandoffService`:
   ```python
   from .twilio_service import twilio_service
   # ... reemplazar meta_whatsapp_service por twilio_service
   ```

2. Revierte el webhook en `main.py`:
   - Usa `/webhook` en lugar de `/webhook/whatsapp`

3. Reconfigura el webhook de Twilio en su consola

---

## Métricas y Observabilidad

Los siguientes eventos se registran en `metrics_service`:

- ✅ `on_message_sent()` - Mensaje enviado
- ✅ `on_message_delivered()` - Mensaje entregado
- ✅ `on_message_read()` - Mensaje leído
- ✅ `on_message_failed()` - Mensaje fallido

---

## Solución de Problemas

### Error: "META_WA_ACCESS_TOKEN es requerido"

**Solución:** Agrega la variable de entorno en Railway.

### Error: "Firma de webhook inválida"

**Posibles causas:**
- `META_WA_APP_SECRET` incorrecto
- Request no viene de Meta (verifica origen)

**Solución:** Verifica que `META_WA_APP_SECRET` coincida con el de tu app en Meta.

### Error: "Webhook verificado exitosamente" pero no recibe mensajes

**Solución:** Asegúrate de estar suscrito al campo `messages` en la configuración del webhook.

### Mensajes no llegan al cliente

**Solución:** 
1. Verifica que `META_WA_PHONE_NUMBER_ID` sea correcto
2. Revisa logs: `mensaje_enviado = meta_whatsapp_service.send_text_message(...)`
3. Verifica el número del cliente en formato E.164

---

## Límites de Rate de Meta API

- **Mensajes de conversación:** 1000/seg por número
- **Mensajes de template:** Según tier de tu cuenta
- **Webhooks:** Sin límite específico documentado

**Recomendación:** Implementar retry con backoff exponencial si es necesario.

---

## Próximos Pasos (Opcionales)

- [ ] Implementar soporte para audio/video/documentos
- [ ] Crear templates aprobados en Meta para notificaciones
- [ ] Agregar botones interactivos en menús del chatbot
- [ ] Configurar Cloud API desde Facebook Business (si no usas On-Premises)

---

## Contacto / Soporte

Para issues o preguntas técnicas sobre esta migración, contactar al equipo de desarrollo.

