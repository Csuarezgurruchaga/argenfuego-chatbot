import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from chatbot.models import EstadoConversacion
from chatbot.rules import ChatbotRules
from chatbot.states import conversation_manager
from main import app, handle_interactive_button


def _build_interactive_payload(reply_id: str, from_number: str, reply_type: str = "list_reply"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5491135722871",
                        "phone_number_id": "123456789",
                    },
                    "contacts": [{
                        "profile": {"name": "Usuario Test"},
                        "wa_id": from_number,
                    }],
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.interactive123",
                        "timestamp": "1234567890",
                        "type": "interactive",
                        "interactive": {
                            "type": reply_type,
                            reply_type: {
                                "id": reply_id,
                                "title": reply_id,
                            },
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _post_signed(client: TestClient, payload: dict):
    body = json.dumps(payload)
    signature_hash = hmac.new(
        b"test_secret",
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhook/whatsapp",
        data=body,
        headers={
            "X-Hub-Signature-256": f"sha256={signature_hash}",
            "Content-Type": "application/json",
        },
    )


@pytest.mark.parametrize("producto_id", ["extintor_pq_5kg", "extintor_pq_10kg"])
def test_extintor_pq_products_show_72h_and_hug_emoji(meta_spy, producto_id):
    numero = "+5491100000001"

    assert ChatbotRules.procesar_mensaje(numero, "hola", "Juan") == "SALUDO"
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.ESPERANDO_OPCION

    assert asyncio.run(handle_interactive_button(numero, "presupuesto", "Juan")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_MENU
    assert meta_spy["buttons"][-1]["footer_text"] == "Elegí una opción para continuar. Ingresá 'hola' para volver a empezar"
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == ["🧯 Extintores", "💧 IFCI", "🧯+💧 Ambos"]

    assert asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Juan")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO

    assert asyncio.run(handle_interactive_button(numero, producto_id, "Juan")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CONFIRMAR_CONTACTO
    assert any("72h" in call["message"] for call in meta_spy["texts"])
    assert any("Hipólito Yrigoyen 2020" in call["message"] for call in meta_spy["texts"])
    assert any("Te esperamos! 🤗" in call["message"] for call in meta_spy["texts"])

    farewell = ChatbotRules.procesar_mensaje(numero, "no")
    assert "Gracias por contactarte con Argenfuego" in farewell
    assert numero not in conversation_manager.conversaciones


def test_extintor_purchase_flow_reaches_confirmation(meta_spy):
    numero = "+5491100000002"

    ChatbotRules.procesar_mensaje(numero, "hola", "Ana")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Ana"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Ana"))
    asyncio.run(handle_interactive_button(numero, "extintor_vehicular_1kg", "Ana"))

    assert asyncio.run(handle_interactive_button(numero, "presupuesto_contacto_si", "Ana")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_SERVICIO

    assert asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Ana")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD
    assert meta_spy["buttons"][-1]["body_text"] == "¿Cuántos equipos necesitás?"
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == ["1", "2", "Otra cantidad"]

    response = asyncio.run(handle_interactive_button(numero, "cantidad_2", "Ana"))
    assert "compra de 2 extintores de 1 kg PQ (ABC)." in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL

    response = ChatbotRules.procesar_mensaje(numero, "cliente@empresa.com")
    assert "¿Cuál es la dirección" in response

    response = ChatbotRules.procesar_mensaje(numero, "Av. Rivadavia 1234, CABA")
    assert "¿En qué horario" in response

    response = ChatbotRules.procesar_mensaje(numero, "9 a 17")
    assert "¿Cuál es la razón social" in response

    response = ChatbotRules.procesar_mensaje(numero, "ACME SA")
    assert "¿Podrías brindarme un CUIT" in response

    response = ChatbotRules.procesar_mensaje(numero, "30-12345678-9")
    assert response == ""
    assert "Resumen de tu solicitud" in meta_spy["buttons"][-1]["body_text"]
    assert "1 kg PQ (ABC)" in meta_spy["buttons"][-1]["body_text"]
    assert [button["id"] for button in meta_spy["buttons"][-1]["buttons"]] == ["si", "no"]
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.CONFIRMANDO

    response = asyncio.run(handle_interactive_button(numero, "si", "Ana"))
    assert response == "⏳ Procesando tu solicitud..."
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.ENVIANDO


def test_ifci_flow_supports_correction_before_sending(meta_spy):
    numero = "+5491100000003"

    ChatbotRules.procesar_mensaje(numero, "hola", "Laura")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Laura"))

    response = asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Laura"))
    assert "¿Cuál es tu email de contacto?" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL

    ChatbotRules.procesar_mensaje(numero, "laura@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Corrientes 1234, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 16")
    ChatbotRules.procesar_mensaje(numero, "saltar")
    response = ChatbotRules.procesar_mensaje(numero, "saltar")

    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_NIVEL
    assert meta_spy["lists"][-1]["button_text"] == "Ver niveles"

    response = asyncio.run(handle_interactive_button(numero, "ifci_nivel_2", "Laura"))
    assert "¿Qué cantidad de hidrantes tiene?" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_HIDRANTES

    response = ChatbotRules.procesar_mensaje(numero, "20")
    assert "¿Qué cantidad de pisos tiene el establecimiento?" in response

    response = ChatbotRules.procesar_mensaje(numero, "4 pisos, sin subsuelo, con estacionamiento")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_DETECTORES

    response = asyncio.run(handle_interactive_button(numero, "ifci_si", "Laura"))
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_PLANO

    response = asyncio.run(handle_interactive_button(numero, "ifci_no_se", "Laura"))
    assert response == ""
    assert "Resumen de tu solicitud" in meta_spy["buttons"][-1]["body_text"]
    assert "🚰 *Cantidad de hidrantes:* 20" in meta_spy["buttons"][-1]["body_text"]
    assert [button["id"] for button in meta_spy["buttons"][-1]["buttons"]] == ["si", "no"]
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.CONFIRMANDO

    response = asyncio.run(handle_interactive_button(numero, "no", "Laura"))
    assert "¿Qué querés modificar?" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_CORRIGIENDO

    response = ChatbotRules.procesar_mensaje(numero, "7")
    assert "¿Qué cantidad de hidrantes tiene?" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_CORRIGIENDO_CAMPO

    response = ChatbotRules.procesar_mensaje(numero, "25")
    assert response == ""
    assert "🚰 *Cantidad de hidrantes:* 25" in meta_spy["buttons"][-1]["body_text"]
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.CONFIRMANDO

    response = asyncio.run(handle_interactive_button(numero, "si", "Laura"))
    assert response == "⏳ Procesando tu solicitud..."
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.ENVIANDO


def test_ifci_skip_optional_field_does_not_prefix_next_prompt_with_blank_line(meta_spy):
    numero = "+5491100000010"

    ChatbotRules.procesar_mensaje(numero, "hola", "Sofi")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Sofi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Sofi"))

    ChatbotRules.procesar_mensaje(numero, "sofi@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Corrientes 1234, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 16")

    response = ChatbotRules.procesar_mensaje(numero, "saltar")
    assert response == "🧾 ¿Podrías brindarme un CUIT? (empresa o personal, según corresponda) (opcional)"
    assert not response.startswith("\n")


def test_ifci_prompts_use_plain_hint_with_blank_line_and_no_can_skip(meta_spy):
    numero = "+5491100000013"

    ChatbotRules.procesar_mensaje(numero, "hola", "Nico")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Nico"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Nico"))

    ChatbotRules.procesar_mensaje(numero, "nico@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Corrientes 1234, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 16")
    ChatbotRules.procesar_mensaje(numero, "saltar")
    ChatbotRules.procesar_mensaje(numero, "saltar")

    response = ChatbotRules.procesar_mensaje(numero, "2")
    assert "\n\nPodés escribir No sé o saltar para pasar a la siguiente pregunta." in response
    assert "`saltar`" not in response
    assert "*" not in response

    response = ChatbotRules.procesar_mensaje(numero, "no")
    assert "¿Qué cantidad de pisos tiene el establecimiento?" in response
    assert conversation_manager.get_datos_temporales(numero, "ifci_hidrantes") == "No sé"

    response = ChatbotRules.procesar_mensaje(numero, "no")
    assert response == ""
    assert conversation_manager.get_datos_temporales(numero, "ifci_establecimiento") == "No sé"
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_DETECTORES
    assert "\n\nPodés escribir No sé o saltar para pasar a la siguiente pregunta." in meta_spy["buttons"][-1]["body_text"]
    assert "`saltar`" not in meta_spy["buttons"][-1]["body_text"]


def test_ifci_level_accepts_numeric_alias_and_stores_full_value(meta_spy):
    numero = "+5491100000012"

    ChatbotRules.procesar_mensaje(numero, "hola", "Tomi")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Tomi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Tomi"))

    ChatbotRules.procesar_mensaje(numero, "tomi@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Corrientes 1234, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 16")
    ChatbotRules.procesar_mensaje(numero, "saltar")
    ChatbotRules.procesar_mensaje(numero, "saltar")

    response = ChatbotRules.procesar_mensaje(numero, "2")
    assert "¿Qué cantidad de hidrantes tiene?" in response
    assert conversation_manager.get_datos_temporales(numero, "ifci_nivel") == "Nivel 2: Cañería húmeda (Aysa)"


def test_presupuesto_local_back_text_respects_internal_navigation(meta_spy):
    numero = "+5491100000004"

    ChatbotRules.procesar_mensaje(numero, "hola", "Mario")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Mario"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Mario"))

    response = ChatbotRules.procesar_mensaje(numero, "volver")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_MENU

    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Mario"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Mario"))

    response = ChatbotRules.procesar_mensaje(numero, "volver al menú anterior")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO


def test_presupuesto_manual_quantity_rejects_invalid_values(meta_spy):
    numero = "+5491100000005"

    ChatbotRules.procesar_mensaje(numero, "hola", "Lu")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Lu"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_10kg", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_contacto_si", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_mantenimiento", "Lu"))
    asyncio.run(handle_interactive_button(numero, "cantidad_otra", "Lu"))

    for invalido in ("2", "100", "3.5", "muchos"):
        response = ChatbotRules.procesar_mensaje(numero, invalido)
        assert response == "Ingresá un número mayor o igual a 3."
        assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD_MANUAL

    response = ChatbotRules.procesar_mensaje(numero, "3")
    assert "mantenimiento de 3 extintores de 10 kg PQ (ABC)." in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL


def test_presupuesto_service_allows_numeric_text_fallback(meta_spy):
    numero = "+5491100000011"

    ChatbotRules.procesar_mensaje(numero, "hola", "Lu")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Lu"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Lu"))

    response = ChatbotRules.procesar_mensaje(numero, "sí")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_SERVICIO

    response = ChatbotRules.procesar_mensaje(numero, "1")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD


def test_webhook_interactive_dispatch_reaches_new_presupuesto_flow(meta_spy):
    client = TestClient(app)
    numero = "5491100000006"

    ChatbotRules.procesar_mensaje(f"+{numero}", "hola", "Webhook")
    assert conversation_manager.get_conversacion(f"+{numero}").estado == EstadoConversacion.ESPERANDO_OPCION

    response = _post_signed(client, _build_interactive_payload("presupuesto", numero, "button_reply"))
    assert response.status_code == 200
    assert conversation_manager.get_conversacion(f"+{numero}").estado == EstadoConversacion.PRESUPUESTO_MENU

    response = _post_signed(client, _build_interactive_payload("presupuesto_extintores", numero, "button_reply"))
    assert response.status_code == 200
    assert conversation_manager.get_conversacion(f"+{numero}").estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO


@pytest.mark.parametrize(
    ("first_choice", "second_choice"),
    [
        ("presupuesto_combo", None),
        ("presupuesto_extintores", "extintor_otro"),
    ],
)
def test_presupuesto_fallback_paths_use_legacy_capture(meta_spy, first_choice, second_choice):
    numero = "+5491199999999"

    ChatbotRules.procesar_mensaje(numero, "hola", "Test")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Test"))

    if second_choice is None:
        response = asyncio.run(handle_interactive_button(numero, first_choice, "Test"))
    else:
        asyncio.run(handle_interactive_button(numero, first_choice, "Test"))
        response = asyncio.run(handle_interactive_button(numero, second_choice, "Test"))

    assert "preparar tu presupuesto de manera precisa" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.RECOLECTANDO_SECUENCIAL
