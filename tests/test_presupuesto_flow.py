import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import main as main_module
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
                        "display_phone_number": "5491139061038",
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
    assert meta_spy["buttons"][-1]["body_text"] == "Seleccioná qué tipo de presupuesto necesitás:"
    assert meta_spy["buttons"][-1]["footer_text"] == "*ingresá 'hola' para volver a empezar."
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == ["🧯 Extintores", "💧 IFCI", "🧯+💧 Ambos"]

    assert asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Juan")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO
    assert [row["title"] for row in meta_spy["lists"][-1]["sections"][0]["rows"]] == [
        "Vehicular (1 kg)",
        "Extintor 5kg PQ (ABC)",
        "Extintor 10kg PQ (ABC)",
        "Extintor 5kg CO2 (BC)",
        "Otro",
    ]

    assert asyncio.run(handle_interactive_button(numero, producto_id, "Juan")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_SERVICIO
    assert any("72h" in call["message"] for call in meta_spy["texts"])
    assert any("Hipólito Yrigoyen 2020" in call["message"] for call in meta_spy["texts"])
    assert any("Te esperamos! 🤗" in call["message"] for call in meta_spy["texts"])
    assert meta_spy["buttons"][-1]["body_text"] == "¿Necesitás un equipo nuevo o mantenimiento?"
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == ["Equipo nuevo", "Mantenimiento"]


def test_extintor_purchase_flow_reaches_confirmation(meta_spy):
    numero = "+5491100000002"

    ChatbotRules.procesar_mensaje(numero, "hola", "Ana")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Ana"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Ana"))
    asyncio.run(handle_interactive_button(numero, "extintor_vehicular_1kg", "Ana"))

    assert asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Ana")) == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD
    assert meta_spy["buttons"][-1]["body_text"] == "¿Cuántos equipos necesitás?"
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == ["1", "2", "Otra cantidad"]

    response = asyncio.run(handle_interactive_button(numero, "cantidad_2", "Ana"))
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert any("Compra de 2 extintores de 1 kg PQ (ABC)." in call["message"] for call in meta_spy["texts"])
    assert meta_spy["buttons"][-1]["body_text"] == "¿Querés agregar otro producto o continuar con tus datos de contacto?"
    assert [button["id"] for button in meta_spy["buttons"][-1]["buttons"]] == [
        "presupuesto_add_extintores",
        "presupuesto_add_ifci",
        "presupuesto_continuar",
    ]
    assert [button["title"] for button in meta_spy["buttons"][-1]["buttons"]] == [
        "Extintores",
        "IFCI",
        "No, continuar",
    ]

    response = asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Ana"))
    assert "¿Cuál es tu email de contacto?" in response
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
    assert "Productos solicitados" in meta_spy["buttons"][-1]["body_text"]
    assert "Compra de 2 extintores de 1 kg PQ (ABC)." in meta_spy["buttons"][-1]["body_text"]
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
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert any("Agregué IFCI a tu solicitud" in call["message"] for call in meta_spy["texts"])
    assert [button["id"] for button in meta_spy["buttons"][-1]["buttons"]] == [
        "presupuesto_add_extintores",
        "presupuesto_continuar",
    ]

    response = asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Laura"))
    assert "¿Cuál es tu email de contacto?" in response

    ChatbotRules.procesar_mensaje(numero, "laura@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Corrientes 1234, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 16")
    ChatbotRules.procesar_mensaje(numero, "saltar")
    response = ChatbotRules.procesar_mensaje(numero, "saltar")

    assert response == ""
    assert "Resumen de tu solicitud" in meta_spy["buttons"][-1]["body_text"]
    assert "Cantidad de hidrantes: 20" in meta_spy["buttons"][-1]["body_text"]
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.CONFIRMANDO

    response = asyncio.run(handle_interactive_button(numero, "no", "Laura"))
    assert response == ""
    assert meta_spy["buttons"][-1]["body_text"] == "¿Qué querés corregir?"
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_CORRIGIENDO_SECCION

    response = asyncio.run(handle_interactive_button(numero, "presupuesto_corregir_contacto", "Laura"))
    assert response == ""
    assert meta_spy["lists"][-1]["button_text"] == "Ver campos"
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_CORRIGIENDO_CONTACTO


def test_presupuesto_multi_item_renders_extintor_and_ifci_in_order(meta_spy):
    numero = "+5491100000017"

    ChatbotRules.procesar_mensaje(numero, "hola", "Vale")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Vale"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Vale"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Vale"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Vale"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Vale"))

    response = asyncio.run(handle_interactive_button(numero, "presupuesto_add_ifci", "Vale"))
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.IFCI_NIVEL

    asyncio.run(handle_interactive_button(numero, "ifci_nivel_1", "Vale"))
    ChatbotRules.procesar_mensaje(numero, "12")
    ChatbotRules.procesar_mensaje(numero, "2 pisos")
    asyncio.run(handle_interactive_button(numero, "ifci_no", "Vale"))
    asyncio.run(handle_interactive_button(numero, "ifci_si", "Vale"))

    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert [button["id"] for button in meta_spy["buttons"][-1]["buttons"]] == [
        "presupuesto_add_extintores",
        "presupuesto_continuar",
    ]

    response = ChatbotRules.procesar_mensaje(numero, "2")
    assert "¿Cuál es tu email de contacto?" in response

    ChatbotRules.procesar_mensaje(numero, "vale@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Siempre Viva 742, CABA")
    ChatbotRules.procesar_mensaje(numero, "9 a 18")
    ChatbotRules.procesar_mensaje(numero, "Empresa Falsa")
    response = ChatbotRules.procesar_mensaje(numero, "20-12345678-9")

    assert response == ""
    resumen = meta_spy["buttons"][-1]["body_text"]
    extintor_index = resumen.index("Compra de 1 extintor de 5 kg PQ (ABC).")
    ifci_index = resumen.index("Consulta IFCI (Hidrantes)")
    assert extintor_index < ifci_index
    assert "Cantidad de hidrantes: 12" in resumen


def test_extintor_info_message_only_shows_once_when_adding_more(meta_spy):
    numero = "+5491100000018"

    ChatbotRules.procesar_mensaje(numero, "hola", "Luz")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Luz"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Luz"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Luz"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Luz"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Luz"))

    asyncio.run(handle_interactive_button(numero, "presupuesto_add_extintores", "Luz"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_10kg", "Luz"))

    info_messages = [call["message"] for call in meta_spy["texts"] if "72h" in call["message"]]
    assert len(info_messages) == 1


def test_presupuesto_otro_does_not_reset_guided_request_in_progress(meta_spy):
    numero = "+5491100000020"

    ChatbotRules.procesar_mensaje(numero, "hola", "Noa")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Noa"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Noa"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Noa"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Noa"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Noa"))

    asyncio.run(handle_interactive_button(numero, "presupuesto_add_extintores", "Noa"))
    response = asyncio.run(handle_interactive_button(numero, "extintor_otro", "Noa"))

    assert "no puedo sumar la opción `Otro`" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_TIPO
    assert len(conversation_manager.get_conversacion(numero).datos_temporales["_presupuesto_items"]) == 1
    assert conversation_manager.get_conversacion(numero).datos_temporales["_presupuesto_items"][0]["summary"] == "Compra de 1 extintor de 5 kg PQ (ABC)."


def test_presupuesto_volver_from_extintor_type_returns_to_add_more_without_reset(meta_spy):
    numero = "+5491100000022"

    ChatbotRules.procesar_mensaje(numero, "hola", "Paz")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Paz"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Paz"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Paz"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Paz"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Paz"))

    asyncio.run(handle_interactive_button(numero, "presupuesto_add_extintores", "Paz"))
    response = ChatbotRules.procesar_mensaje(numero, "volver")

    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert len(conversation_manager.get_conversacion(numero).datos_temporales["_presupuesto_items"]) == 1
    assert meta_spy["buttons"][-1]["body_text"] == "¿Querés agregar otro producto o continuar con tus datos de contacto?"


def test_presupuesto_product_menu_numeric_fallback_tracks_visible_rows(meta_spy):
    numero = "+5491100000019"

    ChatbotRules.procesar_mensaje(numero, "hola", "Mica")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Mica"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Mica"))
    asyncio.run(handle_interactive_button(numero, "ifci_nivel_1", "Mica"))
    ChatbotRules.procesar_mensaje(numero, "8")
    ChatbotRules.procesar_mensaje(numero, "PB y 1 piso")
    asyncio.run(handle_interactive_button(numero, "ifci_no", "Mica"))
    asyncio.run(handle_interactive_button(numero, "ifci_no", "Mica"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Mica"))
    ChatbotRules.procesar_mensaje(numero, "mica@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Libertador 1000, CABA")
    ChatbotRules.procesar_mensaje(numero, "10 a 17")
    ChatbotRules.procesar_mensaje(numero, "Mica SA")
    ChatbotRules.procesar_mensaje(numero, "27-12345678-9")

    asyncio.run(handle_interactive_button(numero, "no", "Mica"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_corregir_productos", "Mica"))

    response = ChatbotRules.procesar_mensaje(numero, "2")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_PRODUCTOS_BORRAR
    assert meta_spy["lists"][-1]["button_text"] == "Ver productos"
    assert [row["title"] for row in meta_spy["lists"][-1]["sections"][0]["rows"]] == ["1"]
    assert "1. Consulta IFCI (Hidrantes)" in meta_spy["texts"][-1]["message"]


def test_presupuesto_delete_picker_sends_full_numbered_context_before_list(meta_spy):
    numero = "+5491100000025"

    ChatbotRules.procesar_mensaje(numero, "hola", "Lola")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Lola"))
    asyncio.run(handle_interactive_button(numero, "extintor_vehicular_1kg", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Lola"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_add_extintores", "Lola"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_mantenimiento", "Lola"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Lola"))
    ChatbotRules.procesar_mensaje(numero, "lola@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Directorio 100, CABA")
    ChatbotRules.procesar_mensaje(numero, "9 a 18")
    ChatbotRules.procesar_mensaje(numero, "Lola SA")
    ChatbotRules.procesar_mensaje(numero, "27-12345678-9")

    asyncio.run(handle_interactive_button(numero, "no", "Lola"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_corregir_productos", "Lola"))
    response = ChatbotRules.procesar_mensaje(numero, "3")

    assert response == ""
    assert "1. Compra de 1 extintor de 1 kg PQ (ABC)." in meta_spy["texts"][-1]["message"]
    assert "2. Mantenimiento de 1 extintor de 5 kg PQ (ABC)." in meta_spy["texts"][-1]["message"]
    assert [row["title"] for row in meta_spy["lists"][-1]["sections"][0]["rows"]] == ["1", "2"]
    assert meta_spy["lists"][-1]["footer_text"] == "Seleccioná un número"


def test_presupuesto_contact_correction_accepts_visible_text(meta_spy):
    numero = "+5491100000021"

    ChatbotRules.procesar_mensaje(numero, "hola", "Jo")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Jo"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Jo"))
    asyncio.run(handle_interactive_button(numero, "extintor_vehicular_1kg", "Jo"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Jo"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Jo"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Jo"))
    ChatbotRules.procesar_mensaje(numero, "jo@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Cabildo 123, CABA")
    ChatbotRules.procesar_mensaje(numero, "9 a 17")
    ChatbotRules.procesar_mensaje(numero, "Jo SA")
    ChatbotRules.procesar_mensaje(numero, "20-12345678-9")

    asyncio.run(handle_interactive_button(numero, "no", "Jo"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_corregir_contacto", "Jo"))

    response = ChatbotRules.procesar_mensaje(numero, "email")
    assert "nuevo valor" in response
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.CORRIGIENDO_CAMPO
    assert conversation_manager.get_conversacion(numero).datos_temporales["_campo_a_corregir"] == "email"


def test_presupuesto_back_during_contact_collection_returns_to_add_more(meta_spy):
    numero = "+5491100000023"

    ChatbotRules.procesar_mensaje(numero, "hola", "Ivi")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Ivi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Ivi"))
    asyncio.run(handle_interactive_button(numero, "extintor_vehicular_1kg", "Ivi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Ivi"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Ivi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Ivi"))

    response = ChatbotRules.procesar_mensaje(numero, "ivi@empresa.com")
    assert "¿Cuál es la dirección" in response

    response = ChatbotRules.procesar_mensaje(numero, "volver")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert conversation_manager.get_conversacion(numero).datos_temporales["email"] == "ivi@empresa.com"
    assert len(conversation_manager.get_conversacion(numero).datos_temporales["_presupuesto_items"]) == 1
    assert meta_spy["buttons"][-1]["body_text"] == "¿Querés agregar otro producto o continuar con tus datos de contacto?"


def test_presupuesto_back_from_product_delete_returns_to_product_menu(meta_spy):
    numero = "+5491100000024"

    ChatbotRules.procesar_mensaje(numero, "hola", "Romi")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Romi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Romi"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Romi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_compra", "Romi"))
    asyncio.run(handle_interactive_button(numero, "cantidad_1", "Romi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_continuar", "Romi"))
    ChatbotRules.procesar_mensaje(numero, "romi@empresa.com")
    ChatbotRules.procesar_mensaje(numero, "Av. Santa Fe 1000, CABA")
    ChatbotRules.procesar_mensaje(numero, "9 a 18")
    ChatbotRules.procesar_mensaje(numero, "Romi SRL")
    ChatbotRules.procesar_mensaje(numero, "27-12345678-9")

    asyncio.run(handle_interactive_button(numero, "no", "Romi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_corregir_productos", "Romi"))
    ChatbotRules.procesar_mensaje(numero, "3")
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_PRODUCTOS_BORRAR

    response = ChatbotRules.procesar_mensaje(numero, "volver")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_PRODUCTOS_CORRIGIENDO
    assert len(conversation_manager.get_conversacion(numero).datos_temporales["_presupuesto_items"]) == 1
    assert meta_spy["lists"][-1]["button_text"] == "Ver opciones"


def test_ifci_skip_optional_field_does_not_prefix_next_prompt_with_blank_line(meta_spy):
    numero = "+5491100000010"

    ChatbotRules.procesar_mensaje(numero, "hola", "Sofi")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Sofi"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Sofi"))

    response = ChatbotRules.procesar_mensaje(numero, "2")
    assert "¿Qué cantidad de hidrantes tiene?" in response
    assert not response.startswith("\n")


def test_ifci_prompts_use_plain_hint_with_blank_line_and_no_can_skip(meta_spy):
    numero = "+5491100000013"

    ChatbotRules.procesar_mensaje(numero, "hola", "Nico")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Nico"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_ifci", "Nico"))

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


def test_presupuesto_manual_quantity_rejects_invalid_values(meta_spy):
    numero = "+5491100000005"

    ChatbotRules.procesar_mensaje(numero, "hola", "Lu")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Lu"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_10kg", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_mantenimiento", "Lu"))
    asyncio.run(handle_interactive_button(numero, "cantidad_otra", "Lu"))

    for invalido in ("2", "100", "3.5", "muchos"):
        response = ChatbotRules.procesar_mensaje(numero, invalido)
        assert response == "Ingresá un número mayor o igual a 3."
        assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_EXTINTOR_CANTIDAD_MANUAL

    response = ChatbotRules.procesar_mensaje(numero, "3")
    assert response == ""
    assert conversation_manager.get_conversacion(numero).estado == EstadoConversacion.PRESUPUESTO_AGREGAR_OTRO
    assert any("Mantenimiento de 3 extintores de 10 kg PQ (ABC)." in call["message"] for call in meta_spy["texts"])


def test_presupuesto_service_allows_numeric_text_fallback(meta_spy):
    numero = "+5491100000011"

    ChatbotRules.procesar_mensaje(numero, "hola", "Lu")
    asyncio.run(handle_interactive_button(numero, "presupuesto", "Lu"))
    asyncio.run(handle_interactive_button(numero, "presupuesto_extintores", "Lu"))
    asyncio.run(handle_interactive_button(numero, "extintor_pq_5kg", "Lu"))

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


def test_webhook_interactive_confirmacion_dispara_post_procesado(meta_spy, monkeypatch):
    numero = "5491100000015"
    numero_con_prefijo = f"+{numero}"
    client = TestClient(app)
    lead_calls = []

    monkeypatch.setattr(
        main_module.email_service,
        "enviar_lead_email",
        lambda conversacion: lead_calls.append(conversacion.numero_telefono) or True,
    )
    monkeypatch.setattr(main_module.metrics_service, "on_lead_sent", lambda: None)

    ChatbotRules.procesar_mensaje(numero_con_prefijo, "hola", "Ana")
    asyncio.run(handle_interactive_button(numero_con_prefijo, "presupuesto", "Ana"))
    asyncio.run(handle_interactive_button(numero_con_prefijo, "presupuesto_extintores", "Ana"))
    asyncio.run(handle_interactive_button(numero_con_prefijo, "extintor_vehicular_1kg", "Ana"))
    asyncio.run(handle_interactive_button(numero_con_prefijo, "presupuesto_compra", "Ana"))
    asyncio.run(handle_interactive_button(numero_con_prefijo, "cantidad_2", "Ana"))
    asyncio.run(handle_interactive_button(numero_con_prefijo, "presupuesto_continuar", "Ana"))
    ChatbotRules.procesar_mensaje(numero_con_prefijo, "ana@empresa.com")
    ChatbotRules.procesar_mensaje(numero_con_prefijo, "Av. Rivadavia 1234, CABA")
    ChatbotRules.procesar_mensaje(numero_con_prefijo, "9 a 17")
    ChatbotRules.procesar_mensaje(numero_con_prefijo, "ACME SA")
    ChatbotRules.procesar_mensaje(numero_con_prefijo, "30-12345678-9")

    assert conversation_manager.get_conversacion(numero_con_prefijo).estado == EstadoConversacion.CONFIRMANDO

    response = _post_signed(client, _build_interactive_payload("si", numero, "button_reply"))

    assert response.status_code == 200
    assert lead_calls == [numero_con_prefijo]
    assert any("Procesando tu solicitud" in call["message"] for call in meta_spy["texts"])
    assert any("Tu solicitud ha sido enviada exitosamente" in call["message"] for call in meta_spy["texts"])
    assert numero_con_prefijo not in conversation_manager.conversaciones


def test_webhook_interactive_finalizar_chat_no_revive_conversacion(meta_spy):
    numero = "5491100000016"
    numero_con_prefijo = f"+{numero}"
    client = TestClient(app)

    ChatbotRules.procesar_mensaje(numero_con_prefijo, "hola", "Ana")
    assert numero_con_prefijo in conversation_manager.conversaciones

    response = _post_signed(client, _build_interactive_payload("finalizar_chat", numero, "button_reply"))

    assert response.status_code == 200
    assert any("Gracias por contactarnos" in call["message"] for call in meta_spy["texts"])
    assert numero_con_prefijo not in conversation_manager.conversaciones


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
