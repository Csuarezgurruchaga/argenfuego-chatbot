import os
from typing import Dict, Any, Optional

# Perfiles de empresas configurables
COMPANY_PROFILES = {
    "argenfuego": {
        "name": "Argenfuego",
        "bot_name": "Eva",
        "phone": ["4567-8900", "11 3906-1038"],
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
    
    info_text = f"""📞 *{profile['name']}* - Información de Contacto

🏢 *Empresa:* {profile['name']}
📱 *Teléfono:* {profile['phone']}
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