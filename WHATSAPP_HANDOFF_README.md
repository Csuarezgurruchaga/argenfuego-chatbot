# WhatsApp Handoff System

## Overview

El sistema de handoff ha sido migrado de Slack a WhatsApp usando Twilio. Ahora los agentes humanos reciben notificaciones directamente en su WhatsApp y pueden responder a los clientes desde la misma plataforma.

## Configuration

### Environment Variables Required

```bash
# WhatsApp Agent Configuration
AGENT_WHATSAPP_NUMBER=+5491135722871  # Número del agente (formato internacional)

# Twilio Configuration (existing)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886  # Número de Twilio WhatsApp
```

## How It Works

### 1. Handoff Detection
- Cuando un cliente solicita hablar con un humano, el bot detecta la solicitud
- El bot responde: "Te conecto con un agente humano ahora mismo. 👩🏻‍💼👨🏻‍💼"
- Se activa el estado `ATENDIDO_POR_HUMANO`

### 2. Agent Notification
- El agente recibe un mensaje en su WhatsApp con:
  - Información del cliente (nombre y número)
  - Mensaje que disparó el handoff
  - Último mensaje del cliente
  - Instrucciones para responder

### 3. Agent Response
- El agente puede responder directamente desde su WhatsApp
- Sus mensajes se envían al cliente con el prefijo "👨‍💼 *Agente:*"
- El agente recibe confirmación de que su mensaje fue enviado

### 4. Resolution (Mejorado)
- Para finalizar la conversación, el agente envía: `ok`, `listo`, `/r`, etc.
- Se envía pregunta al cliente: "¿Hay algo más en lo que pueda ayudarte?"
- Si el cliente no responde en 10 minutos, se cierra automáticamente
- Si el cliente responde, continúa la conversación

## Agent Commands

| Command | Description |
|---------|-------------|
| `/resuelto`, `/r` | Envía pregunta de resolución al cliente |
| `ok`, `listo`, `done` | Comandos naturales para resolución |
| `/resolved`, `/cerrar`, `/close`, `/fin`, `/end` | Alias para resolución |

### Comandos Cortos y Naturales
- **`/r`** - Resolución rápida
- **`ok`** - Comando natural más usado
- **`listo`** - Comando en español
- **`done`** - Comando en inglés

## Message Flow

```
Client → Bot: "Quiero hablar con un humano"
Bot → Client: "Te conecto con un agente humano ahora mismo..."
Bot → Agent: "🔄 Nueva solicitud de agente humano\nCliente: Juan (+5491123456789)\n..."

Client → Bot: "Tengo un problema con mi pedido"
Bot → Agent: "💬 Nuevo mensaje del cliente\nCliente: Juan (+5491123456789)\nMensaje: Tengo un problema con mi pedido"

Agent → Bot: "Hola Juan, ¿en qué puedo ayudarte?"
Bot → Client: "👨‍💼 Agente: Hola Juan, ¿en qué puedo ayudarte?"
Bot → Agent: "✅ Mensaje enviado al cliente +5491123456789"

Agent → Bot: "ok"
Bot → Client: "👨‍💼 Agente: ¿Hay algo más en lo que pueda ayudarte?"
Bot → Agent: "✅ Pregunta de resolución enviada al cliente +5491123456789. Se cerrará automáticamente si no responde en 10 minutos."

# Si cliente no responde en 10 minutos:
Bot → Client: "¡Gracias por tu consulta! Damos por finalizada esta conversación. ✅"

# Si cliente responde:
Client → Bot: "Sí, tengo otra pregunta"
Bot → Agent: "💬 Nuevo mensaje del cliente\nCliente: Juan (+5491123456789)\nMensaje: Sí, tengo otra pregunta"
```

## Technical Implementation

### Files Modified
- `services/whatsapp_handoff_service.py` - New service for WhatsApp handoff
- `main.py` - Modified webhook to handle agent messages
- `chatbot/models.py` - Added `handoff_notified` field

### Key Features
- **Agent Detection**: Automatically detects messages from the agent's WhatsApp number
- **Bidirectional Communication**: Agent can respond to clients directly
- **Smart Resolution**: Natural commands (ok, listo, /r) with client confirmation
- **Auto Timeout**: Conversations close automatically after 10 minutes of no response
- **Error Handling**: Comprehensive error handling and logging
- **Confirmation Messages**: Agent receives confirmation of sent messages
- **Improved UX**: Short commands and natural language support

## Migration from Slack

The system has been completely migrated from Slack to WhatsApp:
- ❌ Removed: Slack channel notifications
- ❌ Removed: Slack thread management
- ❌ Removed: Slack button interactions
- ✅ Added: Direct WhatsApp notifications to agent
- ✅ Added: WhatsApp-based agent responses
- ✅ Added: WhatsApp command system

## Testing

To test the handoff system:

1. Set up the `AGENT_WHATSAPP_NUMBER` environment variable
2. Send a message to the bot requesting human assistance
3. Verify the agent receives the notification
4. Have the agent respond to test bidirectional communication
5. Use `/resuelto` command to test resolution

## Troubleshooting

### Common Issues

1. **Agent not receiving notifications**
   - Check `AGENT_WHATSAPP_NUMBER` is set correctly
   - Verify Twilio credentials are valid
   - Check logs for error messages

2. **Agent messages not reaching clients**
   - Verify agent's WhatsApp number matches `AGENT_WHATSAPP_NUMBER`
   - Check Twilio webhook configuration
   - Review error logs

3. **Resolution commands not working**
   - Ensure agent sends exact command (case insensitive)
   - Check for typos in command
   - Verify conversation is in handoff state

### Logs to Monitor

```bash
# Successful handoff notification
✅ Notificación de handoff enviada al agente para cliente +5491123456789

# Agent message processing
Procesando mensaje del agente +5491135722871: Hola, ¿en qué puedo ayudarte?

# Message delivery confirmation
✅ Mensaje enviado al cliente +5491123456789
```
