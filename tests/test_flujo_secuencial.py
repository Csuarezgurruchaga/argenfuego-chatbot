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

def test_flujo_secuencial_completo():
    print("🚀 PROBANDO NUEVO FLUJO SECUENCIAL CONVERSACIONAL")
    print("=" * 60)
    
    numero_test = "test_secuencial"
    nombre_usuario = "Carlos R"
    
    # Resetear conversación
    conversation_manager.reset_conversacion(numero_test)
    
    mensajes_prueba = [
        "hola",
        "1",  # Presupuesto
        "carlos@mail.com",
        "Av. Rivadavia 1234, CABA", 
        "de 9 a 13hs",
        "Necesito la recarga de 5 matafuegos de 10kg y presupuesto de 2 nuevos.",
        "si"  # Confirmación final
    ]
    
    descripciones = [
        "Saludo inicial",
        "Seleccionar presupuesto",
        "Ingresar email",
        "Ingresar dirección",
        "Ingresar horario",
        "Ingresar descripción",
        "Confirmar datos"
    ]
    
    for i, (mensaje, desc) in enumerate(zip(mensajes_prueba, descripciones)):
        print(f"\n📱 Paso {i+1}: {desc}")
        print(f"Usuario: {mensaje}")
        
        respuesta = ChatbotRules.procesar_mensaje(numero_test, mensaje, nombre_usuario)
        print(f"🤖 Bot: {respuesta}")
        
        # Mostrar estado actual
        conv = conversation_manager.get_conversacion(numero_test)
        print(f"📊 Estado: {conv.estado}")
        
        # Mostrar datos recolectados (sin campos internos)
        if conv.datos_temporales:
            datos_user = {k: v for k, v in conv.datos_temporales.items() if not k.startswith('_')}
            if datos_user:
                print(f"📋 Datos recolectados: {datos_user}")
        
        print("-" * 50)
    
    print("\n✅ PRUEBA COMPLETADA")

def test_flujo_con_validacion_geografica():
    print("\n🌍 PROBANDO FLUJO CON VALIDACIÓN GEOGRÁFICA")
    print("=" * 60)
    
    numero_test = "test_geo"
    
    # Resetear conversación
    conversation_manager.reset_conversacion(numero_test)
    
    mensajes_prueba = [
        "hola",
        "necesito cotizar matafuegos",  # NLU detection
        "juan@empresa.com",
        "Del valle centenera 3222 piso 4D",  # Dirección sin especificar CABA/Provincia
        "1",  # Seleccionar CABA
        "de 15 a 17hs",
        "Necesito 3 matafuegos ABC de 5kg para oficina"
    ]
    
    for i, mensaje in enumerate(mensajes_prueba):
        print(f"\n📱 Mensaje {i+1}: {mensaje}")
        
        respuesta = ChatbotRules.procesar_mensaje(numero_test, mensaje)
        print(f"🤖 Bot: {respuesta}")
        
        conv = conversation_manager.get_conversacion(numero_test)
        print(f"📊 Estado: {conv.estado}")
        
        print("-" * 40)

if __name__ == "__main__":
    test_flujo_secuencial_completo()
    test_flujo_con_validacion_geografica()