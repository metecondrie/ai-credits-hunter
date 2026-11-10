"""Clasificacion semantica de ofertas candidatas mediante IA.

Recorrido: candidato (descripcion + fragmento de evidencia + URL) -> prompt ->
modelo configurado (con cadena de fallback) -> JSON estructurado -> persistencia
en `ai_assessment` (tabla SEPARADA: la evidencia original nunca se modifica y
la interpretacion de la IA JAMAS se presenta como verificacion oficial).

Bloqueos efectivos (requisitos 6 y 7):
- Sin clave habilitada en la cadena -> modo determinista, sin llamadas.
- Limite diario alcanzado -> BLOQUEADO_POR_LIMITE.
- Costo no verificable como gratuito y sin autorizacion explicita
  (allow_unverified_cost) -> BLOQUEADO_COSTO_NO_VERIFICADO. No se asume
  gratuidad por marca ni familia de modelo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import ai_providers, ai_settings
from .ai_providers import COST_DEMO, COST_FREE, COST_UNKNOWN, ProviderError
from .ai_settings import AISettingsStore
from .models import Candidate

BENEFIT_TYPES = ("FREE_TIER", "TRIAL", "CREDITS", "DISCOUNT", "OFF_PEAK",
                 "STUDENT", "ANUNCIO", "OTRO")
ARGENTINA_VALUES = ("DISPONIBLE_POR_DECLARACION", "ARGENTINA_NO_CONFIRMADA",
                    "NO_APLICA_ARGENTINA", "REQUIERE_REVISION_GEO")
CONFIDENCE_VALUES = ("alta", "media", "baja")

# Motivos de no-clasificacion (estados explicitos, nunca silenciosos)
BLOCKED_NO_CHAIN = "SIN_CADENA_CONFIGURADA"
BLOCKED_LIMIT = "BLOQUEADO_POR_LIMITE"
BLOCKED_COST = "BLOQUEADO_COSTO_NO_VERIFICADO"
BLOCKED_NO_KEY = "SIN_API_KEY"
BLOCKED_ALL_FAILED = "TODOS_LOS_MODELOS_FALLARON"

SYSTEM_PROMPT = (
    "Sos un auditor de ofertas de servicios de IA. Evaluas UNA oferta candidata "
    "a partir de su descripcion, el fragmento de evidencia literal y la URL. "
    "Respondes EXCLUSIVAMENTE con un objeto JSON valido, sin texto adicional, "
    "con estas claves exactas:\n"
    '{"is_offer": true|false, '
    '"benefit_type": "FREE_TIER|TRIAL|CREDITS|DISCOUNT|OFF_PEAK|STUDENT|ANUNCIO|OTRO", '
    '"conditions": "condiciones del beneficio o \'No especificadas\'", '
    '"restrictions": "restricciones (tarjeta, region, renovacion) o \'Desconocidas\'", '
    '"argentina_eligibility": "DISPONIBLE_POR_DECLARACION|ARGENTINA_NO_CONFIRMADA|'
    'NO_APLICA_ARGENTINA|REQUIERE_REVISION_GEO", '
    '"confidence": "alta|media|baja", '
    '"justification": "explicacion breve citando la evidencia"}\n'
    "Reglas: no inventes datos fuera de la evidencia; ante la duda usa "
    "ARGENTINA_NO_CONFIRMADA y confidence baja; tu salida es una INTERPRETACION, "
    "no una verificacion oficial."
)

MAX_SNIPPET_CHARS = 1500


@dataclass
class AIAssessment:
    """Interpretacion estructurada devuelta por la IA (NO es verificacion oficial)."""

    is_offer: Optional[bool]
    benefit_type: str
    conditions: str
    restrictions: str
    argentina_eligibility: str
    confidence: str
    justification: str
    raw_response: str = ""


@dataclass
class ClassifyOutcome:
    """Resultado del intento de clasificacion (exito o bloqueo explicito)."""

    ok: bool
    assessment: Optional[AIAssessment] = None
    provider: str = ""
    model: str = ""
    cost_status: str = ""
    tokens: int = 0
    blocked: Optional[str] = None
    detail: str = ""
    attempts: List[Dict[str, str]] = field(default_factory=list)


def build_messages(c: Candidate) -> List[Dict[str, str]]:
    """Pasa a la IA la descripcion, el fragmento de evidencia y la URL."""
    snippet = (c.evidence_snippet or "")[:MAX_SNIPPET_CHARS]
    user = (
        f"OFERTA CANDIDATA\n"
        f"- Proveedor: {c.provider_key}\n"
        f"- Producto: {c.product}\n"
        f"- Titulo: {c.title}\n"
        f"- Descripcion/beneficio: {c.benefit}\n"
        f"- Tipo preliminar (reglas): {c.offer_type}\n"
        f"- Precio base: {c.price_baseline} | Precio oferta: {c.price_offer} {c.price_unit or ''}\n"
        f"- URL de evidencia: {c.evidence_url}\n"
        f"- URL oficial: {c.official_url}\n"
        f"FRAGMENTO DE EVIDENCIA LITERAL:\n\"\"\"\n{snippet}\n\"\"\"\n"
        f"Evalua si es una oferta real y devolve el JSON pedido."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_response(text: str) -> AIAssessment:
    """Parseo robusto: fence markdown, JSON embebido o JSON directo.

    Si no hay JSON valido o faltan claves, se levanta ValueError: NUNCA se
    fabrica una interpretacion a partir de texto no estructurado.
    """
    candidate_text = None
    fence = _JSON_FENCE.search(text or "")
    if fence:
        candidate_text = fence.group(1)
    else:
        obj = _JSON_OBJECT.search(text or "")
        if obj:
            candidate_text = obj.group(0)
    if not candidate_text:
        raise ValueError("La respuesta no contiene un objeto JSON.")

    try:
        data = json.loads(candidate_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalido en la respuesta: {exc}")

    required = {"is_offer", "benefit_type", "conditions", "restrictions",
                "argentina_eligibility", "confidence", "justification"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Faltan claves en la respuesta: {sorted(missing)}")

    benefit_type = str(data["benefit_type"]).upper()
    if benefit_type not in BENEFIT_TYPES:
        benefit_type = "OTRO"
    argentina = str(data["argentina_eligibility"]).upper()
    if argentina not in ARGENTINA_VALUES:
        argentina = "ARGENTINA_NO_CONFIRMADA"
    confidence = str(data["confidence"]).lower()
    if confidence not in CONFIDENCE_VALUES:
        confidence = "baja"

    return AIAssessment(
        is_offer=bool(data["is_offer"]),
        benefit_type=benefit_type,
        conditions=str(data["conditions"])[:1000],
        restrictions=str(data["restrictions"])[:1000],
        argentina_eligibility=argentina,
        confidence=confidence,
        justification=str(data["justification"])[:2000],
        raw_response=(text or "")[:8000],
    )


def _attempt_target(target: Dict[str, str], messages, store: AISettingsStore,
                    http_post=None) -> ClassifyOutcome:
    """Un intento contra un (proveedor, modelo) concreto de la cadena."""
    pid, model = target["provider"], target["model"]
    provider = ai_providers.get_provider(pid)
    settings = store.provider_settings(pid)

    allowed, reason = store.check_limits(pid)
    if not allowed:
        return ClassifyOutcome(ok=False, provider=pid, model=model,
                               blocked=BLOCKED_LIMIT, detail=reason)

    if provider.needs_key:
        api_key = store.keys.get_key(pid)
        if not api_key:
            return ClassifyOutcome(ok=False, provider=pid, model=model,
                                   blocked=BLOCKED_NO_KEY,
                                   detail=f"Sin API key guardada para {pid}.")
    else:
        api_key = ""

    # Regla de costo: verificar gratuidad o exigir autorizacion explicita.
    cost_status = provider.assess_cost(model, api_key=api_key,
                                       base_url=settings.get("base_url", ""))
    if cost_status == COST_UNKNOWN and not settings.get("allow_unverified_cost"):
        return ClassifyOutcome(
            ok=False, provider=pid, model=model, cost_status=cost_status,
            blocked=BLOCKED_COST,
            detail=(f"Costo de '{model}' no verificable como gratuito en {pid} "
                    "y el usuario no autorizo llamadas con costo no verificado."),
        )

    try:
        result = provider.chat(api_key, model, messages,
                               base_url=settings.get("base_url", ""),
                               http_post=http_post)
    except ProviderError as exc:
        store.record_usage(pid, error=str(exc), quota_exhausted=exc.quota_exhausted)
        return ClassifyOutcome(ok=False, provider=pid, model=model,
                               cost_status=cost_status,
                               blocked=BLOCKED_ALL_FAILED, detail=str(exc))

    store.record_usage(pid, tokens=result.tokens)
    try:
        assessment = parse_response(result.text)
    except ValueError as exc:
        store.record_usage(pid, error=f"parseo: {exc}")
        return ClassifyOutcome(ok=False, provider=pid, model=model,
                               cost_status=cost_status, tokens=result.tokens,
                               blocked=BLOCKED_ALL_FAILED,
                               detail=f"Respuesta no estructurada: {exc}")

    return ClassifyOutcome(ok=True, assessment=assessment, provider=pid, model=model,
                           cost_status=cost_status, tokens=result.tokens)


def classify_candidate(c: Candidate, store: Optional[AISettingsStore] = None,
                       http_post=None) -> ClassifyOutcome:
    """Clasifica un candidato recorriendo la cadena principal + fallbacks."""
    store = store or AISettingsStore()
    chain = store.routing_chain()
    if not chain:
        return ClassifyOutcome(ok=False, blocked=BLOCKED_NO_CHAIN,
                               detail="Sin modelo principal ni fallbacks habilitados; "
                                      "el cazador sigue en modo determinista.")

    messages = build_messages(c)
    attempts: List[Dict[str, str]] = []
    saw_limit = saw_cost = saw_no_key = False

    for target in chain:
        outcome = _attempt_target(target, messages, store, http_post=http_post)
        if outcome.ok:
            outcome.attempts = attempts
            return outcome
        attempts.append({"provider": outcome.provider, "model": outcome.model,
                         "blocked": outcome.blocked or "", "detail": outcome.detail[:200]})
        saw_limit = saw_limit or outcome.blocked == BLOCKED_LIMIT
        saw_cost = saw_cost or outcome.blocked == BLOCKED_COST
        saw_no_key = saw_no_key or outcome.blocked == BLOCKED_NO_KEY

    if saw_cost and not (saw_limit or saw_no_key):
        blocked = BLOCKED_COST
    elif saw_limit and not saw_no_key:
        blocked = BLOCKED_LIMIT
    elif saw_no_key:
        blocked = BLOCKED_NO_KEY
    else:
        blocked = BLOCKED_ALL_FAILED
    detail = "; ".join(f"{a['provider']}/{a['model']}: {a['detail']}" for a in attempts)[:500]
    return ClassifyOutcome(ok=False, blocked=blocked, detail=detail, attempts=attempts)
