#!/usr/bin/env python3
"""
Script de prueba para botones interactivos de WhatsApp
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def test_quick_reply():
    """Probar envío de Quick Reply (botones)"""
    try:
        from services.meta_whatsapp_service import meta_whatsapp_service
        
        # Número de prueba (cambiar por tu número)
        test_number = "+5491123456789"  # Cambiar por tu número real
        
        print("🧪 PROBANDO QUICK REPLY (BOTONES)")
        print("=" * 50)
        print(f"Enviando a: {test_number}")
        print()
        
        # Mensaje con botones
        mensaje = "¡Hola! ¿En qué puedo ayudarte hoy?"
        
        buttons = [
            {"id": "presupuesto", "title": "📋 Presupuesto"},
            {"id": "urgencia", "title": "🚨 Urgencia"},
            {"id": "otras", "title": "❓ Otras consultas"}
        ]
        
        print("Mensaje:", mensaje)
        print("Botones:")
        for button in buttons:
            print(f"  - {button['id']}: {button['title']}")
        print()
        
        success = meta_whatsapp_service.send_interactive_buttons(
            test_number,
            body_text=mensaje,
            buttons=buttons,
            header_text="Seleccioná una opción",
            footer_text="Respuesta de prueba"
        )
        
        if success:
            print("✅ Quick Reply enviado exitosamente")
            print("💡 Revisa tu WhatsApp para ver los botones")
        else:
            print("❌ Error enviando Quick Reply")
        
        return success
        
    except Exception as e:
        print(f"❌ Error en test de Quick Reply: {str(e)}")
        return False

def test_list_picker():
    """Probar envío de List Picker (lista desplegable)"""
    try:
        from services.meta_whatsapp_service import meta_whatsapp_service
        
        # Número de prueba (cambiar por tu número)
        test_number = "+5491123456789"  # Cambiar por tu número real
        
        print("🧪 PROBANDO LIST PICKER (LISTA DESPLEGABLE)")
        print("=" * 50)
        print(f"Enviando a: {test_number}")
        print()
        
        # Mensaje con lista
        mensaje = "Selecciona el tipo de servicio que necesitas:"
        button_text = "Ver opciones"
        
        sections = [
            {
                "title": "Servicios de Extintores",
                "rows": [
                    {"id": "mantenimiento", "title": "Mantenimiento de extintores"},
                    {"id": "recarga", "title": "Recarga de extintores"},
                    {"id": "instalacion", "title": "Instalación de extintores"}
                ]
            },
            {
                "title": "Otros Servicios",
                "rows": [
                    {"id": "capacitacion", "title": "Capacitación en seguridad"},
                    {"id": "inspeccion", "title": "Inspección de instalaciones"},
                    {"id": "consultoria", "title": "Consultoría en seguridad"}
                ]
            }
        ]
        
        print("Mensaje:", mensaje)
        print("Botón:", button_text)
        print("Secciones:")
        for section in sections:
            print(f"  {section['title']}:")
            for row in section['rows']:
                print(f"    - {row['id']}: {row['title']}")
        print()
        
        success = meta_whatsapp_service.send_interactive_list(
            test_number,
            body_text=mensaje,
            button_text=button_text,
            sections=sections,
            header_text="Opciones disponibles",
            footer_text="Demo de lista"
        )
        
        if success:
            print("✅ List Picker enviado exitosamente")
            print("💡 Revisa tu WhatsApp para ver la lista desplegable")
        else:
            print("❌ Error enviando List Picker")
        
        return success
        
    except Exception as e:
        print(f"❌ Error en test de List Picker: {str(e)}")
        return False

def test_handoff_buttons():
    """Probar botones de handoff"""
    try:
        from chatbot.rules import ChatbotRules
        
        # Número de prueba (cambiar por tu número)
        test_number = "+5491123456789"  # Cambiar por tu número real
        
        print("🧪 PROBANDO BOTONES DE HANDOFF")
        print("=" * 50)
        print(f"Enviando a: {test_number}")
        print()
        
        # Enviar botones de handoff
        success = ChatbotRules.send_handoff_buttons(test_number)
        
        if success:
            print("✅ Botones de handoff enviados exitosamente")
            print("💡 Revisa tu WhatsApp para ver los botones")
        else:
            print("❌ Error enviando botones de handoff")
        
        return success
        
    except Exception as e:
        print(f"❌ Error en test de botones de handoff: {str(e)}")
        return False

def test_menu_interactivo():
    """Probar menú interactivo"""
    try:
        from chatbot.rules import ChatbotRules
        
        # Número de prueba (cambiar por tu número)
        test_number = "+5491123456789"  # Cambiar por tu número real
        
        print("🧪 PROBANDO MENÚ INTERACTIVO")
        print("=" * 50)
        print(f"Enviando a: {test_number}")
        print()
        
        # Enviar menú interactivo
        success = ChatbotRules.send_menu_interactivo(test_number, "Usuario Test")
        
        if success:
            print("✅ Menú interactivo enviado exitosamente")
            print("💡 Revisa tu WhatsApp para ver el menú con botones")
        else:
            print("❌ Error enviando menú interactivo")
        
        return success
        
    except Exception as e:
        print(f"❌ Error en test de menú interactivo: {str(e)}")
        return False

def main():
    """Ejecutar todas las pruebas"""
    print("🚀 PRUEBAS DE BOTONES INTERACTIVOS")
    print("=" * 60)
    print()
    
    # Verificar variables de entorno
    required_meta = [
        "META_WA_ACCESS_TOKEN",
        "META_WA_PHONE_NUMBER_ID",
        "META_WA_APP_SECRET",
        "META_WA_VERIFY_TOKEN",
    ]

    missing = [var for var in required_meta if not os.getenv(var)]
    if missing:
        print("❌ Variables de entorno faltantes para Meta:", ", ".join(missing))
        return
    
    print("⚠️  IMPORTANTE: Cambia el número de prueba en el código antes de ejecutar")
    print("   Busca '+5491123456789' y reemplázalo por tu número real")
    print()
    
    # Ejecutar pruebas
    resultados = {
        "Quick Reply": test_quick_reply(),
        "List Picker": test_list_picker(),
        "Botones Handoff": test_handoff_buttons(),
        "Menú Interactivo": test_menu_interactivo()
    }
    
    print()
    print("📊 RESUMEN DE RESULTADOS")
    print("=" * 30)
    
    for test, resultado in resultados.items():
        status = "✅ PASS" if resultado else "❌ FAIL"
        print(f"{status}: {test}")
    
    print()
    print("🏁 PRUEBAS COMPLETADAS")
    print("=" * 60)

if __name__ == "__main__":
    main()
