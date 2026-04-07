# Local Testing

## Setup

1. Crear `.env` a partir de `.env.example`.
2. Instalar dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar tests del flujo nuevo

```bash
pytest tests/test_presupuesto_flow.py
```

## Levantar el webhook local

```bash
uvicorn main:app --reload
```

Luego podés exponer `/webhook/whatsapp` con tu túnel habitual y probar el flujo `Presupuesto` completo sobre `argenfuego-chatbot`.
