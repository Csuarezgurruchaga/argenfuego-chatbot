#!/usr/bin/env python3

import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Agregar el directorio raíz del proyecto al path para importaciones
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from services.nlu_service import nlu_service
from chatbot.rules import ChatbotRules
from chatbot.states import conversation_manager


def test_patrones_humano_basicos():
    positivos = [
        "necesito un teléfono para poder llamarlos",
        "necesito hablar",
        "quiero hablar con una persona",
        "puedo hablar con alguien",
        "humano",
        "agente",
        "operadora",
        "representante",
        "asesor",
        "quiero llamar",
    ]

    negativos = [
        "no quiero hablar con un humano",
        "no humano",
        "sin humano por favor",
        "necesito un presupuesto",
        "dónde están ubicados",
    ]

    for msg in positivos:
        assert nlu_service.detectar_solicitud_humano(msg) is True, f"Debería detectar HUMANO: {msg}"

    for msg in negativos:
        assert nlu_service.detectar_solicitud_humano(msg) is False, f"No debería detectar HUMANO: {msg}"


def test_respuesta_humano_con_telefonos():
    respuesta = nlu_service.generar_respuesta_humano("quiero hablar con una persona")
    assert "Teléfono fijo" in respuesta
    assert "solo llamadas" in respuesta
    assert "Celular" in respuesta or "WhatsApp" in respuesta


def test_interrupcion_contextual_humano():
    numero = "+541112223334"
    conversation_manager.reset_conversacion(numero)

    # Iniciar flujo
    ChatbotRules.procesar_mensaje(numero, "hola")
    ChatbotRules.procesar_mensaje(numero, "1")

    # Interrupción para hablar con humano
    respuesta = ChatbotRules.procesar_mensaje(numero, "quiero hablar con una persona")
    assert "Teléfono fijo" in respuesta
    assert "sigamos" in respuesta.lower() or "seguimos" in respuesta.lower()

    conversation_manager.finalizar_conversacion(numero)


if __name__ == "__main__":
    # Ejecutar tests simples sin framework
    test_patrones_humano_basicos()
    test_respuesta_humano_con_telefonos()
    test_interrupcion_contextual_humano()
    print("✅ Tests de intención humano completados")


