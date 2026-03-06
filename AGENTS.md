# AGENTS.md (LOCAL)

## Repo
- Servicio backend del chatbot de Argenfuego para WhatsApp Cloud API.
- Stack principal: Python + FastAPI.
- Entrypoint operativo: `main.py`.

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

## Notas del entorno
- En este workspace, varios `.py` y algunos paquetes presentan `OSError: [Errno 35] Resource deadlock avoided` al leer/importar.
- Para inspección, conviene apoyarse en tests, `__pycache__` y metadatos cuando falle la lectura directa del source.
