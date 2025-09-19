#!/usr/bin/env python3
"""
Test para probar el envío de Message Template
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def test_template_send():
    """Probar envío de template"""
    try:
        from services.twilio_service import twilio_service
        
        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
        if not agent_number:
            print("❌ AGENT_WHATSAPP_NUMBER no configurado")
            return False
        
        print("🧪 PROBANDO ENVÍO DE TEMPLATE")
        print("=" * 40)
        print(f"Agente: {agent_number}")
        print()
        
        # Parámetros del template
        parameters = [
            "Cliente Test",           # {{1}} - Nombre del cliente
            "+5491123456789",        # {{2}} - Número del cliente
            "quiero hablar con un humano",  # {{3}} - Mensaje que disparó handoff
            "necesito ayuda urgente"  # {{4}} - Último mensaje
        ]
        
        print("Parámetros del template:")
        for i, param in enumerate(parameters, 1):
            print(f"  {{{{{i}}}}}: {param}")
        print()
        
        # Enviar template
        success = twilio_service.send_whatsapp_template(
            agent_number,
            "handoff_notification",
            parameters
        )
        
        if success:
            print("✅ Template enviado exitosamente")
            print("💡 Revisa tu WhatsApp para confirmar que llegó el mensaje")
        else:
            print("❌ Error enviando template")
        
        return success
        
    except Exception as e:
        print(f"❌ Error en test de template: {str(e)}")
        return False

if __name__ == "__main__":
    print("🧪 TEST DE MESSAGE TEMPLATE")
    print("=" * 50)
    print()
    
    test_template_send()
    
    print()
    print("🏁 TEST COMPLETADO")
    print("=" * 50)
