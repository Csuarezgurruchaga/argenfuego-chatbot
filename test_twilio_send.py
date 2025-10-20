#!/usr/bin/env python3
"""
Test rápido para verificar si la Cloud API de Meta puede enviar al número del agente
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def test_meta_send():
    """Probar envío directo con WhatsApp Cloud API"""
    try:
        from services.meta_whatsapp_service import meta_whatsapp_service

        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER")
        
        print("🔍 VERIFICANDO CONFIGURACIÓN")
        print("=" * 40)
        print(f"META_WA_PHONE_NUMBER_ID: {os.getenv('META_WA_PHONE_NUMBER_ID')}")
        print(f"Agente WhatsApp: {agent_number}")
        print()
        
        required_meta = [
            "META_WA_ACCESS_TOKEN",
            "META_WA_PHONE_NUMBER_ID",
            "META_WA_APP_SECRET",
            "META_WA_VERIFY_TOKEN",
            "AGENT_WHATSAPP_NUMBER"
        ]
        missing = [var for var in required_meta if not os.getenv(var)]
        if missing:
            print("❌ Variables de entorno faltantes:", ", ".join(missing))
            return False
        
        # Preparar mensaje
        test_message = "🧪 TEST - Si recibes esto, la API de Meta está entregando mensajes ✅"
        
        print("📤 ENVIANDO MENSAJE DE PRUEBA")
        print("=" * 40)
        print(f"Hacia: {agent_number}")
        print(f"Mensaje: {test_message}")
        print()
        
        success = meta_whatsapp_service.send_text_message(agent_number, test_message)
        
        if success:
            print("✅ MENSAJE ENVIADO EXITOSAMENTE")
            print("💡 Revisa tu WhatsApp para confirmar que llegó el mensaje")
            return True
        
        print("❌ Error enviando mensaje")
        print()
        return False

    except Exception as e:
        print("❌ ERROR ENVIANDO MENSAJE")
        print(f"Error: {str(e)}")
        print()
        print("🔍 DIAGNÓSTICO: Revisa los logs de la API de Meta o renueva el token de acceso")
        return False

if __name__ == "__main__":
    print("🧪 TEST DE ENVÍO META AL AGENTE")
    print("=" * 50)
    print()
    
    test_meta_send()
    
    print("🏁 TEST COMPLETADO")
    print("=" * 50)
