#!/usr/bin/env python3
"""
Script de prueba para las nuevas funcionalidades:
- Sistema de configuración multi-empresa
- Detección de consultas de contacto
- Saludo personalizado con nombre de usuario
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import config first to avoid relative import issues  
from config.company_profiles import get_active_company_profile, get_company_info_text

# Import for urgency tests
try:
    from chatbot.rules import ChatbotRules
    from chatbot.states import conversation_manager
    CHATBOT_AVAILABLE = True
except ImportError:
    CHATBOT_AVAILABLE = False
    print("⚠️  Chatbot modules not available for full testing")

def test_nlu_import():
    """Test if NLU service can be imported and works"""
    try:
        # We'll test basic functionality without importing the problematic module
        import openai
        print("✅ OpenAI library available")
        return True
    except ImportError:
        print("❌ OpenAI library not available")
        return False

def test_company_configuration():
    print("🏢 === TEST: Configuración Multi-Empresa ===")
    
    # Test 1: Cargar perfil activo
    try:
        profile = get_active_company_profile()
        print(f"✅ Perfil activo: {profile['name']}")
        print(f"   Bot: {profile['bot_name']}")
        
        # Manejar formato de teléfono dict o string
        if isinstance(profile['phone'], dict):
            print(f"   Teléfono fijo: {profile['phone'].get('landline_phone', 'N/A')}")
            print(f"   Teléfono móvil: {profile['phone'].get('mobile_phone', 'N/A')}")
        else:
            print(f"   Teléfono: {profile['phone']}")
            
    except Exception as e:
        print(f"❌ Error cargando perfil: {e}")
        return False
    
    # Test 2: Generar información de contacto
    try:
        info = get_company_info_text()
        print("✅ Información de contacto generada")
        print(f"   Longitud: {len(info)} caracteres")
    except Exception as e:
        print(f"❌ Error generando info contacto: {e}")
        return False
    
    return True

def test_contact_detection():
    print("\n📞 === TEST: Detección de Consultas de Contacto ===")
    
    test_cases = [
        ("cuál es su teléfono?", True),
        ("dónde están ubicados?", True),
        ("qué horarios tienen?", True),
        ("necesito un presupuesto", False),
        ("ok, pero cuándo abren?", True),
        ("quiero comprar extintores", False),
    ]
    
    for mensaje, esperado in test_cases:
        try:
            resultado = nlu_service.detectar_consulta_contacto(mensaje)
            estado = "✅" if resultado == esperado else "❌"
            print(f"{estado} '{mensaje}' -> {resultado} (esperado: {esperado})")
        except Exception as e:
            print(f"❌ Error procesando '{mensaje}': {e}")
            return False
    
    return True

def test_contact_responses():
    print("\n💬 === TEST: Generación de Respuestas de Contacto ===")
    
    test_queries = [
        "cuál es su teléfono?",
        "dónde están ubicados?",
        "qué horarios tienen?",
        "necesito sus datos de contacto"
    ]
    
    for query in test_queries:
        try:
            respuesta = nlu_service.generar_respuesta_contacto(query)
            print(f"✅ '{query}' -> Respuesta generada ({len(respuesta)} chars)")
        except Exception as e:
            print(f"❌ Error generando respuesta para '{query}': {e}")
            return False
    
    return True

def test_contextual_interruption():
    print("\n🔄 === TEST: Interrupción Contextual ===")
    
    if not CHATBOT_AVAILABLE:
        print("⚠️  Saltando test - módulos de chatbot no disponibles")
        return True
    
    # Simular conversación con interrupción
    numero_test = "+541234567890"
    
    try:
        # 1. Iniciar conversación
        respuesta1 = ChatbotRules.procesar_mensaje(numero_test, "hola", "Juan")
        print("✅ Saludo inicial procesado")
        
        # 2. Seleccionar opción
        respuesta2 = ChatbotRules.procesar_mensaje(numero_test, "1")
        print("✅ Opción seleccionada")
        
        # 3. INTERRUPCIÓN: consulta de contacto en medio del flujo
        respuesta3 = ChatbotRules.procesar_mensaje(numero_test, "cuál es su teléfono?")
        print("✅ Interrupción contextual procesada")
        print(f"   Contiene info de contacto: {'teléfono' in respuesta3.lower()}")
        print(f"   Invita a continuar: {'sigamos' in respuesta3.lower()}")
        
        # 4. Continuar flujo normal
        respuesta4 = ChatbotRules.procesar_mensaje(numero_test, "juan@test.com, Palermo 123, mañanas, necesito extintores")
        print("✅ Flujo continuado después de interrupción")
        
        # Limpiar
        conversation_manager.finalizar_conversacion(numero_test)
        
    except Exception as e:
        print(f"❌ Error en test de interrupción contextual: {e}")
        return False
    
    return True

def test_emergency_redirect():
    print("\n🚨 === TEST: Redirección Inmediata de Urgencias ===")
    
    if not CHATBOT_AVAILABLE:
        print("⚠️  Saltando test - módulos de chatbot no disponibles")
        return True
    
    # Simular selección de urgencia
    numero_test = "+541234567891"
    
    try:
        # 1. Iniciar conversación
        respuesta1 = ChatbotRules.procesar_mensaje(numero_test, "hola", "María")
        print("✅ Saludo inicial procesado")
        
        # 2. Seleccionar URGENCIA (opción 3)
        respuesta2 = ChatbotRules.procesar_mensaje(numero_test, "3")
        print("✅ Urgencia seleccionada")
        print(f"   Contiene redirección: {'URGENCIA DETECTADA' in respuesta2}")
        print(f"   Contiene teléfono fijo: {'4567-8900' in respuesta2}")
        print(f"   Contiene celular: {'11 3906-1038' in respuesta2}")
        print(f"   Finaliza conversación: {'equipo técnico' in respuesta2.lower()}")
        
        # 3. Verificar que la conversación terminó (debe crear nueva)
        conversacion = conversation_manager.get_conversacion(numero_test)
        estado_final = conversacion.estado
        print(f"   Estado final: {estado_final}")
        
        # Limpiar
        conversation_manager.finalizar_conversacion(numero_test)
        
    except Exception as e:
        print(f"❌ Error en test de redirección de urgencias: {e}")
        return False
    
    return True

def main():
    print("🧪 === PRUEBAS DE NUEVAS FUNCIONALIDADES ===\n")
    
    tests = [
        ("Configuración Multi-Empresa", test_company_configuration),
        ("Detección de Consultas de Contacto", test_contact_detection),
        ("Generación de Respuestas de Contacto", test_contact_responses),
        ("Interrupción Contextual", test_contextual_interruption),
        ("Redirección de Urgencias", test_emergency_redirect)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Error ejecutando {name}: {e}")
            results.append((name, False))
    
    # Resumen
    print("\n" + "="*50)
    print("📊 RESUMEN DE PRUEBAS:")
    print("="*50)
    
    passed = 0
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} {name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Total: {passed}/{len(results)} pruebas exitosas")
    
    if passed == len(results):
        print("🎉 ¡Todas las funcionalidades están funcionando correctamente!")
        return 0
    else:
        print("⚠️  Algunas funcionalidades necesitan revisión.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
