import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("COMPANY_PROFILE", "argenfuego")
os.environ.setdefault("ERROR_LOG_EMAIL", "alerts@example.com")
os.environ.setdefault("AWS_REGION", "us-east-1")

from chatbot.models import ConversacionData, DatosContacto, EstadoConversacion, TipoConsulta
import services.email_service as email_module
import services.error_reporter as error_module


def _build_conversacion(tipo: TipoConsulta = TipoConsulta.PRESUPUESTO) -> ConversacionData:
    datos = DatosContacto(
        email="lead@example.com",
        direccion="Calle Falsa 123",
        horario_visita="Lunes 9-12",
        descripcion="Necesito un presupuesto completo para planta industrial.",
        razon_social="Empresa de Prueba SA",
        cuit="30-12345678-9",
    )
    return ConversacionData(
        numero_telefono="+5491112345678",
        estado=EstadoConversacion.ENVIANDO,
        tipo_consulta=tipo,
        datos_contacto=datos,
    )


def _mock_profile():
    return {
        "email_bot": "bot@example.com",
        "email": "ventas@example.com",
        "name": "Empresa Test",
        "bot_name": "Eva",
    }


def test_email_service_envia_lead_exitoso(monkeypatch):
    ses_mock = MagicMock()
    ses_mock.send_email.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "MessageId": "msg-123",
    }
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = ses_mock

    monkeypatch.setattr(email_module, "boto3", mock_boto3)
    monkeypatch.setattr(email_module, "get_active_company_profile", _mock_profile)
    monkeypatch.delenv("REPLY_TO_EMAIL", raising=False)

    service = email_module.EmailService()
    conversacion = _build_conversacion()

    assert service.enviar_lead_email(conversacion) is True
    ses_mock.send_email.assert_called_once()
    kwargs = ses_mock.send_email.call_args.kwargs
    assert kwargs["Destination"]["ToAddresses"] == ["ventas@example.com"]
    assert "Empresa Test" in kwargs["Message"]["Subject"]["Data"]


def test_email_service_envia_lead_falla_status(monkeypatch):
    ses_mock = MagicMock()
    ses_mock.send_email.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 500},
        "MessageId": "msg-500",
    }
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = ses_mock

    monkeypatch.setattr(email_module, "boto3", mock_boto3)
    monkeypatch.setattr(email_module, "get_active_company_profile", _mock_profile)

    service = email_module.EmailService()
    assert service.enviar_lead_email(_build_conversacion()) is False


def test_error_reporter_send_email_exitoso(monkeypatch):
    ses_mock = MagicMock()
    ses_mock.send_email.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "MessageId": "err-1",
    }
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = ses_mock
    monkeypatch.setattr(error_module, "boto3", mock_boto3)

    reporter = error_module.ErrorReporter()
    assert (
        reporter._send_email(
            subject="Test error",
            html="<p>Error</p>",
            from_name="Eva · Error Reporter",
        )
        is True
    )
    ses_mock.send_email.assert_called_once()
    kwargs = ses_mock.send_email.call_args.kwargs
    assert kwargs["Destination"]["ToAddresses"] == ["alerts@example.com"]


def test_error_reporter_send_email_falla(monkeypatch):
    ses_mock = MagicMock()
    ses_mock.send_email.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 400},
        "MessageId": "err-2",
    }
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = ses_mock
    monkeypatch.setattr(error_module, "boto3", mock_boto3)

    reporter = error_module.ErrorReporter()
    assert (
        reporter._send_email(
            subject="Test error",
            html="<p>Error</p>",
            from_name="Eva · Error Reporter",
        )
        is False
    )

