#!/usr/bin/env python3
"""
Test rápido para verificar si Twilio puede enviar al número del agente
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def test_twilio_send():
    """Probar envío directo con Twilio"""
    try:
        from twilio.rest import Client
        
        # Credenciales de Twilio
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER")
        
        print("🔍 VERIFICANDO CONFIGURACIÓN")
        print("=" * 40)
        print(f"Twilio WhatsApp: {whatsapp_number}")
        print(f"Agente WhatsApp: {agent_number}")
        print()
        
        if not all([account_sid, auth_token, whatsapp_number, agent_number]):
            print("❌ Variables de entorno faltantes")
            return False
        
        # Crear cliente de Twilio
        client = Client(account_sid, auth_token)
        
        # Preparar mensaje
        test_message = "🧪 TEST - Si recibes esto, Twilio puede enviar a tu número ✅"
        
        print("📤 ENVIANDO MENSAJE DE PRUEBA")
        print("=" * 40)
        print(f"Desde: {whatsapp_number}")
        print(f"Hacia: {agent_number}")
        print(f"Mensaje: {test_message}")
        print()
        
        # Intentar enviar mensaje
        message = client.messages.create(
            body=test_message,
            from_=whatsapp_number,
            to=f"whatsapp:{agent_number}"
        )
        
        print("✅ MENSAJE ENVIADO EXITOSAMENTE")
        print(f"SID: {message.sid}")
        print(f"Status: {message.status}")
        print()
        print("💡 Revisa tu WhatsApp para confirmar que llegó el mensaje")
        return True
        
    except Exception as e:
        print("❌ ERROR ENVIANDO MENSAJE")
        print(f"Error: {str(e)}")
        print()
        
        # Analizar el tipo de error
        error_str = str(e).lower()
        if "not a valid phone number" in error_str:
            print("🔍 DIAGNÓSTICO: El número del agente no es válido")
        elif "not authorized" in error_str:
            print("🔍 DIAGNÓSTICO: No tienes permisos para enviar a este número")
        elif "not found" in error_str:
            print("🔍 DIAGNÓSTICO: El número no está en tu cuenta de Twilio")
        elif "geographic" in error_str:
            print("🔍 DIAGNÓSTICO: Restricciones geográficas")
        else:
            print("🔍 DIAGNÓSTICO: Error desconocido - revisa logs de Twilio")
        
        return False

if __name__ == "__main__":
    print("🧪 TEST DE ENVÍO TWILIO AL AGENTE")
    print("=" * 50)
    print()
    
    test_twilio_send()
    
    print("🏁 TEST COMPLETADO")
    print("=" * 50)
