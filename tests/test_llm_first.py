#!/usr/bin/env python3

import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Agregar el directorio actual al path para importaciones
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chatbot.rules import ChatbotRules
from chatbot.states import conversation_manager

def test_caso_completo(numero_telefono: str, mensajes: list, descripcion: str):
    print(f"\n{'='*70}")
    print(f"🧪 PRUEBA LLM-FIRST: {descripcion}")
    print(f"{'='*70}")
    
    # Resetear conversación antes de cada prueba
    conversation_manager.reset_conversacion(numero_telefono)
    
    for i, mensaje in enumerate(mensajes):
        print(f"\n📱 Usuario ({i+1}): {mensaje}")
        respuesta = ChatbotRules.procesar_mensaje(numero_telefono, mensaje)
        print(f"🤖 Bot: {respuesta}")
        
        # Mostrar estado actual
        conv = conversation_manager.get_conversacion(numero_telefono)
        print(f"📊 Estado: {conv.estado}")
        if conv.datos_temporales:
            datos_relevantes = {k: v for k, v in conv.datos_temporales.items() if not k.startswith('_')}
            if datos_relevantes:
                print(f"📋 Datos: {datos_relevantes}")

def test_parsing_llm():
    print("🚀 INICIANDO PRUEBAS LLM-FIRST + VALIDACIÓN GEOGRÁFICA")
    
    # Caso 1: Tu ejemplo específico - múltiples campos en una línea
    test_caso_completo("test1", [
        "hola",
        "necesito cotizar matafuegos", 
        "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h"
    ], "Extracción múltiple campos - direccion + horario en una línea")
    
    # Caso 2: Direccion sin especificar CABA/Provincia - debe preguntar
    test_caso_completo("test2", [
        "hola",
        "1",
        "juan@empresa.com, Palermo cerca del shopping, mañanas, necesito extintores ABC",
        "1"  # Selecciona CABA
    ], "Validación geográfica - Palermo sin especificar → pregunta CABA/Provincia")
    
    # Caso 3: Direccion clara CABA - no debe preguntar
    test_caso_completo("test3", [
        "hola",
        "quiero matafuego urgente",
        "pedro@tech.com, Av. Corrientes 1234 CABA, cualquier tarde, oficina 50m2"
    ], "LLM-first + ubicación clara CABA - no pregunta ubicación")
    
    # Caso 4: Direccion clara Provincia - no debe preguntar  
    test_caso_completo("test4", [
        "hola",
        "2", 
        "maria@startup.com, La Plata centro, lunes a miércoles 10-15h, consultoría completa"
    ], "Ubicación clara Provincia (La Plata) - no pregunta ubicación")
    
    # Caso 5: Dirección ambigua → pregunta ubicación → selecciona Provincia
    test_caso_completo("test5", [
        "hola",
        "se rompió el extintor urgente",
        "carlos@empresa.com, Ramos Mejía altura 2500, horario flexible, válvula rota",
        "2"  # Selecciona Provincia
    ], "NLU + ubicación ambigua → árbol de decisión Provincia")

def test_solo_parsing():
    print(f"\n{'='*50}")
    print("🔍 TEST SOLO PARSING LLM vs BASICO")
    print(f"{'='*50}")
    
    mensaje_test = "Del valle centenera 3222 piso 4D, pueden pasar de 15-17h"
    
    # Test LLM
    print(f"\n📝 Mensaje: {mensaje_test}")
    try:
        datos_llm = ChatbotRules._extraer_datos_con_llm(mensaje_test)
        print(f"🤖 LLM result: {datos_llm}")
    except Exception as e:
        print(f"❌ LLM error: {e}")
    
    # Test básico
    try:
        datos_basico = ChatbotRules._parsear_datos_contacto_basico(mensaje_test)
        print(f"⚙️  Basic result: {datos_basico}")
    except Exception as e:
        print(f"❌ Basic error: {e}")

if __name__ == "__main__":
    # Verificar si OpenAI está configurado
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY no configurado - solo se ejecutarán tests básicos")
        test_solo_parsing()
    else:
        print("✅ OpenAI configurado - ejecutando tests completos")
        test_parsing_llm()
        test_solo_parsing()