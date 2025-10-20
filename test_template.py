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
        from services.meta_whatsapp_service import meta_whatsapp_service
        
        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
        if not agent_number:
            print("❌ AGENT_WHATSAPP_NUMBER no configurado")
            return False
        
        print("🧪 PROBANDO ENVÍO DE TEMPLATE")
        print("=" * 40)
        print(f"Agente: {agent_number}")
        print()
        
        template_name = os.getenv("META_WA_TEMPLATE_NAME", "handoff_notification")
        language_code = os.getenv("META_WA_TEMPLATE_LANG", "es_AR")

        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Cliente Test"},
                    {"type": "text", "text": "+5491123456789"},
                    {"type": "text", "text": "quiero hablar con un humano"},
                    {"type": "text", "text": "necesito ayuda urgente"},
                ],
            }
        ]

        print("Template:", template_name)
        print("Idioma:", language_code)
        print("Componentes:", components)
        print()

        success = meta_whatsapp_service.send_template_message(
            agent_number,
            template_name,
            language_code,
            components
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
