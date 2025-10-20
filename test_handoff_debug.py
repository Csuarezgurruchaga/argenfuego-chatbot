#!/usr/bin/env python3
"""
Script de debug para probar el handoff de WhatsApp
Ejecutar: python test_handoff_debug.py
"""

import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Agregar path para importaciones
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_env_variables():
    """Verificar que las variables de entorno estén configuradas"""
    print("🔍 VERIFICANDO VARIABLES DE ENTORNO")
    print("=" * 50)
    print("ℹ️  Variables configuradas en Railway (no disponibles localmente)")
    print("✅ AGENT_WHATSAPP_NUMBER: +5491135722871 (según tu configuración)")
    required = [
        "META_WA_ACCESS_TOKEN",
        "META_WA_PHONE_NUMBER_ID",
        "META_WA_APP_SECRET",
        "META_WA_VERIFY_TOKEN",
    ]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        print("❌ Variables META faltantes:", ", ".join(missing))
    else:
        print("✅ Variables META configuradas en Railway")
    print()

def test_handoff_detection():
    """Probar la detección de handoff"""
    print("🧪 TESTING DETECCIÓN DE HANDOFF")
    print("=" * 50)
    
    try:
        from services.nlu_service import nlu_service
        
        test_messages = [
            "humano",
            "quiero hablar con un agente", 
            "necesito un operador",
            "hablar con una persona",
            "quiero hablar con alguien",
            "hola como estas"  # Este NO debería activar handoff
        ]
        
        for msg in test_messages:
            result = nlu_service.detectar_solicitud_humano(msg)
            status = "✅ HANDOFF" if result else "❌ NO HANDOFF"
            print(f"{status}: '{msg}'")
            
    except Exception as e:
        print(f"❌ Error en detección: {e}")
    print()

def test_direct_whatsapp_send():
    """Probar envío directo de WhatsApp al agente"""
    print("📱 TESTING ENVÍO DIRECTO WHATSAPP")
    print("=" * 50)
    print("⚠️  Este test requiere variables de entorno de Railway")
    print("🚀 Para ejecutar en Railway:")
    print("   1. Sube este archivo a tu proyecto")
    print("   2. Ejecuta: python test_handoff_debug.py")
    print("   3. O añade esta función a main.py como endpoint temporal")
    print()

def test_handoff_service():
    """Probar el servicio de handoff completo"""
    print("🔄 TESTING SERVICIO HANDOFF COMPLETO")
    print("=" * 50)
    print("⚠️  Este test también requiere variables de entorno de Railway")
    print()

def test_regex_patterns_local():
    """Probar los patterns regex localmente (sin variables de entorno)"""
    print("🧪 TESTING PATTERNS REGEX (LOCAL)")
    print("=" * 50)
    
    # Importar patterns directamente
    try:
        import re
        import unicodedata
        
        # Patterns copiados del código
        HUMAN_INTENT_PATTERNS = [
            r"\bhumano\b",
            r"\bpersona\b",
            r"\balguien\s+real\b",
            r"\bagente\b",
            r"\boperador(?:a)?\b",
            r"\bquiero\s+hablar\b",
            r"\bnecesito\s+hablar\b",
            r"\bhablar\s+con\s+(?:alguien|una\s+persona)\b",
        ]
        
        def _normalize(s: str) -> str:
            s = s.lower().strip()
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        
        test_messages = [
            "humano",                           # ✅ Debería funcionar
            "quiero hablar con un agente",      # ✅ Debería funcionar  
            "necesito un operador",             # ✅ Debería funcionar
            "hablar con una persona",           # ✅ Debería funcionar
            "quiero hablar con alguien",        # ✅ Debería funcionar
            "conectame con soporte",            # ❌ NO debería funcionar
            "ayuda personalizada",              # ❌ NO debería funcionar
            "atención humana",                  # ❌ NO debería funcionar
            "hola como estas"                   # ❌ NO debería funcionar
        ]
        
        print("Patterns que se van a probar:")
        for i, pattern in enumerate(HUMAN_INTENT_PATTERNS[:8], 1):
            print(f"  {i}. {pattern}")
        print()
        
        for msg in test_messages:
            mensaje_lower = _normalize(msg)
            found_pattern = None
            
            for pattern in HUMAN_INTENT_PATTERNS:
                if re.search(pattern, mensaje_lower, re.IGNORECASE):
                    found_pattern = pattern
                    break
            
            if found_pattern:
                print(f"✅ HANDOFF: '{msg}' -> pattern: {found_pattern}")
            else:
                print(f"❌ NO HANDOFF: '{msg}'")
                
    except Exception as e:
        print(f"❌ Error en test regex: {e}")
    print()

if __name__ == "__main__":
    print("🚀 SCRIPT DE DEBUG - HANDOFF WHATSAPP")
    print("=" * 60)
    print()
    
    test_env_variables()
    test_regex_patterns_local() 
    test_handoff_detection() 
    test_direct_whatsapp_send()
    test_handoff_service()
    
    print("🏁 DEBUG COMPLETADO")
    print("=" * 60)
    print("💡 Los patterns regex muestran qué palabras exactas funcionan")
    print("💡 Para test completo, ejecuta este script en Railway con variables de entorno")
