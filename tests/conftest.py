import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


ENV_DEFAULTS = {
    "COMPANY_PROFILE": "argenfuego",
    "META_WA_ACCESS_TOKEN": "test_token",
    "META_WA_PHONE_NUMBER_ID": "123456789",
    "META_WA_APP_SECRET": "test_secret",
    "META_WA_VERIFY_TOKEN": "test_verify_token",
    "AGENT_WHATSAPP_NUMBER": "+5491111111111",
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "AWS_EC2_METADATA_DISABLED": "true",
    "ENABLE_ERROR_EMAILS": "false",
    "ENABLE_SHEETS_METRICS": "false",
    "OPENAI_API_KEY": "test-key",
    "ENV": "test",
}

for key, value in ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
def reset_conversation_state():
    from chatbot.states import conversation_manager

    conversation_manager.conversaciones.clear()
    conversation_manager.recently_finalized.clear()
    conversation_manager.handoff_queue.clear()
    conversation_manager.active_handoff = None
    yield
    conversation_manager.conversaciones.clear()
    conversation_manager.recently_finalized.clear()
    conversation_manager.handoff_queue.clear()
    conversation_manager.active_handoff = None


@pytest.fixture
def meta_spy(monkeypatch):
    from chatbot.rules import ChatbotRules
    from services.meta_whatsapp_service import meta_whatsapp_service

    calls = {
        "texts": [],
        "buttons": [],
        "lists": [],
        "stickers": [],
    }

    monkeypatch.setattr(
        meta_whatsapp_service,
        "send_text_message",
        lambda to_number, message: calls["texts"].append({"to": to_number, "message": message}) or True,
    )
    monkeypatch.setattr(
        meta_whatsapp_service,
        "send_interactive_buttons",
        lambda to_number, body_text, buttons, footer_text=None: calls["buttons"].append(
            {
                "to": to_number,
                "body_text": body_text,
                "buttons": buttons,
                "footer_text": footer_text,
            }
        )
        or True,
    )
    monkeypatch.setattr(
        meta_whatsapp_service,
        "send_interactive_list",
        lambda to_number, body_text, button_text, sections, footer_text=None: calls["lists"].append(
            {
                "to": to_number,
                "body_text": body_text,
                "button_text": button_text,
                "sections": sections,
                "footer_text": footer_text,
            }
        )
        or True,
    )
    monkeypatch.setattr(
        meta_whatsapp_service,
        "send_sticker",
        lambda *args, **kwargs: calls["stickers"].append({"args": args, "kwargs": kwargs}) or True,
    )
    monkeypatch.setattr(
        ChatbotRules,
        "_enviar_flujo_saludo_completo",
        staticmethod(lambda numero_telefono, nombre_usuario="": "SALUDO"),
    )
    return calls
