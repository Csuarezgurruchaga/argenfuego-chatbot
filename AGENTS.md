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

## Estado funcional actual
- `Presupuesto` v2 usa un submenú guiado con `🧯 Extintores`, `💧 IFCI` y `🧯+💧 Ambos`; `Ambos` y `Otro` caen al fallback legacy secuencial.
- `Extintores` guía tipo de equipo, contacto, servicio (`Equipo nuevo` / `Mantenimiento`) y cantidad, con confirmación final por botones `Sí` / `No`.
- `IFCI` usa captura de contacto + preguntas técnicas específicas + resumen final con menú de corrección propio.
- En las preguntas libres de IFCI, `no` se interpreta como `No sé`; en las preguntas binarias sigue siendo una respuesta válida.
- La descripción del email preserva saltos de línea, útil para el resumen de IFCI.
- Al 2026-04-07, las respuestas de datos de contacto ya no usan OpenAI: salen de forma determinística desde `config/company_profiles.py` para evitar prompt-injection y copy inventado.
- También al 2026-04-07, se eliminó la función de saludo personalizado con OpenAI; el saludo operativo de Eva queda únicamente por la ruta estática de `chatbot/rules.py`.
- Antes de extender otra vez este chatbot, cerrar cambios de flujo en el spec externo y no asumir que el flujo legacy de `hybrid-chatbot` se conserva automáticamente.

## Notas del entorno
- En este workspace, varios `.py` y algunos paquetes presentan `OSError: [Errno 35] Resource deadlock avoided` al leer/importar.
- Para inspección, conviene apoyarse en tests, `__pycache__` y metadatos cuando falle la lectura directa del source.
