import importlib
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _load_module():
    sys.modules.pop("services.whatsapp_handoff_service", None)
    return importlib.import_module("services.whatsapp_handoff_service")


def test_handoff_template_uses_es_ar_by_default(monkeypatch):
    monkeypatch.delenv("HANDOFF_TEMPLATE_LANG", raising=False)
    module = _load_module()

    calls = []
    monkeypatch.setattr(
        module.meta_whatsapp_service,
        "send_template_message",
        lambda to_number, template_name, language_code, components: calls.append(
            {
                "to_number": to_number,
                "template_name": template_name,
                "language_code": language_code,
                "components": components,
            }
        )
        or True,
    )

    service = module.WhatsAppHandoffService()
    assert service.notify_agent_new_handoff(
        "+5491123456789",
        "Juan Perez",
        "quiero hablar con una persona",
        "quiero hablar con una persona",
    )

    assert calls == [
        {
            "to_number": "+5491111111111",
            "template_name": "handoff",
            "language_code": "es_AR",
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "Juan Perez"},
                        {"type": "text", "text": "+5491123456789"},
                        {"type": "text", "text": "quiero hablar con una persona"},
                    ],
                }
            ],
        }
    ]


def test_handoff_template_language_can_be_overridden(monkeypatch):
    monkeypatch.setenv("HANDOFF_TEMPLATE_LANG", "es_MX")
    module = _load_module()

    calls = []
    monkeypatch.setattr(
        module.meta_whatsapp_service,
        "send_template_message",
        lambda to_number, template_name, language_code, components: calls.append(language_code) or True,
    )

    service = module.WhatsAppHandoffService()
    assert service.notify_agent_new_handoff(
        "+5491123456789",
        "Juan Perez",
        "quiero hablar con una persona",
        "quiero hablar con una persona",
    )

    assert calls == ["es_MX"]
