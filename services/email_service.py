import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From, To, Subject, HtmlContent
from chatbot.models import ConversacionData, TipoConsulta
from config.company_profiles import get_active_company_profile
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.api_key = os.getenv('SENDGRID_API_KEY')
        
        # Obtener configuración de empresa activa
        company_profile = get_active_company_profile()
        
        self.from_email = os.getenv('SENDGRID_FROM_EMAIL', company_profile['email'])
        self.to_email = os.getenv('LEAD_RECIPIENT', company_profile['email'])
        self.company_name = company_profile['name']
        self.bot_name = company_profile['bot_name']
        
        if not self.api_key:
            raise ValueError("SENDGRID_API_KEY es requerido")
        
        self.sg = SendGridAPIClient(api_key=self.api_key)
    
    def enviar_lead_email(self, conversacion: ConversacionData) -> bool:
        try:
            subject = self._get_email_subject(conversacion.tipo_consulta)
            html_content = self._generate_email_html(conversacion)
            
            message = Mail(
                from_email=From(self.from_email, f"{self.bot_name} - Asistente Virtual {self.company_name}"),
                to_emails=To(self.to_email),
                subject=Subject(subject),
                html_content=HtmlContent(html_content)
            )
            
            response = self.sg.send(message)
            
            if response.status_code in [200, 202]:
                logger.info(f"Email enviado exitosamente para {conversacion.numero_telefono}")
                return True
            else:
                logger.error(f"Error enviando email. Status: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error enviando email para {conversacion.numero_telefono}: {str(e)}")
            return False
    
    def _get_email_subject(self, tipo_consulta: TipoConsulta) -> str:
        subjects = {
            TipoConsulta.PRESUPUESTO: f"🔥 Nueva Solicitud de Presupuesto - {self.company_name}",
            TipoConsulta.VISITA_TECNICA: f"📋 Nueva Solicitud de Visita Técnica - {self.company_name}", 
            TipoConsulta.URGENCIA: f"🚨 URGENCIA - Nueva Consulta - {self.company_name}",
            TipoConsulta.OTRAS: f"💬 Nueva Consulta General - {self.company_name}"
        }
        return subjects.get(tipo_consulta, f"Nueva Consulta - {self.company_name}")
    
    def _generate_email_html(self, conversacion: ConversacionData) -> str:
        tipo_consulta_texto = {
            TipoConsulta.PRESUPUESTO: "Solicitud de Presupuesto",
            TipoConsulta.VISITA_TECNICA: "Visita Técnica",
            TipoConsulta.URGENCIA: "Urgencia",
            TipoConsulta.OTRAS: "Consulta General"
        }
        
        urgencia_style = ""
        if conversacion.tipo_consulta == TipoConsulta.URGENCIA:
            urgencia_style = "background-color: #fee2e2; border-left: 4px solid #dc2626; padding: 10px; margin: 10px 0;"
        
        fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Nueva Consulta - Argenfuego</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            
            <div style="background-color: #1f2937; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">🔥 {self.company_name.upper()}</h1>
                <p style="margin: 5px 0 0 0; font-size: 14px;">Nueva consulta desde WhatsApp</p>
            </div>
            
            <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
                
                <div style="{urgencia_style}">
                    <h2 style="color: #dc2626; margin: 0 0 10px 0;">
                        {tipo_consulta_texto[conversacion.tipo_consulta]}
                    </h2>
                </div>
                
                <div style="background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    
                    <h3 style="color: #1f2937; border-bottom: 2px solid #f59e0b; padding-bottom: 5px;">
                        📋 Datos del Cliente
                    </h3>
                    
                    <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; color: #374151; width: 30%;">📧 Email:</td>
                            <td style="padding: 8px 0; color: #1f2937;">
                                <a href="mailto:{conversacion.datos_contacto.email}" style="color: #2563eb; text-decoration: none;">
                                    {conversacion.datos_contacto.email}
                                </a>
                            </td>
                        </tr>"""
        
        # Campos adicionales solo para presupuestos y visitas técnicas
        if conversacion.tipo_consulta != TipoConsulta.OTRAS:
            html_template += f"""
                        <tr style="background-color: #f9fafb;">
                            <td style="padding: 8px 0; font-weight: bold; color: #374151;">📍 Dirección:</td>
                            <td style="padding: 8px 0; color: #1f2937;">{conversacion.datos_contacto.direccion}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; color: #374151;">🕒 Horario de visita:</td>
                            <td style="padding: 8px 0; color: #1f2937;">{conversacion.datos_contacto.horario_visita}</td>
                        </tr>"""
        
        html_template += f"""
                        <tr style="background-color: #f9fafb;">
                            <td style="padding: 8px 0; font-weight: bold; color: #374151;">📱 WhatsApp:</td>
                            <td style="padding: 8px 0; color: #1f2937;">
                                <a href="https://wa.me/{conversacion.numero_telefono.replace('+', '')}" style="color: #059669; text-decoration: none;">
                                    {conversacion.numero_telefono}
                                </a>
                            </td>
                        </tr>
                    </table>
                    
                    <h3 style="color: #1f2937; border-bottom: 2px solid #f59e0b; padding-bottom: 5px; margin-top: 30px;">
                        📝 Descripción de la Necesidad
                    </h3>
                    
                    <div style="background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 15px; margin: 15px 0; border-radius: 0 8px 8px 0;">
                        <p style="margin: 0; color: #1f2937; font-style: italic;">
                            "{conversacion.datos_contacto.descripcion}"
                        </p>
                    </div>
                    
                </div>
                
                <div style="margin-top: 20px; padding: 15px; background-color: #ecfdf5; border-radius: 8px; border-left: 4px solid #10b981;">
                    <h4 style="color: #047857; margin: 0 0 10px 0;">✅ Próximos Pasos</h4>
                    <ul style="margin: 0; padding-left: 20px; color: #065f46;">
                        <li>Contactar al cliente vía email o WhatsApp</li>
                        <li>Evaluar la solicitud y preparar respuesta</li>
                        <li>Coordinar visita técnica si es necesario</li>
                    </ul>
                </div>
                
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                
                <p style="text-align: center; color: #6b7280; font-size: 12px; margin: 0;">
                    📅 Solicitud generada el {fecha_actual}<br>
                    🤖 Procesado automáticamente por {self.bot_name} - Asistente Virtual de {self.company_name}
                </p>
                
            </div>
            
        </body>
        </html>
        """
        
        return html_template

email_service = EmailService()