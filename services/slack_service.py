import os
import logging
import time
import hmac
import hashlib
import json
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class SlackService:
    """Ligera integración con Slack usando Bot Token y firma para slash commands."""

    def __init__(self):
        self.bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        self.signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
        self.default_channel = os.getenv("SLACK_CHANNEL_ID", "")

    # --------------- Firma de Slack ---------------
    def verify_signature(self, timestamp: str, signature: str, body: str) -> bool:
        try:
            sig_basestring = f"v0:{timestamp}:{body}".encode("utf-8")
            digest = hmac.new(self.signing_secret.encode("utf-8"), sig_basestring, hashlib.sha256).hexdigest()
            expected = f"v0={digest}"
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False

    # --------------- Envío de mensajes ---------------
    def post_message(self, channel: str, text: str, thread_ts: Optional[str] = None, blocks: Optional[list] = None) -> Optional[str]:
        if not self.bot_token:
            logger.error("SLACK_BOT_TOKEN no configurado")
            return None

        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json; charset=utf-8"}
        payload = {"channel": channel or self.default_channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks

        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Error enviando mensaje a Slack: {data}")
            return None
        return data.get("ts")

    def open_modal(self, trigger_id: str, view: dict) -> bool:
        if not self.bot_token:
            logger.error("SLACK_BOT_TOKEN no configurado")
            return False
        url = "https://slack.com/api/views.open"
        headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json; charset=utf-8"}
        payload = {"trigger_id": trigger_id, "view": view}
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Error abriendo modal: {data}")
            return False
        return True

    def respond_interaction(self, response_url: str, text: str, replace_original: bool = False) -> bool:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"text": text, "replace_original": replace_original}
        resp = requests.post(response_url, headers=headers, data=json.dumps(payload), timeout=10)
        return resp.status_code == 200


slack_service = SlackService()


