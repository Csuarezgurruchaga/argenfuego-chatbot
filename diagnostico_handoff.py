#!/usr/bin/env python3
"""
Script de diagnóstico completo para el problema de handoff de WhatsApp
Ejecutar en Railway para diagnosticar el problema
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def verificar_variables_entorno():
    """Verificar que todas las variables de entorno estén configuradas"""
    print("🔍 VERIFICANDO VARIABLES DE ENTORNO")
    print("=" * 50)
    
    variables_requeridas = [
        "AGENT_WHATSAPP_NUMBER",
        "TWILIO_ACCOUNT_SID", 
        "TWILIO_AUTH_TOKEN",
        "TWILIO_WHATSAPP_NUMBER",
        "AGENT_API_TOKEN"
    ]
    
    todas_configuradas = True
    
    for var in variables_requeridas:
        valor = os.getenv(var)
        if valor:
            # Ocultar tokens sensibles
            if "TOKEN" in var or "SID" in var:
                valor_masked = valor[:8] + "..." + valor[-4:] if len(valor) > 12 else "***"
                print(f"✅ {var}: {valor_masked}")
            else:
                print(f"✅ {var}: {valor}")
        else:
            print(f"❌ {var}: NO CONFIGURADO")
            todas_configuradas = False
    
    print()
    return todas_configuradas

def verificar_formato_numero_agente():
    """Verificar que el número del agente tenga el formato correcto"""
    print("📱 VERIFICANDO FORMATO DEL NÚMERO DEL AGENTE")
    print("=" * 50)
    
    agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
    
    if not agent_number:
        print("❌ AGENT_WHATSAPP_NUMBER no está configurado")
        return False
    
    # Verificar formato
    if not agent_number.startswith('+'):
        print(f"⚠️  Número sin prefijo '+': {agent_number}")
        print("💡 Debería ser: +5491135722871")
        return False
    
    if not agent_number[1:].isdigit():
        print(f"⚠️  Número contiene caracteres no numéricos: {agent_number}")
        return False
    
    print(f"✅ Formato correcto: {agent_number}")
    print()
    return True

def test_twilio_conexion():
    """Probar conexión con Twilio"""
    print("🌐 PROBANDO CONEXIÓN CON TWILIO")
    print("=" * 50)
    
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        
        if not account_sid or not auth_token:
            print("❌ Credenciales de Twilio no configuradas")
            return False
        
        client = Client(account_sid, auth_token)
        
        # Intentar obtener información de la cuenta
        account = client.api.accounts(account_sid).fetch()
        print(f"✅ Conexión exitosa con Twilio")
        print(f"   Account SID: {account.sid}")
        print(f"   Account Status: {account.status}")
        print()
        return True
        
    except Exception as e:
        print(f"❌ Error conectando con Twilio: {str(e)}")
        print()
        return False

def test_envio_mensaje_directo():
    """Probar envío directo de mensaje al agente"""
    print("📤 PROBANDO ENVÍO DIRECTO AL AGENTE")
    print("=" * 50)
    
    try:
        from services.twilio_service import twilio_service
        
        agent_number = os.getenv("AGENT_WHATSAPP_NUMBER", "")
        if not agent_number:
            print("❌ AGENT_WHATSAPP_NUMBER no configurado")
            return False
        
        test_message = "🧪 TEST DIRECTO - Si recibes esto, el sistema funciona ✅"
        
        print(f"Enviando mensaje a: {agent_number}")
        print(f"Mensaje: {test_message}")
        
        success = twilio_service.send_whatsapp_message(agent_number, test_message)
        
        if success:
            print("✅ Mensaje enviado exitosamente")
            print("💡 Revisa tu WhatsApp para confirmar que llegó el mensaje")
        else:
            print("❌ Error enviando mensaje")
        
        print()
        return success
        
    except Exception as e:
        print(f"❌ Error en test de envío: {str(e)}")
        print()
        return False

def test_deteccion_handoff():
    """Probar detección de handoff"""
    print("🧪 PROBANDO DETECCIÓN DE HANDOFF")
    print("=" * 50)
    
    try:
        from services.nlu_service import nlu_service
        
        test_messages = [
            "humano",
            "quiero hablar con un agente",
            "necesito un operador",
            "hablar con una persona"
        ]
        
        for msg in test_messages:
            result = nlu_service.detectar_solicitud_humano(msg)
            status = "✅ HANDOFF" if result else "❌ NO HANDOFF"
            print(f"{status}: '{msg}'")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ Error en test de detección: {str(e)}")
        print()
        return False

def test_handoff_completo():
    """Probar flujo completo de handoff"""
    print("🔄 PROBANDO FLUJO COMPLETO DE HANDOFF")
    print("=" * 50)
    
    try:
        from chatbot.rules import ChatbotRules
        from chatbot.states import conversation_manager
        from chatbot.models import EstadoConversacion
        from services.whatsapp_handoff_service import whatsapp_handoff_service
        
        # Simular conversación
        test_phone = "+5491123456789"
        test_name = "Cliente Test"
        test_message = "quiero hablar con un humano"
        
        print(f"Simulando mensaje: '{test_message}' de {test_name} ({test_phone})")
        
        # Procesar mensaje
        respuesta = ChatbotRules.procesar_mensaje(test_phone, test_message, test_name)
        print(f"Respuesta del bot: {respuesta}")
        
        # Verificar estado
        conversacion = conversation_manager.get_conversacion(test_phone)
        handoff_activated = conversacion.atendido_por_humano or conversacion.estado == EstadoConversacion.ATENDIDO_POR_HUMANO
        
        print(f"Handoff activado: {handoff_activated}")
        print(f"Estado de conversación: {conversacion.estado}")
        
        if handoff_activated:
            # Intentar notificar al agente
            if not conversacion.handoff_notified:
                print("Enviando notificación al agente...")
                success = whatsapp_handoff_service.notify_agent_new_handoff(
                    test_phone,
                    test_name,
                    conversacion.mensaje_handoff_contexto or test_message,
                    test_message
                )
                
                if success:
                    print("✅ Notificación enviada al agente")
                    conversacion.handoff_notified = True
                else:
                    print("❌ Error enviando notificación al agente")
            else:
                print("ℹ️  Handoff ya notificado")
        
        print()
        return handoff_activated
        
    except Exception as e:
        print(f"❌ Error en test de handoff completo: {str(e)}")
        print()
        return False

def verificar_webhook_twilio():
    """Verificar configuración de webhook en Twilio"""
    print("🔗 VERIFICANDO CONFIGURACIÓN DE WEBHOOK")
    print("=" * 50)
    
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "")
        
        if not all([account_sid, auth_token, whatsapp_number]):
            print("❌ Variables de Twilio no configuradas")
            return False
        
        client = Client(account_sid, auth_token)
        
        # Limpiar prefijo whatsapp: si existe
        if whatsapp_number.startswith('whatsapp:'):
            whatsapp_number = whatsapp_number[9:]
        
        # Obtener información del número WhatsApp
        incoming_phone_numbers = client.incoming_phone_numbers.list()
        
        whatsapp_configured = False
        for number in incoming_phone_numbers:
            if number.phone_number == whatsapp_number:
                whatsapp_configured = True
                print(f"✅ Número WhatsApp encontrado: {number.phone_number}")
                print(f"   Webhook URL: {number.sms_url or 'No configurado'}")
                print(f"   Webhook Method: {number.sms_method or 'No configurado'}")
                break
        
        if not whatsapp_configured:
            print(f"⚠️  Número WhatsApp {whatsapp_number} no encontrado en la cuenta")
            print("💡 Verifica que el número esté configurado en Twilio Console")
        
        print()
        return whatsapp_configured
        
    except Exception as e:
        print(f"❌ Error verificando webhook: {str(e)}")
        print()
        return False

def generar_reporte_diagnostico():
    """Generar reporte completo de diagnóstico"""
    print("📊 REPORTE DE DIAGNÓSTICO COMPLETO")
    print("=" * 60)
    
    resultados = {
        "variables_entorno": verificar_variables_entorno(),
        "formato_numero": verificar_formato_numero_agente(),
        "conexion_twilio": test_twilio_conexion(),
        "deteccion_handoff": test_deteccion_handoff(),
        "webhook_twilio": verificar_webhook_twilio(),
        "envio_directo": test_envio_mensaje_directo(),
        "handoff_completo": test_handoff_completo()
    }
    
    print("📋 RESUMEN DE RESULTADOS")
    print("=" * 30)
    
    for test, resultado in resultados.items():
        status = "✅ PASS" if resultado else "❌ FAIL"
        print(f"{status}: {test.replace('_', ' ').title()}")
    
    print()
    
    # Recomendaciones
    print("💡 RECOMENDACIONES")
    print("=" * 20)
    
    if not resultados["variables_entorno"]:
        print("• Configura todas las variables de entorno en Railway")
    
    if not resultados["formato_numero"]:
        print("• Verifica que AGENT_WHATSAPP_NUMBER tenga formato +5491135722871")
    
    if not resultados["conexion_twilio"]:
        print("• Verifica credenciales de Twilio en Railway")
    
    if not resultados["webhook_twilio"]:
        print("• Configura webhook en Twilio Console apuntando a tu dominio Railway")
    
    if not resultados["envio_directo"]:
        print("• El problema está en el envío de mensajes - revisa logs de Twilio")
    
    if not resultados["handoff_completo"]:
        print("• El problema está en el flujo de handoff - revisa logs de la aplicación")
    
    print()
    print("🚀 PRÓXIMOS PASOS")
    print("=" * 20)
    print("1. Ejecuta este script en Railway con todas las variables configuradas")
    print("2. Revisa los logs de Railway para errores específicos")
    print("3. Verifica en Twilio Console que el webhook esté configurado")
    print("4. Prueba enviando un mensaje real al bot")

if __name__ == "__main__":
    print("🔧 DIAGNÓSTICO COMPLETO - HANDOFF WHATSAPP")
    print("=" * 60)
    print()
    
    generar_reporte_diagnostico()
    
    print("🏁 DIAGNÓSTICO COMPLETADO")
    print("=" * 60)
