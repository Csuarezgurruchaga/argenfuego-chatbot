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

def test_parsing_simple():
    print("🧪 TEST PARSING MEJORADO")
    print("="*50)
    
    # Resetear conversación
    numero = "test123"
    conversation_manager.reset_conversacion(numero)
    
    # Test 1: Mensaje estructurado
    mensaje1 = """juan@empresa.com
Av. Corrientes 1234, CABA
lunes a viernes 9-17h
necesito matafuegos para mi oficina de 200m2"""
    
    print("📱 Mensaje de entrada:")
    print(mensaje1)
    print("\n📊 Parsing resultado:")
    datos = ChatbotRules._parsear_datos_contacto(mensaje1)
    for campo, valor in datos.items():
        print(f"  {campo}: '{valor}'")
    
    # Test 2: Mensaje con keywords
    print("\n" + "="*50)
    mensaje2 = """Email: pedro@tech.com
Dirección: Honduras 5000, Palermo
Horario disponible: cualquier tarde
Descripción: equipar oficina nueva con extintores"""
    
    print("📱 Mensaje con keywords:")
    print(mensaje2)
    print("\n📊 Parsing resultado:")
    datos2 = ChatbotRules._parsear_datos_contacto(mensaje2)
    for campo, valor in datos2.items():
        print(f"  {campo}: '{valor}'")

if __name__ == "__main__":
    test_parsing_simple()