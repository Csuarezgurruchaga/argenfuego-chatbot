"""
OpenTelemetry Metrics Service for Datadog integration.

This service configures OpenTelemetry to send metrics directly to Datadog
via OTLP/HTTP without requiring an Agent or Collector.
"""

import os
import logging
from typing import Optional

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

logger = logging.getLogger(__name__)


class OTelMetricsService:
    """
    Service to manage OpenTelemetry metrics export to Datadog.
    
    Metrics are sent directly to Datadog via OTLP/HTTP.
    """
    
    def __init__(self):
        self.enabled = os.getenv("OTEL_METRICS_ENABLED", "false").lower() == "true"
        self._initialized = False
        self._meter: Optional[metrics.Meter] = None
        
        # Metric instruments
        self.http_requests_counter = None
        self.http_duration_histogram = None
        self.whatsapp_messages_sent = None
        self.whatsapp_send_errors = None
        self.ses_emails_sent = None
        self.ses_emails_failed = None
        self.handoff_queue_size = None
        self.leads_processed = None
    
    def init_metrics(self):
        """
        Initialize OpenTelemetry metrics with Datadog exporter.
        
        Call this once at application startup.
        """
        if not self.enabled:
            logger.info("OpenTelemetry metrics disabled (OTEL_METRICS_ENABLED != true)")
            return
        
        if self._initialized:
            logger.warning("OpenTelemetry metrics already initialized")
            return
        
        try:
            # Get configuration from environment
            dd_api_key = os.getenv("DD_API_KEY", "")
            dd_site = os.getenv("DD_SITE", "datadoghq.com")
            dd_service = os.getenv("DD_SERVICE", "chatbot")
            dd_env = os.getenv("DD_ENV", "production")
            dd_version = os.getenv("DD_VERSION", "1.0.0")
            
            if not dd_api_key:
                logger.error("DD_API_KEY not set, OpenTelemetry metrics will not be sent")
                return
            
            # Build the OTLP HTTP endpoint for Datadog
            # Port 4318 is the standard OTLP HTTP port (4317 is gRPC)
            otlp_endpoint = f"https://otlp.{dd_site}:4318/v1/metrics"
            
            logger.info(f"Configuring OpenTelemetry metrics for service '{dd_service}' -> {otlp_endpoint}")
            
            # Create resource with service information
            resource = Resource.create({
                SERVICE_NAME: dd_service,
                "deployment.environment": dd_env,
                "service.version": dd_version,
            })
            
            # Configure the OTLP HTTP exporter with Datadog API key
            exporter = OTLPMetricExporter(
                endpoint=otlp_endpoint,
                headers={"dd-api-key": dd_api_key},
            )
            
            # Create a periodic reader that exports every 60 seconds
            reader = PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=60000,  # 60 seconds
            )
            
            # Create and set the MeterProvider
            provider = MeterProvider(
                resource=resource,
                metric_readers=[reader],
            )
            metrics.set_meter_provider(provider)
            
            # Get a meter for creating instruments
            self._meter = metrics.get_meter("chatbot.metrics", version="1.0.0")
            
            # Create metric instruments
            self._create_instruments()
            
            self._initialized = True
            logger.info(f"OpenTelemetry metrics initialized successfully for '{dd_service}'")
            
        except Exception as e:
            logger.error(f"Failed to initialize OpenTelemetry metrics: {e}")
    
    def _create_instruments(self):
        """Create all metric instruments."""
        if not self._meter:
            return
        
        # HTTP metrics
        self.http_requests_counter = self._meter.create_counter(
            name="chatbot.http.requests",
            description="Total HTTP requests",
            unit="1",
        )
        
        self.http_duration_histogram = self._meter.create_histogram(
            name="chatbot.http.duration",
            description="HTTP request duration in milliseconds",
            unit="ms",
        )
        
        # WhatsApp metrics
        self.whatsapp_messages_sent = self._meter.create_counter(
            name="chatbot.whatsapp.messages_sent",
            description="WhatsApp messages sent successfully",
            unit="1",
        )
        
        self.whatsapp_send_errors = self._meter.create_counter(
            name="chatbot.whatsapp.send_errors",
            description="WhatsApp message send errors",
            unit="1",
        )
        
        # SES Email metrics
        self.ses_emails_sent = self._meter.create_counter(
            name="chatbot.ses.emails_sent",
            description="Emails sent successfully via SES",
            unit="1",
        )
        
        self.ses_emails_failed = self._meter.create_counter(
            name="chatbot.ses.emails_failed",
            description="Email send failures via SES",
            unit="1",
        )
        
        # Handoff queue gauge (using observable gauge for current value)
        # We'll use a callback to get the current queue size
        self._handoff_queue_size_value = 0
        self.handoff_queue_size = self._meter.create_observable_gauge(
            name="chatbot.handoff.queue_size",
            description="Current size of the handoff queue",
            unit="1",
            callbacks=[self._get_handoff_queue_size],
        )
        
        # Leads processed
        self.leads_processed = self._meter.create_counter(
            name="chatbot.leads.processed",
            description="Total leads processed successfully",
            unit="1",
        )
    
    def _get_handoff_queue_size(self, options):
        """Callback for observable gauge to get current handoff queue size."""
        yield metrics.Observation(self._handoff_queue_size_value)
    
    def set_handoff_queue_size(self, size: int):
        """Update the handoff queue size value for the gauge."""
        self._handoff_queue_size_value = size
    
    # Convenience methods for recording metrics
    def record_http_request(self, endpoint: str, method: str, status_code: int):
        """Record an HTTP request metric."""
        if self.http_requests_counter:
            status_class = f"{status_code // 100}xx"
            self.http_requests_counter.add(
                1,
                attributes={
                    "endpoint": endpoint,
                    "method": method,
                    "status_code": str(status_code),
                    "status_class": status_class,
                },
            )
    
    def record_http_duration(self, endpoint: str, method: str, duration_ms: float):
        """Record HTTP request duration in milliseconds."""
        if self.http_duration_histogram:
            self.http_duration_histogram.record(
                duration_ms,
                attributes={
                    "endpoint": endpoint,
                    "method": method,
                },
            )
    
    def record_whatsapp_sent(self):
        """Record a successful WhatsApp message send."""
        if self.whatsapp_messages_sent:
            self.whatsapp_messages_sent.add(1)
    
    def record_whatsapp_error(self, error_type: str = "unknown"):
        """Record a WhatsApp message send error."""
        if self.whatsapp_send_errors:
            self.whatsapp_send_errors.add(1, attributes={"error_type": error_type})
    
    def record_email_sent(self):
        """Record a successful email send via SES."""
        if self.ses_emails_sent:
            self.ses_emails_sent.add(1)
    
    def record_email_failed(self, error_type: str = "unknown"):
        """Record an email send failure via SES."""
        if self.ses_emails_failed:
            self.ses_emails_failed.add(1, attributes={"error_type": error_type})
    
    def record_lead_processed(self):
        """Record a successfully processed lead."""
        if self.leads_processed:
            self.leads_processed.add(1)


# Global instance
otel_metrics = OTelMetricsService()


def init_metrics():
    """Initialize OpenTelemetry metrics. Call once at app startup."""
    otel_metrics.init_metrics()

