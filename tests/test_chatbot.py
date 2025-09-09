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

def test_caso(numero_telefono: str, mensajes: list, descripcion: str):
    print(f"\n{'='*60}")
    print(f"🧪 PRUEBA: {descripcion}")
    print(f"{'='*60}")
    
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
            print(f"📋 Datos temporales: {conv.datos_temporales}")

def main():
    print("🚀 INICIANDO PRUEBAS DEL CHATBOT HÍBRIDO")
    
    # Caso 1: Flujo tradicional con números
    test_caso("test1", [
        "hola",
        "1",
        "juan@empresa.com\nAv. Corrientes 1234, CABA\nlunes a viernes 9-17h\nnecesito matafuegos para mi oficina de 200m2"
    ], "Flujo tradicional - todo en un mensaje")
    
    # Caso 2: NLU para mapeo de intenciones
    test_caso("test2", [
        "hola", 
        "quiero comprar un matafuego para mi empresa",
        "mi email es pedro@tech.com, estoy en Palermo, CABA en la calle Honduras 5000, pueden venir cualquier tarde y necesito equipar una oficina nueva"
    ], "NLU - mapeo de intención + datos completos")
    
    # Caso 3: Preguntas puntuales
    test_caso("test3", [
        "hola",
        "2",
        "maria@startup.com\nPuerto Madero",
        "lunes a miércoles por la mañana",
        "necesito una consultoría completa para equipar mi startup con todo lo necesario contra incendios"
    ], "Preguntas puntuales - datos incompletos iniciales")
    
    # Caso 4: NLU + preguntas puntuales
    test_caso("test4", [
        "hola",
        "se me rompió el extintor y necesito uno urgente",
        "carlos@empresa.com",
        "Microcentro, cerca del Obelisco",
        "cualquier momento hoy",
        "se rompió la válvula del extintor principal de la oficina"
    ], "Híbrido completo - NLU + preguntas puntuales")
    
    # Caso 5: Parsing complejo con LLM
    test_caso("test5", [
        "hola",
        "necesito cotizar matafuegos",
        "Hola soy Ana de la empresa TechCorp, mi contacto es ana.rodriguez@techcorp.com.ar, estamos ubicados en Belgrano en la calle Cabildo 2500 piso 3, podemos recibir visitas de lunes a viernes entre las 10 y 18 horas, queremos equipar nuestras oficinas que son 3 pisos de 150m2 cada uno con matafuegos clase ABC y sistemas de detección"
    ], "LLM - extracción de datos complejos en lenguaje natural")

if __name__ == "__main__":
    main()