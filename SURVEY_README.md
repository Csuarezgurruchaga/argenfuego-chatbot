# Encuesta de Satisfacción Post-Handoff

## Descripción

Sistema de encuesta de satisfacción con **opt-in explícito** que se activa cuando un agente humano finaliza una conversación usando el comando `/done`. El cliente puede elegir responder la encuesta o declinarla, garantizando una experiencia respetuosa y no invasiva.

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

| Columna | Nombre | Descripción | Valores |
|---------|--------|-------------|---------|
| A | `fecha` | Fecha y hora de finalización de encuesta | `2025-01-15 14:30:22` |
| B | `telefono_masked` | Número de teléfono enmascarado | `***1234` |
| C | `resolvio_problema` | Respuesta a "¿Pudiste resolver el motivo?" | `Sí` / `Parcialmente` / `No` |
| D | `amabilidad` | Respuesta a "¿Cómo calificarías la amabilidad?" | `Muy buena` / `Regular` / `Mala` |
| E | `volveria_contactar` | Respuesta a "¿Volverías a utilizar esta vía?" | `Sí` / `No` |
| F | `duracion_handoff_minutos` | Duración del handoff en minutos | `15` (número) |
| G | `survey_offered` | Si se ofreció la encuesta al cliente | `true` / `false` |
| H | `survey_accepted` | Decisión del cliente sobre la encuesta | `accepted` / `declined` / `timeout` |
| I | `nombre_cliente` | Nombre del cliente (nombre + inicial) | `Juan P.` |

**Nota importante**: Esta estructura reemplaza la columna anterior `fecha_handoff` con `duracion_handoff_minutos` para evitar redundancia y facilitar análisis directo.

## Funcionamiento

### Activación
- Se activa cuando el agente escribe `/done` (o aliases: `/d`, `/resuelto`, `/r`, `/finalizar`, `/cerrar`)
- Solo funciona si `SUMMARY=true` está configurado
- Si está deshabilitado, cierra la conversación inmediatamente sin encuesta

### Flujo Completo con Opt-in

#### 1. **Oferta de Encuesta** (Cliente elige)
```
¡Gracias por tu consulta, [Nombre]! 🙏

¿Nos ayudas con 3 preguntas rápidas? (toma menos de 1 minuto)
Tu opinión es muy valiosa para mejorar nuestro servicio.

1️⃣ Sí, con gusto
2️⃣ No, gracias

Si no respondes en 2 minutos, cerraremos la conversación automáticamente.
```

**Cliente responde:**
- **"1"** o keywords aceptación (`sí`, `si`, `yes`, `ok`, `dale`, `acepto`) → Inicia encuesta
- **"2"** o keywords rechazo (`no`, `no gracias`, `no quiero`, `paso`) → Cierra conversación con agradecimiento
- **Timeout 2 minutos** → Cierra conversación silenciosamente

#### 2. **Primera Pregunta** (si acepta)
```
¡Perfecto! Comencemos:

¿Pudiste resolver el motivo por el cuál te comunicaste?

1️⃣ Sí
2️⃣ Parcialmente
3️⃣ No
```

#### 3. **Segunda Pregunta**
```
¿Cómo calificarías la amabilidad en la atención?

1️⃣ Muy buena
2️⃣ Regular
3️⃣ Mala
```

#### 4. **Tercera Pregunta**
```
¿Volverías a utilizar esta vía de contacto?

1️⃣ Sí
2️⃣ No
```

#### 5. **Finalización**
```
¡Gracias por tu tiempo! Tus respuestas nos ayudan a mejorar nuestro servicio. ✅
```
[Conversación cerrada automáticamente]

### Procesamiento de Respuestas

El sistema acepta múltiples formatos de respuesta:

- **Números**: `1`, `2`, `3`
- **Emojis**: `1️⃣`, `2️⃣`, `3️⃣`
- **Texto**: `sí`, `si`, `parcialmente`, `no`, `muy buena`, `regular`, `mala`

### Estados de Conversación

- **`ESPERANDO_RESPUESTA_ENCUESTA`**: Esperando decisión del cliente (acepta/rechaza encuesta) - timeout 2 minutos
- **`ENCUESTA_SATISFACCION`**: Estado activo durante la encuesta - timeout 15 minutos por pregunta
- **`survey_question_number`**: Número de pregunta actual (1, 2, 3)
- **`survey_responses`**: Diccionario con las respuestas guardadas
- **`survey_offered`**: Indica si se ofreció la encuesta
- **`survey_accepted`**: True (aceptó), False (rechazó), None (timeout)

## Análisis de Datos

### Métricas Clave

1. **Opt-in Rate** (Nueva métrica)
   - `accepted` / (`accepted` + `declined` + `timeout`)
   - Indica engagement y disposición del cliente
   - Meta sugerida: >60%

2. **Tasa de Resolución**
   - `Sí` / Total de respuestas completadas
   - Indica efectividad del agente
   - Correlacionar con `duracion_handoff_minutos`

3. **Calidad de Atención**
   - `Muy buena` / Total de respuestas
   - Indica satisfacción con el servicio

4. **Retención de Clientes**
   - `Sí` / Total de respuestas (pregunta 3)
   - Indica probabilidad de reutilización

5. **Eficiencia vs Satisfacción** (Nueva métrica)
   - Analizar `duracion_handoff_minutos` vs `amabilidad`
   - Identificar si handoffs más largos tienen mejor/peor satisfacción

### Interpretación de Resultados

- **Alta satisfacción**: >80% "Muy buena" en amabilidad
- **Baja resolución**: >30% "No" en resolución de problemas
- **Riesgo de abandono**: >20% "No" en volvería a contactar
- **Buen opt-in rate**: >60% accepted
- **Handoff eficiente**: Promedio <20 minutos con satisfacción "Muy buena"

## Implementación Técnica

### Archivos Principales

- **`services/survey_service.py`**: Lógica principal de la encuesta
- **`services/whatsapp_handoff_service.py`**: Integración con handoff
- **`main.py`**: Manejo de respuestas en webhook
- **`services/sheets_service.py`**: Almacenamiento en Google Sheets

### Flujo de Datos

1. Agente escribe `/done` → `agent_command_service.execute_done_command()`
2. Verifica `SUMMARY=true` → Envía mensaje opt-in/opt-out al cliente
3. Cambia estado a `ESPERANDO_RESPUESTA_ENCUESTA` (timeout 2 min)
4. Cliente responde:
   - **Acepta** → `survey_service.send_survey()` → Estado `ENCUESTA_SATISFACCION`
   - **Rechaza** → Cierra conversación con mensaje de agradecimiento
   - **Timeout** → Cierra conversación silenciosamente
5. Si acepta: Cliente responde preguntas → `survey_service.process_survey_response()`
6. Procesa respuesta → Envía siguiente pregunta o finaliza
7. Guarda resultados → `sheets_service.append_row('survey', data)`
8. Cierra conversación y activa siguiente en cola

## Troubleshooting

### Problemas Comunes

1. **Encuesta no se ofrece al cliente**
   - Verificar `SUMMARY=true` en variables de entorno
   - Verificar que el agente use `/done` (o aliases válidos)
   - Revisar logs: debe aparecer "✅ Oferta de encuesta enviada"

2. **Cliente no puede aceptar/rechazar**
   - Verificar que esté en estado `ESPERANDO_RESPUESTA_ENCUESTA`
   - Verificar keywords de aceptación/rechazo en logs
   - Mensaje debe incluir "1️⃣ Sí, con gusto" y "2️⃣ No, gracias"

3. **Timeout muy rápido o muy lento**
   - Timeout de oferta: 2 minutos (en `main.py` TTL sweep)
   - Timeout de preguntas: 15 minutos por pregunta
   - Ajustar según necesidad en código

4. **Conversación no cierra después de rechazar**
   - Verificar que `close_active_handoff()` se llame correctamente
   - Revisar logs: debe aparecer "✅ Cliente rechazó encuesta"
   - Verificar que se active siguiente conversación en cola

5. **Datos no se guardan en Sheets**
   - Verificar configuración de Google Sheets
   - Verificar que la hoja `ENCUESTA_RESULTADOS` exista
   - Revisar permisos del service account

### Logs Importantes

```
✅ Oferta de encuesta enviada al cliente +5491123456789
✅ Cliente +5491123456789 aceptó encuesta, primera pregunta enviada
✅ Cliente +5491123456789 rechazó encuesta, conversación cerrada
⏱️ Timeout de oferta de encuesta para +5491123456789
✅ Encuesta enviada al cliente +5491123456789
✅ Resultados de encuesta guardados para +5491123456789
✅ Encuesta completada y conversación finalizada para +5491123456789
```

## Mejores Prácticas

1. **Configuración**
   - Habilitar solo en producción cuando esté listo
   - Configurar hoja de Google Sheets antes de activar
   - Testear flujo completo: aceptación, rechazo y timeout

2. **Monitoreo**
   - Revisar regularmente los resultados en Google Sheets
   - Monitorear logs para errores de procesamiento
   - Trackear tasa de aceptación (opt-in rate) como indicador de engagement
   - Analizar `survey_accepted` field: True/False/None para entender comportamiento

3. **Análisis**
   - Analizar tendencias semanales/mensuales
   - Identificar patrones en respuestas negativas
   - Usar datos para mejorar entrenamiento de agentes
   - Comparar tasas de aceptación por día/hora para optimizar timing

4. **UX/Messaging**
   - Mantener mensaje de oferta conciso (<100 caracteres)
   - Enfatizar brevedad ("menos de 1 minuto", "3 preguntas")
   - Personalizar con nombre del cliente cuando sea posible
   - No ser insistente: respetar decisión de rechazo

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
