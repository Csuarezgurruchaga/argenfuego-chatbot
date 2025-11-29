import os
import time
import json
import hashlib
import logging
from typing import Dict, Any, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from services.sheets_service import sheets_service
from config.company_profiles import get_active_company_profile

logger = logging.getLogger(__name__)


class ErrorTrigger:
    VALIDATION_REPEAT = "validation_repeat"
    NLU_UNCLEAR = "nlu_unclear"
    GEO_UNCLEAR = "geo_unclear"
    HUMAN_ESCALATION = "human_escalation"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"


def _mask_email(email: str) -> str:
    try:
        if not email or "@" not in email:
            return email
        name, domain = email.split("@", 1)
        masked_name = (name[0] + "***") if name else "***"
        parts = domain.split('.')
        if len(parts) >= 2:
            masked_domain = parts[0][0] + "***" + "." + parts[-1]
        else:
            masked_domain = domain[0] + "***"
        return f"{masked_name}@{masked_domain}"
    except Exception:
        return "***"


def _mask_phone(phone: str) -> str:
    try:
        digits = ''.join([c for c in phone if c.isdigit()])
        if len(digits) <= 4:
            return "***"
        return phone[:3] + "******" + phone[-2:]
    except Exception:
        return "***"


def _sanitize_text(text: str, limit: int = 200) -> str:
    if not text:
        return ""
    text = text.strip()
    return text[:limit]


def _hash_payload(payload: Dict[str, Any]) -> str:
    try:
        data = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(data.encode('utf-8')).hexdigest()
    except Exception:
        return hashlib.sha256(str(payload).encode('utf-8')).hexdigest()


class InMemoryRateLimiter:
    def __init__(self, window_seconds: int = 300):
        self.window_seconds = window_seconds
        self._last_sent_by_key: Dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        last = self._last_sent_by_key.get(key, 0)
        if now - last >= self.window_seconds:
            self._last_sent_by_key[key] = now
            return True
        return False


class ErrorReporter:
    def __init__(self):
        # Use only ENABLE_ERROR_EMAILS (no legacy fallback)
        self.enabled = os.getenv("ENABLE_ERROR_EMAILS", "true").lower() == "true"
        self.error_email = os.getenv("ERROR_LOG_EMAIL", "").strip()
        self.from_email = os.getenv("ERROR_FROM_EMAIL", "notificaciones.chatbot@gmail.com").strip()
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
        self.rate_limiter = InMemoryRateLimiter(window_seconds=int(os.getenv("ERROR_RATE_WINDOW_SEC", "300")))
        self.ses = boto3.client("ses", region_name=self.region)

        if not self.error_email:
            logger.warning("ERROR_LOG_EMAIL not set - error emails disabled")
        if not self.from_email:
            logger.warning("ERROR_FROM_EMAIL not set - usando valor por defecto")

    def _should_send(self, key_parts: List[str], payload: Dict[str, Any]) -> bool:
        if not self.enabled or not self.error_email:
            return False
        unique = "|".join([p for p in key_parts if p]) + "|" + _hash_payload(payload)[:16]
        return self.rate_limiter.allow(unique)

    def _build_email(self, subject: str, summary_lines: List[str], details: Dict[str, Any]) -> Dict[str, str]:
        profile = get_active_company_profile()

        def render_kv(d: Dict[str, Any]) -> str:
            rows = []
            for k, v in d.items():
                rows.append(f"<tr><td style='padding:4px 8px;font-weight:600;'>{k}</td><td style='padding:4px 8px;'>{v}</td></tr>")
            return "\n".join(rows)

        summary_html = "<br/>".join([_sanitize_text(s, 500) for s in summary_lines])
        details_html = render_kv(details)

        html = f"""
        <div style='font-family:Arial, sans-serif;max-width:700px;margin:0 auto;'>
          <div style='background:#111827;color:#fff;padding:12px 16px;border-radius:6px 6px 0 0;'>
            <strong>{profile['name']}</strong> · Chatbot Error Report
          </div>
          <div style='border:1px solid #e5e7eb;border-top:none;padding:16px;border-radius:0 0 6px 6px;'>
            <p style='margin:0 0 12px 0;'>{summary_html}</p>
            <table style='width:100%;border-collapse:collapse;background:#fff;border:1px solid #f3f4f6;'>
              {details_html}
            </table>
          </div>
        </div>
        """

        return {
            "subject": subject,
            "html": html,
            "from_name": f"{profile['bot_name']} · Error Reporter",
        }

    def _send_email(self, subject: str, html: str, from_name: str) -> bool:
        try:
            send_kwargs = {
                "Source": f"{from_name} <{self.from_email or 'notificaciones.chatbot@gmail.com'}>",
                "Destination": {"ToAddresses": [self.error_email]},
                "Message": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                },
            }

            if self.reply_to:
                send_kwargs["ReplyToAddresses"] = [self.reply_to]

            resp = self.ses.send_email(**send_kwargs)
            status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if status == 200:
                logger.info(
                    "Error report email sent | message_id=%s status=%s",
                    resp.get("MessageId", "unknown"),
                    status,
                )
                return True

            logger.error("SES error report send failed | status=%s resp=%s", status, resp)
            return False
        except (ClientError, BotoCoreError) as e:
            logger.error("SES client error sending error report: %s", str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error sending error report: %s", str(e))
            return False

    def capture_experience_issue(self, trigger: str, context: Dict[str, Any]) -> None:
        try:
            profile = get_active_company_profile()
            env = os.getenv("ENV", "prod")

            conversation_id = context.get("conversation_id", "")
            phone_masked = _mask_phone(context.get("numero_telefono", ""))

            summary = [
                f"Trigger: {trigger}",
                f"Company: {profile['name']} | Env: {env}",
                f"Conversation: {conversation_id} | Phone: {phone_masked}",
                f"State: {context.get('estado_actual', '')} ← {context.get('estado_anterior', '')}",
                f"Tipo consulta: {context.get('tipo_consulta', '')} | Timestamp: {context.get('timestamp', '')}",
            ]

            last_user_msgs = context.get("ultimos_mensajes_usuario", [])
            last_bot_msgs = context.get("ultimos_mensajes_bot", [])

            details = {
                "trigger_type": trigger,
                "nlu_snapshot": _sanitize_text(json.dumps(context.get("nlu_snapshot", {}), ensure_ascii=False), 500),
                "validation": _sanitize_text(json.dumps(context.get("validation_info", {}), ensure_ascii=False), 500),
                "user_msgs": _sanitize_text(" | ".join(last_user_msgs), 500),
                "bot_msgs": _sanitize_text(" | ".join(last_bot_msgs), 500),
                "recommended_action": _sanitize_text(context.get("recommended_action", "review validation or NLU patterns"), 200)
            }

            payload_key = [trigger, conversation_id, env]
            # Always attempt to log to Google Sheets (best-effort)
            try:
                sheets_service.append_row(
                    'errors',
                    [
                        context.get('timestamp', ''),
                        env,
                        profile['name'],
                        trigger,
                        conversation_id,
                        phone_masked,
                        context.get('estado_anterior', ''),
                        context.get('estado_actual', ''),
                        _sanitize_text(context.get('nlu_snapshot', {}), 120),
                        _sanitize_text(context.get('validation_info', {}), 120),
                        _sanitize_text(context.get('recommended_action', ''), 120),
                    ]
                )
            except Exception as e:
                logger.error(f"Sheets logging failed: {str(e)}")

            if not self._should_send(payload_key, {**context, "trigger": trigger}):
                return

            subject = f"[Chatbot Error] {trigger} @{profile['name']}"
            payload = self._build_email(subject, summary, details)
            self._send_email(payload["subject"], payload["html"], payload["from_name"])
        except Exception as e:
            logger.error(f"Error building experience issue report: {str(e)}")

    def capture_exception(self, error: Exception, context: Dict[str, Any]) -> None:
        try:
            profile = get_active_company_profile()
            env = os.getenv("ENV", "prod")
            conversation_id = context.get("conversation_id", "")
            phone_masked = _mask_phone(context.get("numero_telefono", ""))

            summary = [
                f"Trigger: exception",
                f"Company: {profile['name']} | Env: {env}",
                f"Conversation: {conversation_id} | Phone: {phone_masked}",
                f"State: {context.get('estado_actual', '')} ← {context.get('estado_anterior', '')}",
            ]

            details = {
                "exception_type": type(error).__name__,
                "message": _sanitize_text(str(error), 500),
                "stack": _sanitize_text(context.get("stack", ""), 1500),
            }

            payload_key = [ErrorTrigger.EXCEPTION, conversation_id, env]
            if not self._should_send(payload_key, {"exception": str(error), **context}):
                return

            subject = f"[Chatbot Error] exception @{profile['name']}"
            payload = self._build_email(subject, summary, details)
            self._send_email(payload["subject"], payload["html"], payload["from_name"])
        except Exception as e:
            logger.error(f"Error building exception report: {str(e)}")


error_reporter = ErrorReporter()


