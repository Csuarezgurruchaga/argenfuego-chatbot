import os
from dotenv import load_dotenv

# Cargar variables de entorno PRIMERO
load_dotenv()

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import PlainTextResponse
import logging
from chatbot.rules import ChatbotRules
from chatbot.states import conversation_manager
from chatbot.models import EstadoConversacion
from services.twilio_service import twilio_service
from services.email_service import email_service

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear la aplicación FastAPI
app = FastAPI(
    title="Argenfuego Chatbot API",
    description="Chatbot basado en reglas para WhatsApp usando Twilio",
    version="1.0.0"
)

@app.get("/")
async def root():
    return {
        "message": "Argenfuego Chatbot API",
        "status": "active",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "argenfuego-chatbot"
    }

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request):
    try:
        # Obtener datos del formulario de Twilio
        form_data = await request.form()
        form_dict = dict(form_data)
        
        logger.info(f"Webhook recibido: {form_dict}")
        
        # Extraer datos del mensaje
        numero_telefono, mensaje_usuario, message_sid = twilio_service.extract_message_data(form_dict)
        
        if not numero_telefono or not mensaje_usuario:
            logger.warning("Datos incompletos en el webhook")
            return PlainTextResponse("OK", status_code=200)
        
        logger.info(f"Procesando mensaje de {numero_telefono}: {mensaje_usuario}")
        
        # Procesar el mensaje con el chatbot
        respuesta = ChatbotRules.procesar_mensaje(numero_telefono, mensaje_usuario)
        
        # Enviar respuesta via WhatsApp
        mensaje_enviado = twilio_service.send_whatsapp_message(numero_telefono, respuesta)
        
        if not mensaje_enviado:
            logger.error(f"Error enviando mensaje a {numero_telefono}")
        
        # Verificar si necesitamos enviar email
        conversacion = conversation_manager.get_conversacion(numero_telefono)
        
        if conversacion.estado == EstadoConversacion.ENVIANDO:
            # Enviar email con los datos del lead
            email_enviado = email_service.enviar_lead_email(conversacion)
            
            if email_enviado:
                # Enviar mensaje de confirmación
                mensaje_final = ChatbotRules.get_mensaje_final_exito()
                twilio_service.send_whatsapp_message(numero_telefono, mensaje_final)
                
                # Finalizar la conversación
                conversation_manager.finalizar_conversacion(numero_telefono)
                
                logger.info(f"Lead procesado exitosamente para {numero_telefono}")
            else:
                # Error enviando email
                error_msg = "❌ Hubo un error procesando tu solicitud. Por favor intenta nuevamente más tarde."
                twilio_service.send_whatsapp_message(numero_telefono, error_msg)
                logger.error(f"Error enviando email para {numero_telefono}")
        
        return PlainTextResponse("OK", status_code=200)
        
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return PlainTextResponse("Error", status_code=500)

@app.get("/stats")
async def get_stats():
    """Endpoint para obtener estadísticas básicas del chatbot"""
    total_conversaciones = len(conversation_manager.conversaciones)
    conversaciones_por_estado = {}
    
    for conversacion in conversation_manager.conversaciones.values():
        estado = conversacion.estado
        conversaciones_por_estado[estado] = conversaciones_por_estado.get(estado, 0) + 1
    
    return {
        "total_conversaciones_activas": total_conversaciones,
        "conversaciones_por_estado": conversaciones_por_estado,
        "timestamp": "2024-01-01T00:00:00Z"  # Placeholder timestamp
    }

@app.post("/reset-conversation")
async def reset_conversation(numero_telefono: str = Form(...)):
    """Endpoint para resetear una conversación específica (útil para debugging)"""
    try:
        conversation_manager.reset_conversacion(numero_telefono)
        return {"message": f"Conversación resetada para {numero_telefono}"}
    except Exception as e:
        logger.error(f"Error reseteando conversación: {str(e)}")
        raise HTTPException(status_code=500, detail="Error reseteando conversación")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)