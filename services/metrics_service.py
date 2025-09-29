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

    # Hooks técnicos
    def on_nlu_unclear(self):
        self._inc('nlu_unclear')

    def on_exception(self):
        self._inc('exceptions')

    def on_validation_failure(self, field: str):
        self._inc(f'validation_fail_{field}')

    # Hooks de estado de entrega de mensajes
    def on_message_sent(self):
        self._inc('messages_sent')

    def on_message_delivered(self):
        self._inc('messages_delivered')

    def on_message_failed(self):
        self._inc('messages_failed')

    def on_message_undelivered(self):
        self._inc('messages_undelivered')

    def on_message_read(self):
        self._inc('messages_read')

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
                int(bucket.get('messages_sent', 0)),
                int(bucket.get('messages_delivered', 0)),
                int(bucket.get('messages_failed', 0)),
                int(bucket.get('messages_undelivered', 0)),
                int(bucket.get('messages_read', 0)),
            ])
            # Enviar a TECH
            sheets_service.append_row('tech', [
                day,
                int(bucket.get('nlu_unclear', 0)),
                int(bucket.get('exceptions', 0)),
                int(bucket.get('validation_fail_email', 0)),
                int(bucket.get('validation_fail_direccion', 0)),
                int(bucket.get('validation_fail_horario_visita', 0)),
                int(bucket.get('validation_fail_descripcion', 0)),
            ])
            return True
        except Exception as e:
            logger.error(f'Metrics flush failed: {str(e)}')
            return False


metrics_service = MetricsService()


