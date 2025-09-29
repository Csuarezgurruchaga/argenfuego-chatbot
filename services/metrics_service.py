import os
import time
import logging
from typing import Dict, Any

from services.sheets_service import sheets_service

logger = logging.getLogger(__name__)


class MetricsService:
    def __init__(self):
        self.enabled = os.getenv('ENABLE_SHEETS_METRICS', 'false').lower() == 'true'
        self.window_seconds = int(os.getenv('METRICS_FLUSH_SECONDS', '300'))
        self._last_flush = 0
        self._day_cache: Dict[str, Dict[str, float]] = {}

    def _sanitize_key(self, value: str, fallback: str = "generic") -> str:
        if not value:
            return fallback
        sanitized = ''.join(ch.lower() if ch.isalnum() else '_' for ch in value)
        sanitized = sanitized.strip('_')
        return sanitized or fallback

    def _key(self) -> str:
        return time.strftime('%Y-%m-%d')

    def _inc(self, metric: str, amount: float = 1.0):
        if not self.enabled:
            return
        day = self._key()
        bucket = self._day_cache.setdefault(day, {})
        bucket[metric] = bucket.get(metric, 0.0) + amount

    # Hooks de negocio
    def on_conversation_started(self):
        self._inc('conv_started')

    def on_conversation_finished(self):
        self._inc('conv_finished')

    def on_lead_sent(self):
        self._inc('leads_sent')

    def on_intent(self, intent: str):
        self._inc(f'intent_{intent}')

    def on_human_request(self):
        self._inc('human_requests')

    def on_geo_caba(self):
        self._inc('geo_caba')

    def on_geo_provincia(self):
        self._inc('geo_provincia')

    def on_message_attempt(self, kind: str = 'generic'):
        key = self._sanitize_key(kind)
        self._inc('msg_attempt_total')
        self._inc(f'msg_attempt_{key}')

    def on_message_success(self, kind: str = 'generic'):
        key = self._sanitize_key(kind)
        self._inc('msg_success_total')
        self._inc(f'msg_success_{key}')

    def on_message_failure(self, kind: str = 'generic'):
        key = self._sanitize_key(kind)
        self._inc('msg_failure_total')
        self._inc(f'msg_failure_{key}')

    def on_message_delivered(self, kind: str = 'generic'):
        key = self._sanitize_key(kind)
        self._inc('msg_delivered_total')
        self._inc(f'msg_delivered_{key}')

    def on_message_status(self, status: str, kind: str = 'generic'):
        status_key = self._sanitize_key(status, 'unknown')
        kind_key = self._sanitize_key(kind)
        self._inc(f'msg_status_{status_key}')
        self._inc(f'msg_status_{status_key}_{kind_key}')

    def on_handoff_started(self):
        self._inc('handoff_started')

    def on_handoff_resolved(self):
        self._inc('handoff_resolved')

    # Hooks técnicos
    def on_nlu_unclear(self):
        self._inc('nlu_unclear')

    def on_exception(self):
        self._inc('exceptions')

    # Flush
    def flush_if_needed(self):
        if not self.enabled:
            return False
        now = time.time()
        if now - self._last_flush < self.window_seconds:
            return False
        self._last_flush = now
        try:
            day = self._key()
            bucket = self._day_cache.get(day, {})
            if not bucket:
                return False
            # Enviar a BUSINESS
            sheets_service.append_row('business', [
                day,
                int(bucket.get('conv_started', 0)),
                int(bucket.get('conv_finished', 0)),
                int(bucket.get('leads_sent', 0)),
                int(bucket.get('human_requests', 0)),
                int(bucket.get('intent_presupuesto', 0)),
                int(bucket.get('intent_visita_tecnica', 0)),
                int(bucket.get('intent_urgencia', 0)),
                int(bucket.get('intent_otras', 0)),
                int(bucket.get('geo_caba', 0)),
                int(bucket.get('geo_provincia', 0)),
                int(bucket.get('msg_attempt_total', 0)),
                int(bucket.get('msg_success_total', 0)),
                int(bucket.get('msg_failure_total', 0)),
                int(bucket.get('msg_delivered_total', 0)),
                int(bucket.get('msg_status_queued', 0)),
                int(bucket.get('msg_status_sent', 0)),
                int(bucket.get('msg_status_delivered', 0)),
                int(bucket.get('msg_status_failed', 0)),
                int(bucket.get('msg_status_undelivered', 0)),
                int(bucket.get('msg_status_read', 0)),
                int(bucket.get('handoff_started', 0)),
                int(bucket.get('handoff_resolved', 0)),
            ])
            # Enviar a TECH
            sheets_service.append_row('tech', [
                day,
                int(bucket.get('nlu_unclear', 0)),
                int(bucket.get('exceptions', 0)),
            ])
            return True
        except Exception as e:
            logger.error(f'Metrics flush failed: {str(e)}')
            return False


metrics_service = MetricsService()
