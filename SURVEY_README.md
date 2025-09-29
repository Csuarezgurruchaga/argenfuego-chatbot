# Encuesta de Satisfacción Post-Handoff

## Descripción

Sistema de encuesta de satisfacción que se activa automáticamente cuando un agente humano finaliza una conversación usando los comandos `/r` o `/resuelto`. La encuesta evalúa la calidad de atención del agente y la experiencia del cliente.

## Configuración

### Variables de Entorno

```bash
# Habilitar/deshabilitar encuestas
SUMMARY=true

# Nombre de la hoja en Google Sheets (opcional)
SHEETS_SURVEY_SHEET_NAME=ENCUESTA_RESULTADOS
```

### Google Sheets

Crear una hoja llamada `ENCUESTA_RESULTADOS` con las siguientes columnas:

| Columna | Nombre | Descripción |
|---------|--------|-------------|
| A | `fecha` | Fecha y hora de la encuesta (YYYY-MM-DD HH:MM:SS) |
| B | `telefono_masked` | Número de teléfono enmascarado (***1234) |
| C | `resolvio_problema` | Respuesta a "¿Pudiste resolver el motivo?" |
| D | `amabilidad` | Respuesta a "¿Cómo calificarías la amabilidad?" |
| E | `volveria_contactar` | Respuesta a "¿Volverías a utilizar esta vía?" |
| F | `fecha_handoff` | Fecha y hora del handoff (YYYY-MM-DD HH:MM:SS) |

## Funcionamiento

### Activación
- Se activa cuando el agente escribe `/r`, `/resuelto`, `ok`, `listo`, etc.
- Solo funciona si `SUMMARY=true` está configurado
- Si está deshabilitado, funciona el flujo normal de resolución

### Flujo de la Encuesta

1. **Primera Pregunta**
   ```
   Con el fin de seguir mejorando la calidad de nuestra atención, le proponemos responder la siguiente encuesta:

   ¿Pudiste resolver el motivo por el cuál te comunicaste?
   1️⃣ Sí
   2️⃣ Parcialmente  
   3️⃣ No

   Responde con el número (1, 2 o 3)
   ```

2. **Segunda Pregunta** (después de responder la primera)
   ```
   ¿Cómo calificarías la amabilidad en la atención?
   1️⃣ Muy buena
   2️⃣ Regular
   3️⃣ Mala

   Responde con el número (1, 2 o 3)
   ```

3. **Tercera Pregunta** (después de responder la segunda)
   ```
   ¿Volverías a utilizar esta vía de contacto?
   1️⃣ Sí
   2️⃣ No

   Responde con el número (1, 2 o 3)
   ```

4. **Finalización**
   ```
   ¡Gracias por tu tiempo! Tus respuestas nos ayudan a mejorar nuestro servicio. ✅
   ```

### Procesamiento de Respuestas

El sistema acepta múltiples formatos de respuesta:

- **Números**: `1`, `2`, `3`
- **Emojis**: `1️⃣`, `2️⃣`, `3️⃣`
- **Texto**: `sí`, `si`, `parcialmente`, `no`, `muy buena`, `regular`, `mala`

### Estados de Conversación

- **`ENCUESTA_SATISFACCION`**: Estado activo durante la encuesta
- **`survey_question_number`**: Número de pregunta actual (1, 2, 3)
- **`survey_responses`**: Diccionario con las respuestas guardadas

## Análisis de Datos

### Métricas Clave

1. **Tasa de Resolución**
   - `Sí` / Total de respuestas
   - Indica efectividad del agente

2. **Calidad de Atención**
   - `Muy buena` / Total de respuestas
   - Indica satisfacción con el servicio

3. **Retención de Clientes**
   - `Sí` / Total de respuestas (pregunta 3)
   - Indica probabilidad de reutilización

### Interpretación de Resultados

- **Alta satisfacción**: >80% "Muy buena" en amabilidad
- **Baja resolución**: >30% "No" en resolución de problemas
- **Riesgo de abandono**: >20% "No" en volvería a contactar

## Implementación Técnica

### Archivos Principales

- **`services/survey_service.py`**: Lógica principal de la encuesta
- **`services/whatsapp_handoff_service.py`**: Integración con handoff
- **`main.py`**: Manejo de respuestas en webhook
- **`services/sheets_service.py`**: Almacenamiento en Google Sheets

### Flujo de Datos

1. Agente escribe `/r` → `send_resolution_question_to_client()`
2. Verifica `SUMMARY=true` → `survey_service.send_survey()`
3. Cliente responde → `survey_service.process_survey_response()`
4. Procesa respuesta → Envía siguiente pregunta o finaliza
5. Guarda resultados → `sheets_service.append_row('survey', data)`

## Troubleshooting

### Problemas Comunes

1. **Encuesta no se activa**
   - Verificar `SUMMARY=true` en variables de entorno
   - Verificar que el agente use comandos válidos (`/r`, `ok`, etc.)

2. **Respuestas no se procesan**
   - Verificar que el cliente responda con formato válido
   - Revisar logs para errores de procesamiento

3. **Datos no se guardan en Sheets**
   - Verificar configuración de Google Sheets
   - Verificar que la hoja `ENCUESTA_RESULTADOS` exista
   - Revisar permisos del service account

### Logs Importantes

```
✅ Encuesta enviada al cliente +5491123456789
✅ Resultados de encuesta guardados para +5491123456789
✅ Encuesta completada y conversación finalizada para +5491123456789
```

## Mejores Prácticas

1. **Configuración**
   - Habilitar solo en producción cuando esté listo
   - Configurar hoja de Google Sheets antes de activar

2. **Monitoreo**
   - Revisar regularmente los resultados en Google Sheets
   - Monitorear logs para errores de procesamiento

3. **Análisis**
   - Analizar tendencias semanales/mensuales
   - Identificar patrones en respuestas negativas
   - Usar datos para mejorar entrenamiento de agentes

## Variables de Entorno Completas

```bash
# Encuesta de satisfacción
SUMMARY=true
SHEETS_SURVEY_SHEET_NAME=ENCUESTA_RESULTADOS

# Google Sheets (requerido)
ENABLE_SHEETS_METRICS=true
SHEETS_METRICS_SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_JSON=your_service_account_json

# WhatsApp Handoff (requerido)
AGENT_WHATSAPP_NUMBER=+5491135722871
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
```
