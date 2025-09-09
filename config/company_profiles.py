import os
from typing import Dict, Any

# Perfiles de empresas configurables
COMPANY_PROFILES = {
    "argenfuego": {
        "name": "Argenfuego",
        "bot_name": "Eva",
        "phone": {"public_phone":"4567-8900", "mobile_phone":"11-3906-1038", "emergency_phone":"11-3906-1038"},
        "address": "Av. Hipólito Yrigoyen 2020, El Talar, Provincia de Buenos Aires",
        "hours": "Lunes a Viernes de 8 a 17hs y Sábados de 9 a 13hs",
        "email": "argenfuego@yahoo.com.ar",
        "website": "www.argenfuego.com.ar"
    },
    "empresa_ejemplo": {
        "name": "Empresa Ejemplo",
        "bot_name": "Asistente",
        "phone": "+54 11 0000-0000",
        "address": "Dirección ejemplo",
        "hours": "Horarios ejemplo",
        "email": "info@ejemplo.com",
        "industry": "Industria ejemplo",
        "website": "www.ejemplo.com"
    }
}

def get_active_company_profile() -> Dict[str, Any]:
    """
    Obtiene el perfil de empresa activo desde variable de entorno
    """
    profile_name = os.getenv('COMPANY_PROFILE').lower()
    
    if profile_name not in COMPANY_PROFILES:
        raise ValueError(f"Perfil de empresa '{profile_name}' no encontrado. Perfiles disponibles: {list(COMPANY_PROFILES.keys())}")
    
    return COMPANY_PROFILES[profile_name]

def get_company_info_text() -> str:
    """
    Genera texto formateado con información de contacto de la empresa activa
    """
    profile = get_active_company_profile()
    
    # Manejar tanto formato de teléfono dict como string para compatibilidad
    phone_text = ""
    if isinstance(profile['phone'], dict):
        phone_parts = []
        if profile['phone'].get('landline_phone'):
            phone_parts.append(f"📞 {profile['phone']['landline_phone']}")
        if profile['phone'].get('mobile_phone'):
            phone_parts.append(f"📱 {profile['phone']['mobile_phone']}")
        phone_text = " | ".join(phone_parts)
    else:
        phone_text = f"📱 {profile['phone']}"
    
    info_text = f"""📞 *{profile['name']}* - Información de Contacto

🏢 *Empresa:* {profile['name']}
{phone_text}
📍 *Dirección:* {profile['address']}
🕒 *Horarios:* {profile['hours']}
📧 *Email:* {profile['email']}"""

    if profile.get('website'):
        info_text += f"\n🌐 *Web:* {profile['website']}"
    
    return info_text

def get_company_services_text() -> str:
    """
    Genera texto formateado con servicios de la empresa activa
    """
    profile = get_active_company_profile()
    
    services_text = f"🔧 *Nuestros Servicios:*\n\n"
    for i, service in enumerate(profile['services'], 1):
        services_text += f"{i}. {service}\n"
    
    return services_text.strip()

def get_urgency_redirect_message() -> str:
    """
    Genera mensaje de redirección inmediata para urgencias con números de teléfono
    """
    profile = get_active_company_profile()
    
    urgency_text = f"""🚨 *URGENCIA DETECTADA* 🚨

Para atención inmediata de urgencias, por favor comunícate directamente por teléfono:

📞 *Teléfono fijo:* {profile['phone']['landline_phone']}
📱 *Celular de emergencias:* {profile['phone']['emergency_phone']}

🕒 *Horarios:* {profile['hours']}

⚡ *Para urgencias fuera de horario, llama al celular.*

Nuestro equipo técnico te atenderá de inmediato para resolver tu problema.

_Gracias por contactar a {profile['name']}_ 🔥"""
    
    return urgency_text