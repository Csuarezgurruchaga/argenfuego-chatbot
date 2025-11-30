"""
Tests para el webhook de WhatsApp Cloud API (Meta)
"""
import pytest
import json
import hmac
import hashlib
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os


# Mock de las variables de entorno antes de importar
@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Mock de variables de entorno para tests"""
    monkeypatch.setenv("META_WA_ACCESS_TOKEN", "test_token_123")
    monkeypatch.setenv("META_WA_PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("META_WA_APP_SECRET", "test_secret")
    monkeypatch.setenv("META_WA_VERIFY_TOKEN", "test_verify_token")
    monkeypatch.setenv("AGENT_WHATSAPP_NUMBER", "+5491135722871")


def _build_message_payload(text_body: str, from_number: str = "5491198765432"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5491135722871",
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {"name": "Usuario Test"},
                        "wa_id": from_number
                    }],
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.test123",
                        "timestamp": "1234567890",
                        "type": "text",
                        "text": {"body": text_body}
                    }]
                },
                "field": "messages"
            }]
        }]
    }


def _post_signed(client: TestClient, payload: dict):
    body = json.dumps(payload)
    secret = "test_secret"
    signature_hash = hmac.new(
        secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    signature = f"sha256={signature_hash}"
    return client.post(
        "/webhook/whatsapp",
        data=body,
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json"
        }
    )


def test_webhook_verification_success():
    """Test de verificación GET del webhook - caso exitoso"""
    from main import app
    
    client = TestClient(app)
    
    # Simular request GET de verificación de Meta
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "challenge_12345"
        }
    )
    
    assert response.status_code == 200
    assert response.text == "challenge_12345"


def test_webhook_verification_invalid_token():
    """Test de verificación GET con token inválido"""
    from main import app
    
    client = TestClient(app)
    
    # Token incorrecto
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "challenge_12345"
        }
    )
    
    assert response.status_code == 403


def test_webhook_verification_invalid_mode():
    """Test de verificación GET con mode inválido"""
    from main import app
    
    client = TestClient(app)
    
    # Mode incorrecto
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "unsubscribe",  # Debería ser "subscribe"
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "challenge_12345"
        }
    )
    
    assert response.status_code == 403


def test_webhook_message_received_valid_signature():
    """Test de recepción de mensaje POST con firma válida"""
    from main import app
    
    client = TestClient(app)
    
    # Payload de ejemplo de Meta
    webhook_data = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5491135722871",
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {
                            "name": "Usuario Test"
                        },
                        "wa_id": "5491198765432"
                    }],
                    "messages": [{
                        "from": "5491198765432",
                        "id": "wamid.test123",
                        "timestamp": "1234567890",
                        "type": "text",
                        "text": {
                            "body": "Hola"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    
    # Convertir a JSON string
    body = json.dumps(webhook_data)
    
    # Generar firma HMAC válida
    secret = "test_secret"
    signature_hash = hmac.new(
        secret.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    signature = f"sha256={signature_hash}"
    
    # Enviar request con firma
    with patch('services.meta_whatsapp_service.meta_whatsapp_service.send_text_message') as mock_send:
        mock_send.return_value = True
        
        response = client.post(
            "/webhook/whatsapp",
            data=body,
            headers={
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json"
            }
        )
    
    assert response.status_code == 200


def test_webhook_message_received_invalid_signature():
    """Test de recepción de mensaje POST con firma inválida"""
    from main import app
    
    client = TestClient(app)
    
    webhook_data = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": "123456789"
                    },
                    "messages": [{
                        "from": "5491198765432",
                        "type": "text",
                        "text": {
                            "body": "Hola"
                        }
                    }]
                }
            }]
        }]
    }
    
    body = json.dumps(webhook_data)
    
    # Firma inválida
    invalid_signature = "sha256=invalid_hash"
    
    response = client.post(
        "/webhook/whatsapp",
        data=body,
        headers={
            "X-Hub-Signature-256": invalid_signature,
            "Content-Type": "application/json"
        }
    )
    
    # Debería rechazar con 403
    assert response.status_code == 403


def test_meta_whatsapp_service_send_text():
    """Test del método send_text_message"""
    from services.meta_whatsapp_service import MetaWhatsAppService
    
    service = MetaWhatsAppService()
    
    with patch('requests.post') as mock_post:
        # Mock de respuesta exitosa de Meta API
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "5491135722871", "wa_id": "5491135722871"}],
            "messages": [{"id": "wamid.test123"}]
        }
        mock_post.return_value = mock_response
        
        result = service.send_text_message("+5491135722871", "Hola mundo")
        
        assert result is True
        assert mock_post.called


def test_meta_whatsapp_service_normalize_phone():
    """Test de normalización de números de teléfono"""
    from services.meta_whatsapp_service import MetaWhatsAppService
    
    service = MetaWhatsAppService()
    
    # Con prefijo whatsapp:
    assert service._normalize_phone_number("whatsapp:+5491135722871") == "5491135722871"
    
    # Con +
    assert service._normalize_phone_number("+5491135722871") == "5491135722871"
    
    # Sin +
    assert service._normalize_phone_number("5491135722871") == "5491135722871"
    
    # Con espacios
    assert service._normalize_phone_number("+549 11 3572 2871") == "5491135722871"


def test_meta_whatsapp_service_extract_message_data():
    """Test de extracción de datos del webhook"""
    from services.meta_whatsapp_service import MetaWhatsAppService
    
    service = MetaWhatsAppService()
    
    webhook_data = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {
                            "name": "Juan Pérez"
                        }
                    }],
                    "messages": [{
                        "from": "5491198765432",
                        "id": "wamid.test123",
                        "type": "text",
                        "text": {
                            "body": "Hola, necesito ayuda"
                        }
                    }]
                }
            }]
        }]
    }
    
    result = service.extract_message_data(webhook_data)
    
    assert result is not None
    numero, mensaje, msg_id, nombre, msg_type = result
    
    assert numero == "+5491198765432"
    assert mensaje == "Hola, necesito ayuda"
    assert msg_id == "wamid.test123"
    assert nombre == "Juan Pérez"
    assert msg_type == "text"


def test_meta_whatsapp_service_validate_signature():
    """Test de validación de firma HMAC"""
    from services.meta_whatsapp_service import MetaWhatsAppService
    
    service = MetaWhatsAppService()
    
    payload = b'{"test": "data"}'
    
    # Generar firma correcta
    correct_hash = hmac.new(
        "test_secret".encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    correct_signature = f"sha256={correct_hash}"
    
    # Validar firma correcta
    assert service.validate_webhook_signature(payload, correct_signature) is True
    
    # Validar firma incorrecta
    wrong_signature = "sha256=wrong_hash"
    assert service.validate_webhook_signature(payload, wrong_signature) is False


def test_gracias_post_finalizacion_no_reinicia():
    """Si la conversación terminó y el usuario dice gracias, se responde con ack y no se reinicia."""
    from main import app
    from chatbot.states import conversation_manager
    from chatbot.rules import ChatbotRules
    
    client = TestClient(app)
    numero = "5491198765432"
    conversation_manager.mark_recently_finalized(numero)
    
    payload = _build_message_payload("Gracias!!", from_number=numero)
    
    with patch('services.meta_whatsapp_service.meta_whatsapp_service.send_text_message') as mock_send, \
            patch('chatbot.rules.ChatbotRules.procesar_mensaje') as mock_procesar:
        mock_send.return_value = True
        response = _post_signed(client, payload)
    
    assert response.status_code == 200
    mock_procesar.assert_not_called()
    mock_send.assert_any_call(numero, ChatbotRules.get_mensaje_post_finalizado_gracias())


def test_nueva_consulta_post_finalizacion_reinicia():
    """Si envía otro mensaje distinto, se limpia el estado y se procesa normalmente."""
    from main import app
    from chatbot.states import conversation_manager
    
    client = TestClient(app)
    numero = "549117770000"
    conversation_manager.mark_recently_finalized(numero)
    
    payload = _build_message_payload("Necesito otra cosa", from_number=numero)
    
    with patch('services.meta_whatsapp_service.meta_whatsapp_service.send_text_message') as mock_send, \
            patch('chatbot.rules.ChatbotRules.procesar_mensaje', return_value="") as mock_procesar:
        mock_send.return_value = True
        response = _post_signed(client, payload)
    
    assert response.status_code == 200
    mock_procesar.assert_called_once()
    assert conversation_manager.was_finalized_recently(numero) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
