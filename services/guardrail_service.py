import os
import re
import unicodedata
from typing import Dict, List, Optional

from config.company_profiles import get_active_company_profile


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return text


class GuardrailService:
    """
    Regex-based topic guardrail (balanced mode behavior).
    Controlled by env var GUARDRAIL_LLM_ENABLED=true|false (true = enabled).
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("GUARDRAIL_LLM_ENABLED", "false").lower() == "true"

        profile = get_active_company_profile()
        self.allowed_topics: List[str] = [t.strip() for t in profile.get("allowed_topics", [])]
        # Optional per-company related keywords that are commerce-adjacent but not core topics
        self.related_keywords: List[str] = [k.strip() for k in profile.get("related_keywords", [])]

        # Generic commerce words to soften redirects
        self.commercial_terms: List[str] = [
            "comprar", "compra", "venta", "presupuesto", "cotizacion", "cotización",
            "precio", "lista de precios", "stock", "proveer", "provision", "proveedor"
        ]

        # Off-topic obvious buckets (balanced: used for hard_block only if clear)
        self.offtopic_buckets: List[str] = [
            "clima", "climate", "tiempo", "futbol", "football", "deportes", "chiste",
            "meme", "politica", "politics", "musica", "música", "receta", "juego"
        ]

        # Build regex lists from topics (simple lexical signals). For Spanish, include common synonyms
        topic_to_keywords = {
            "incendios": ["incendio", "prevencion de incendios", "señalizacion", "rociadores"],
            "extintores": ["extintor", "matafuego", "mata fuego", "recarga", "mantenimiento"],
            "presupuestos": ["presupuesto", "cotizacion", "cotización", "precio", "costo"],
            "visitas técnicas": ["visita tecnica", "visita técnica", "relevamiento", "inspeccion"],
            "urgencias": ["urgencia", "emergencia", "llamar urgente", "salida de emergencia"],
            "contacto": ["contacto", "telefono", "teléfono", "whatsapp", "mail", "email"],
        }

        # Expand from allowed_topics only
        self.allowed_keywords: List[str] = []
        for topic in self.allowed_topics:
            self.allowed_keywords.extend(topic_to_keywords.get(topic, [topic]))

        # Compile regex patterns (word-ish boundaries tolerant to spaces/accents removed by _normalize)
        self.allowed_patterns = [re.compile(re.escape(_normalize(k))) for k in self.allowed_keywords]
        self.related_patterns = [re.compile(re.escape(_normalize(k))) for k in self.related_keywords]
        self.offtopic_patterns = [re.compile(re.escape(_normalize(k))) for k in self.offtopic_buckets]

    def _score(self, text_norm: str) -> Dict[str, int]:
        score_allowed = sum(1 for p in self.allowed_patterns if p.search(text_norm))
        score_related = sum(1 for p in self.related_patterns if p.search(text_norm))
        score_commercial = sum(1 for term in self.commercial_terms if _normalize(term) in text_norm)
        score_offtopic = sum(1 for p in self.offtopic_patterns if p.search(text_norm))
        return {
            "allowed": score_allowed,
            "related": score_related,
            "commercial": score_commercial,
            "offtopic": score_offtopic,
        }

    def evaluate_user_input(self, text: str) -> Dict[str, Optional[str]]:
        """
        Returns a dict: {decision, reason, suggestion}
        decision: allow | soft_redirect | hard_block
        """
        if not self.enabled:
            return {"decision": "allow", "reason": None, "suggestion": None}

        text_norm = _normalize(text)
        s = self._score(text_norm)

        # Hard block only if clearly off-topic and no commercial/related intent
        if s["offtopic"] >= 1 and s["allowed"] == 0 and s["related"] == 0 and s["commercial"] == 0:
            return {
                "decision": "hard_block",
                "reason": "Off-topic claro detectado",
                "suggestion": "Podemos ayudarte con extintores, presupuestos o visitas técnicas. ¿Sobre qué te gustaría consultar?",
            }

        # Allow if clear allowed signal
        if s["allowed"] >= 1:
            return {
                "decision": "allow",
                "reason": "Consulta dentro de tópicos permitidos",
                "suggestion": None,
            }

        # Soft redirect for related or commercial intents
        if s["related"] >= 1 or s["commercial"] >= 1:
            return {
                "decision": "soft_redirect",
                "reason": "Consulta comercial/relacionada pero no núcleo del dominio",
                "suggestion": "Manejamos principalmente extintores y servicios contra incendio. ¿Querés un presupuesto o coordinar una visita técnica?",
            }

        # Default balanced: soft redirect gently
        return {
            "decision": "soft_redirect",
            "reason": "No hay señales claras; mantenemos foco del servicio",
            "suggestion": "¿Te interesa presupuesto de extintores o coordinar una visita técnica?",
        }

    def enforce_on_llm_output(self, text: str) -> str:
        # No-op for regex-only mode
        return text


guardrail_service = GuardrailService()


