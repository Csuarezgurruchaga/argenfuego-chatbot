#!/usr/bin/env python3
"""
Script de diagnóstico para el problema de inicio del bot
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def diagnosticar_problema_inicio():
    """Diagnostica el problema de inicio del bot"""
    print("🔍 DIAGNÓSTICO DEL PROBLEMA DE INICIO")
    print("=" * 50)
    
    # 1. Verificar configuración de agente
    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
    print(f"1. AGENT_WHATSAPP_NUMBER: {agent_number}")
    
    if not agent_number:
        print("❌ PROBLEMA: AGENT_WHATSAPP_NUMBER no está configurado")
        return
    
    # 2. Verificar si el número de prueba es el mismo que el agente
    test_number = "+5491139061038"  # Número que estás usando para probar
    print(f"2. Número de prueba: {test_number}")
    
    if test_number == agent_number:
        print("❌ PROBLEMA IDENTIFICADO:")
        print("   Estás probando desde el mismo número configurado como AGENT_WHATSAPP_NUMBER")
        print("   El bot piensa que eres el agente, no el cliente")
        print()
        print("🔧 SOLUCIONES:")
        print("   1. Usar un número diferente para probar (recomendado)")
        print("   2. Cambiar temporalmente AGENT_WHATSAPP_NUMBER")
        print("   3. Usar los endpoints de debug que agregamos")
        return
    
    # 3. Verificar configuración de Meta
    phone_id = os.getenv("META_WA_PHONE_NUMBER_ID", "")
    access_token = os.getenv("META_WA_ACCESS_TOKEN", "")
    print(f"3. META_WA_PHONE_NUMBER_ID: {phone_id}")
    print(f"4. META_WA_ACCESS_TOKEN presente: {bool(access_token)}")
    
    if not phone_id or not access_token:
        print("❌ PROBLEMA: Variables de Meta (META_WA_PHONE_NUMBER_ID / META_WA_ACCESS_TOKEN) faltantes")
        return
    
    print("✅ Configuración básica parece correcta")
    print()
    print("🧪 PRUEBAS RECOMENDADAS:")
    print("   1. Usar un número diferente para probar")
    print("   2. Probar con los endpoints de debug")
    print("   3. Verificar logs de Railway")

def probar_con_numero_diferente():
    """Sugiere cómo probar con un número diferente"""
    print()
    print("📱 CÓMO PROBAR CON NÚMERO DIFERENTE")
    print("=" * 40)
    print()
    print("1. Usa un número de WhatsApp diferente (no el del agente)")
    print("2. Envía 'hola' a tu bot de WhatsApp")
    print("3. Deberías ver el saludo y menú interactivo")
    print()
    print("💡 NÚMEROS DE PRUEBA SUGERIDOS:")
    print("   - Tu número personal (si es diferente al agente)")
    print("   - Número de un familiar/amigo")

def probar_con_endpoints_debug():
    """Explica cómo usar los endpoints de debug"""
    print()
    print("🔧 USAR ENDPOINTS DE DEBUG")
    print("=" * 30)
    print()
    print("1. POST /test-bot-flow")
    print("   - Parámetro: test_number (tu número)")
    print("   - Simula el flujo completo del bot")
    print()
    print("2. POST /test-interactive-buttons")
    print("   - Parámetro: test_number (tu número)")
    print("   - Prueba solo los botones interactivos")
    print()
    print("💡 EJEMPLO DE USO:")
    print("   curl -X POST 'https://tu-app.railway.app/test-bot-flow' \\")
    print("        -H 'Content-Type: application/x-www-form-urlencoded' \\")
    print("        -d 'test_number=+5491123456789'")

def verificar_logs_railway():
    """Sugiere cómo verificar logs de Railway"""
    print()
    print("📊 VERIFICAR LOGS DE RAILWAY")
    print("=" * 30)
    print()
    print("1. Ve a tu dashboard de Railway")
    print("2. Selecciona tu servicio")
    print("3. Ve a la pestaña 'Logs'")
    print("4. Busca mensajes que contengan:")
    print("   - 'Procesando mensaje de'")
    print("   - 'Botón presionado por'")
    print("   - 'ERROR' o 'Error'")
    print()
    print("🔍 LOGS IMPORTANTES A BUSCAR:")
    print("   - Si aparece 'is_agent_message: True'")
    print("   - Si aparece 'handle_agent_message'")
    print("   - Si aparece 'No hay conversaciones activas'")

def main():
    """Función principal"""
    diagnosticar_problema_inicio()
    probar_con_numero_diferente()
    probar_con_endpoints_debug()
    verificar_logs_railway()
    
    print()
    print("🎯 RESUMEN DEL PROBLEMA")
    print("=" * 25)
    print("El bot está detectando tu mensaje como si viniera del agente")
    print("porque estás usando el mismo número configurado como")
    print("AGENT_WHATSAPP_NUMBER. Por eso responde con mensajes")
    print("de sistema en lugar del saludo inicial.")
    print()
    print("✅ SOLUCIÓN MÁS RÁPIDA:")
    print("   Usa un número diferente para probar el bot")

if __name__ == "__main__":
    main()
