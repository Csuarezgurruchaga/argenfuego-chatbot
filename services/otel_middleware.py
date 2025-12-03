"""
OpenTelemetry HTTP Metrics Middleware for FastAPI.

This middleware automatically records HTTP request metrics (count and duration)
for all incoming requests.
"""

import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from services.otel_metrics_service import otel_metrics

logger = logging.getLogger(__name__)


class OTelMetricsMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that automatically records HTTP metrics.
    
    Records:
    - chatbot.http.requests: Counter of requests by endpoint, method, and status
    - chatbot.http.duration: Histogram of request duration in milliseconds
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip metrics if not enabled
        if not otel_metrics.enabled:
            return await call_next(request)
        
        # Get request info
        method = request.method
        # Use path template if available, otherwise use path
        endpoint = request.url.path
        
        # Normalize endpoint to avoid high cardinality
        # Remove trailing slashes and limit depth
        endpoint = self._normalize_endpoint(endpoint)
        
        # Record start time
        start_time = time.perf_counter()
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration in milliseconds
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        # Record metrics
        try:
            otel_metrics.record_http_request(
                endpoint=endpoint,
                method=method,
                status_code=response.status_code,
            )
            otel_metrics.record_http_duration(
                endpoint=endpoint,
                method=method,
                duration_ms=duration_ms,
            )
        except Exception as e:
            # Don't let metrics recording break the request
            logger.debug(f"Failed to record HTTP metrics: {e}")
        
        return response
    
    def _normalize_endpoint(self, path: str) -> str:
        """
        Normalize endpoint path to reduce cardinality.
        
        - Removes trailing slashes
        - Groups dynamic segments (e.g., /users/123 -> /users/{id})
        """
        # Remove trailing slash
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        
        # Split path into segments
        segments = path.split("/")
        normalized_segments = []
        
        for segment in segments:
            if not segment:
                continue
            
            # Check if segment looks like an ID (numeric or UUID-like)
            if self._is_dynamic_segment(segment):
                normalized_segments.append("{id}")
            else:
                normalized_segments.append(segment)
        
        return "/" + "/".join(normalized_segments) if normalized_segments else "/"
    
    def _is_dynamic_segment(self, segment: str) -> bool:
        """
        Check if a path segment is likely a dynamic value (ID).
        
        Returns True for:
        - Pure numeric values
        - UUID-like strings (contains hyphens and is long)
        - Phone numbers (starts with + or is mostly digits)
        """
        # Pure numeric
        if segment.isdigit():
            return True
        
        # UUID-like (e.g., 550e8400-e29b-41d4-a716-446655440000)
        if "-" in segment and len(segment) > 20:
            return True
        
        # Phone number-like (starts with + or mostly digits)
        if segment.startswith("+") or (len(segment) > 8 and sum(c.isdigit() for c in segment) > len(segment) * 0.7):
            return True
        
        return False

