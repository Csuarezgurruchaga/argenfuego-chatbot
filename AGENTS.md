# AGENTS.md (LOCAL)

## Repo
- Servicio backend del chatbot de Argenfuego para WhatsApp Cloud API.
- Stack principal: Python + FastAPI.
- Entrypoint operativo: `main.py`.
- El repo git versionado y publicado a `origin` es este `hybrid-chatbot`; la carpeta hermana `../argenfuego-chatbot` funciona como working copy local no git.
- La especificación de esta v2 se trabajó fuera del repo en `../docs/specs/argenfuego-chatbot/SPEC.md`; la fuente de verdad del flujo `Presupuesto` quedó en `../docs/specs/argenfuego-chatbot/PRESUPUESTO_COPY.md`.

## Módulos principales
- `chatbot/`: reglas conversacionales, modelos y estado en memoria.
- `services/meta_whatsapp_service.py`: integración con WhatsApp Cloud API.
- `services/whatsapp_handoff_service.py`: handoff a agente humano por WhatsApp.
- `services/agent_command_service.py`: comandos del agente (`/done`, `/next`, `/queue`, `/help`, etc.).
- `services/survey_service.py`: encuesta post-handoff.
- `services/email_service.py`: envío de leads por email.
- `services/sheets_service.py`: persistencia de métricas/encuestas en Google Sheets.
- `services/nlu_service.py`: mapeo de intención y extracción de datos.

## Operación observada
- Webhook principal: `GET/POST /webhook/whatsapp`.
- El servicio mantiene conversaciones en memoria con `conversation_manager`.
- Hay cola FIFO de handoffs y cierre por TTL/inactividad.
- El agente humano interactúa también por WhatsApp, no por Slack.
- El trigger de Cloud Build de `argenfuego-chatbot` en GCP despliega desde `main` y no desde `dev`.
- Al 2026-04-07, `origin/main` y `origin/dev` apuntan al mismo commit actual: `7efcb8f` (`docs(chatbot): move local agents ledger into repo`).
- La prueba de tráfico compartido quedó revertida: el dispatcher restauró `972301799307809 -> kleiman-chatbot-api` y el servicio temporal `argenfuego-chatbot-v2` fue eliminado de Cloud Run.
- Al 2026-04-07 quedó bootstrapado el proyecto GCP separado `argenfuego`: Firestore `"(default)"` en `southamerica-west1`, servicio Cloud Run `argenfuego-chatbot`, y tres schedulers internos en `southamerica-east1`.
- También al 2026-04-07, el dispatcher compartido quedó cortado al nuevo `argenfuego-chatbot` del proyecto `argenfuego` para `883679188152252`, mientras `972301799307809` volvió a `kleiman-chatbot-api`.

## Estado funcional actual
- `Presupuesto` v2 usa un submenú guiado con `🧯 Extintores`, `💧 IFCI` y `🧯+💧 Ambos`; `Ambos` y `Otro` caen al fallback legacy secuencial.
- `Extintores` guía tipo de equipo, contacto, servicio (`Equipo nuevo` / `Mantenimiento`) y cantidad, con confirmación final por botones `Sí` / `No`.
- `IFCI` usa captura de contacto + preguntas técnicas específicas + resumen final con menú de corrección propio.
- En las preguntas libres de IFCI, `no` se interpreta como `No sé`; en las preguntas binarias sigue siendo una respuesta válida.
- La descripción del email preserva saltos de línea, útil para el resumen de IFCI.
- Al 2026-04-07, las respuestas de datos de contacto ya no usan OpenAI: salen de forma determinística desde `config/company_profiles.py` para evitar prompt-injection y copy inventado.
- También al 2026-04-07, se eliminó la función de saludo personalizado con OpenAI; el saludo operativo de Eva queda únicamente por la ruta estática de `chatbot/rules.py`.
- También al 2026-04-07, `requirements.txt` dejó de incluir `guardrails-*` porque no tenía usos en el repo y rompía el build limpio de Cloud Run por conflictos de dependencias.
- Al 2026-04-11, `origin/main` quedó en `611ce0e` (`fix(chatbot): unblock lead email post-processing`): el webhook ahora ejecuta el post-procesado del lead también para confirmaciones interactivas `Sí`, y `services/email_service.py` soporta `LEAD_FROM_EMAIL` / `LEAD_TO_EMAIL` por entorno con logs más claros de SES.
- También al 2026-04-11, Cloud Run `argenfuego-chatbot` en el proyecto `argenfuego` tenía ya activa la configuración `DISABLE_LEAD_EMAILS=false` y `LEAD_FROM_EMAIL=no-reply@eventually-ai.com.ar`, pero esa activación se verificó como cambio de configuración sobre la misma imagen previa.
- Al 2026-04-11 quedó desplegado explícitamente `611ce0e` en Cloud Run mediante imagen `southamerica-west1-docker.pkg.dev/argenfuego/argenfuego-chatbot/argenfuego-chatbot@sha256:855edee47435b90faad963e6174902da533a51d230ffd5557b882f851cc54a18`, sirviendo 100% del tráfico en la revisión `argenfuego-chatbot-00010-znv`.
- También al 2026-04-11 quedó implementada localmente la v1 de `Presupuesto` multi-producto guiado: `Extintores` e `IFCI` ahora arman primero una lista `_presupuesto_items`, piden contacto sólo al elegir `Continuar`, muestran `Productos solicitados` en el resumen y separan la corrección final entre `Contacto` y `Productos`.
- Esa implementación multi-producto sigue sin commit al cierre de esta iteración, pero quedó validada localmente con `pytest -q tests/test_presupuesto_flow.py` (`18 passed`) y `pytest -q tests/test_email_and_error_services.py` (`6 passed`).
- También al 2026-04-11 se corrigieron dos riesgos detectados por review antes del commit del feature: elegir `Otro` dentro del builder guiado ya no destruye `_presupuesto_items` ni contacto previo, y los estados nuevos del presupuesto multi-producto quedaron incluidos en la persistencia resumible de `conversation_session_service`.
- La validación local ampliada posterior a esos fixes quedó en `pytest -q tests/test_presupuesto_flow.py tests/test_email_and_error_services.py tests/test_session_checkpoint_service.py` con `31 passed`.
- Al 2026-04-12 quedó cerrada la navegación local `volver/atrás` del presupuesto multi-producto para builder, captura de contacto final y corrección; la review final ya no encontró findings nuevos.
- La validación local final para este feature quedó en `pytest -q tests/test_presupuesto_flow.py tests/test_email_and_error_services.py tests/test_session_checkpoint_service.py` con `34 passed`.
- También al 2026-04-12, el presupuesto multi-producto dejó robusto el picker de borrado: el tope operativo es `10` ítems distintos por solicitud, mientras que extintores idénticos se consolidan sumando cantidad en un único renglón para no consumir filas extra de Meta.
- También al 2026-04-12, el email de `Presupuesto` dejó de renderizar multi-producto como una sola descripción textual: ahora usa una sección HTML `Productos solicitados` con bloques por ítem y sublista clara para IFCI, mientras que consultas no-presupuesto conservan el bloque legacy de descripción.
- También al 2026-04-12, el tope de `10` ítems distintos no bloquea volver a elegir `Extintores`: se permite reingresar para sumar cantidad a un extintor ya existente y recién se rechaza al final si intentaba crear un undécimo ítem distinto; además, si falla SES, la conversación ya no queda trabada en `ENVIANDO` y se finaliza tras notificar el error al cliente.
- También al 2026-04-12, la causa raíz de los fallos de envío a `argenfuego@yahoo.com.ar` fue una desalineación de credenciales AWS: Cloud Run estaba usando la cuenta `729936530864`, mientras que la cuenta SES correcta del negocio es `5537-0972-2930`; se rotaron los secretos `aws-access-key-id` y `aws-secret-access-key` a una access key nueva del usuario `ses-bot-argenfuego` en la cuenta correcta y se desplegó la revisión `argenfuego-chatbot-00014-qb4` para volver a probar el destinatario real.
- Antes de extender otra vez este chatbot, cerrar cambios de flujo en el spec externo y no asumir que el flujo legacy de `hybrid-chatbot` se conserva automáticamente.

## Notas del entorno
- En este workspace, varios `.py` y algunos paquetes presentan `OSError: [Errno 35] Resource deadlock avoided` al leer/importar.
- Para inspección, conviene apoyarse en tests, `__pycache__` y metadatos cuando falle la lectura directa del source.
