"""Clasificacion, bandas de descuento, elegibilidad AR y nivel de verificacion.

Ninguna funcion inventa datos: si falta la evidencia, devuelve `unknown` o
`ARGENTINA_NO_CONFIRMADA`, tal como exige AGENTS.md.
"""

from __future__ import annotations

import re

from .models import Candidate

BANDS = [
    (90.0, "DESCUENTO_90_PLUS"),
    (70.0, "DESCUENTO_70_89"),
    (50.0, "DESCUENTO_50_69"),
    (30.0, "DESCUENTO_30_49"),
]

# Clases de beneficio. La gratuidad NO es un descuento porcentual: un plan free,
# una cuota incluida o un credito no tienen un precio de lista comparable.
BENEFIT_KINDS = (
    "DESCUENTO",        # porcentaje real sobre precios comparables
    "TARIFA_HORARIA",   # tarifa especial por horario (peak vs off-peak)
    "PLAN_GRATUITO",    # plan gratuito permanente
    "CUOTA_GRATUITA",   # cuota gratuita incluida
    "CREDITO",          # creditos promocionales o recurrentes
    "PRUEBA_GRATUITA",  # prueba gratuita
    "MODELO_GRATUITO",  # modelo sin costo por token
    "BENEFICIO_ESTUDIANTIL",  # beneficio atado a elegibilidad academica
)

# Solo estas clases comparan dos precios del mismo producto, modalidad, unidad
# y periodo; unicamente ellas pueden llevar un porcentaje.
KINDS_CON_COMPARACION = {"DESCUENTO", "TARIFA_HORARIA"}

_KIND_POR_TIPO = {
    "DISCOUNT": "DESCUENTO",
    "OFF_PEAK_DISCOUNT": "TARIFA_HORARIA",
    "FREE_TIER": "PLAN_GRATUITO",
    "FREE_PLAN": "PLAN_GRATUITO",
    "FREE_QUOTA": "CUOTA_GRATUITA",
    "FREE_MODEL": "MODELO_GRATUITO",
    "CREDITS": "CREDITO",
    "TRIAL": "PRUEBA_GRATUITA",
    "STUDENT": "BENEFICIO_ESTUDIANTIL",
}


def benefit_kind(c: Candidate) -> str:
    """Clase declarada por el extractor, o inferida del tipo de oferta."""
    return c.benefit_kind or _KIND_POR_TIPO.get(c.offer_type, "")


# Etiquetas legibles compartidas por la interfaz, el reporte y la CLI: la
# gratuidad se nombra, nunca se presenta como un porcentaje de descuento.
KIND_LABELS = {
    "PLAN_GRATUITO": "Plan gratuito",
    "CUOTA_GRATUITA": "Cuota incluida",
    "CREDITO": "Credito",
    "PRUEBA_GRATUITA": "Prueba gratuita",
    "MODELO_GRATUITO": "Modelo gratuito",
    "BENEFICIO_ESTUDIANTIL": "Beneficio estudiantil",
    "SIN_BASE_VERIFICADA": "sin base comparable",
    "SIN_DESCUENTO": "sin descuento",
}


def kind_label(band: str) -> str:
    return KIND_LABELS.get(band, "sin base comparable")


def precios_comparables(c: Candidate) -> bool:
    """Exige base publicada positiva, precio oferta, unidad y moneda declaradas.

    Sin equivalencia de producto, modalidad, unidad y periodo no hay porcentaje
    posible: una cuota diaria gratis contra el precio del excedente, o un plan
    FREE contra un PRO con otros limites, no son la misma cosa.
    """
    return (
        benefit_kind(c) in KINDS_CON_COMPARACION
        and c.price_baseline is not None
        and c.price_baseline > 0
        and c.price_offer is not None
        and c.price_offer >= 0
        and bool(c.price_unit)
        and bool(c.currency)
    )


def discount_band(pct: float | None) -> str:
    if pct is None:
        return "SIN_BASE_VERIFICADA"
    if pct >= 99.95:
        return "GRATIS_100"
    for threshold, label in BANDS:
        if pct >= threshold:
            return label
    return "SIN_DESCUENTO"


_TYPE_RULES = [
    ("STUDENT", re.compile(r"\b(student|education|academic|universit|sheerid)\w*", re.I)),
    ("TRIAL", re.compile(r"\b(free trial|trial|prueba gratuita)\b", re.I)),
    ("CREDITS", re.compile(r"\b(credits?|cupo|cupones|coupon|voucher|grant)\b", re.I)),
    ("OFF_PEAK", re.compile(r"\b(off-peak|off peak|horario valle|fuera de pico)\b", re.I)),
    ("DISCOUNT", re.compile(r"\b(discount|% off|descuento|rebaja)\b", re.I)),
    ("FREE_TIER", re.compile(r"\b(free tier|free plan|plan gratuito|gratis|free)\b", re.I)),
]


def refine_type(c: Candidate) -> str:
    if c.offer_type not in ("ANUNCIO_PROMOCIONAL", "UNKNOWN", ""):
        return c.offer_type
    blob = f"{c.title} {c.benefit}"
    for label, rx in _TYPE_RULES:
        if rx.search(blob):
            return label
    return "ANUNCIO"


_GEO_GLOBAL = re.compile(
    r"\b(worldwide|globally|all countries|available in every country)\b", re.I
)
_GEO_RESTRICTED = re.compile(
    r"\b(not available in|excluding|excludes|sanctioned|embargoed|restricted countries)\b", re.I
)
_NO_CARD = re.compile(r"\b(no credit card|without a credit card|sin tarjeta)\b", re.I)
_YES_CARD = re.compile(r"\b(credit card required|requires a credit card|tarjeta requerida)\b", re.I)


def argentina_status(c: Candidate) -> str:
    blob = f"{c.title} {c.benefit} {c.evidence_snippet}"
    if _GEO_RESTRICTED.search(blob):
        return "REQUIERE_REVISION_GEO"
    if _GEO_GLOBAL.search(blob):
        return "DISPONIBLE_POR_DECLARACION"
    return "ARGENTINA_NO_CONFIRMADA"


def card_requirement(c: Candidate) -> str:
    blob = f"{c.title} {c.benefit} {c.evidence_snippet}"
    if _NO_CARD.search(blob):
        return "no"
    if _YES_CARD.search(blob):
        return "yes"
    return c.card_required if c.card_required in ("yes", "no") else "unknown"


def verification_level(c: Candidate, http_status: int, fixture: bool) -> str:
    if fixture:
        return "FIXTURE"
    if http_status != 200:
        return "UNVERIFIED"
    if not c.evidence_snippet:
        return "UNVERIFIED"
    if c.discount_pct is not None and c.price_baseline and c.price_offer is not None:
        return "NETWORK_VERIFIED"
    if c.price_offer == 0.0 and c.confidence == "alta":
        return "NETWORK_VERIFIED"
    return "CONTENT_VERIFIED"


def confidence(c: Candidate, level: str) -> str:
    if level == "NETWORK_VERIFIED":
        return "alta"
    if level == "CONTENT_VERIFIED":
        return "media" if c.confidence != "baja" else "baja"
    return "baja"


def assess(c: Candidate, http_status: int, fixture: bool = False) -> Candidate:
    """Aplica todas las reglas sobre el candidato, en sitio, y lo devuelve."""
    c.offer_type = refine_type(c)
    # Guarda central: ningun extractor puede fabricar un porcentaje sin dos
    # precios equivalentes del mismo producto, modalidad, unidad y periodo.
    if c.discount_pct is not None and not precios_comparables(c):
        c.discount_pct = None
        c.notes = (c.notes + " [porcentaje descartado: sin precios comparables]").strip()
    c.argentina_status = argentina_status(c)
    c.card_required = card_requirement(c)
    level = verification_level(c, http_status, fixture)
    c.confidence = confidence(c, level)
    if not c.notes:
        c.notes = ""
    c.notes = (c.notes + f" [nivel={level}]").strip()
    return c


def band_of(c: Candidate) -> str:
    """Porcentaje real, clase de gratuidad, o SIN_BASE_VERIFICADA.

    La banda es el campo que la interfaz filtra y muestra; no forma parte de
    dedupe_key(), asi que corregir la semantica no duplica ofertas.
    """
    if c.discount_pct is not None and precios_comparables(c):
        return discount_band(c.discount_pct)
    kind = benefit_kind(c)
    if kind and kind not in KINDS_CON_COMPARACION:
        return kind
    return "SIN_BASE_VERIFICADA"
