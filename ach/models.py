"""Modelos de datos del motor: candidato extraido y oferta normalizada."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional


def slug(text: str, limit: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:limit]


@dataclass
class Candidate:
    """Oferta cruda tal como sale de una fuente, con su evidencia literal."""

    source_id: str
    provider_key: str
    product: str
    title: str
    offer_type: str
    benefit: str
    official_url: str
    evidence_url: str
    evidence_snippet: str
    extraction_rule: str

    price_baseline: Optional[float] = None
    price_offer: Optional[float] = None
    price_unit: Optional[str] = None
    currency: Optional[str] = None
    discount_pct: Optional[float] = None

    eligibility: str = "No especificada en la fuente"
    card_required: str = "unknown"
    auto_renewal: str = "unknown"
    student_required: str = "unknown"
    argentina_status: str = "ARGENTINA_NO_CONFIRMADA"

    terms_url: Optional[str] = None
    starts_at: Optional[str] = None
    expires_at: Optional[str] = None
    published_at: Optional[str] = None
    time_window_utc: Optional[str] = None
    time_window_art: Optional[str] = None

    confidence: str = "media"
    notes: str = ""
    dedupe_extra: str = ""
    tags: list[str] = field(default_factory=list)
    # Clase de beneficio declarada por el extractor. No se persiste como columna
    # ni entra en dedupe_key(): solo determina la banda visible, para no crear
    # ofertas duplicadas al corregir la semantica de un beneficio.
    benefit_kind: str = ""

    def dedupe_key(self) -> str:
        extra = self.dedupe_extra or self.official_url or self.title
        raw = "|".join([
            slug(self.provider_key),
            slug(self.product, 60),
            slug(self.offer_type, 40),
            slug(self.price_unit or "na", 30),
            slug(extra, 90),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dedupe_key"] = self.dedupe_key()
        return d


@dataclass
class Offer:
    """Oferta normalizada y persistida."""

    dedupe_key: str
    provider_key: str
    product: str
    title: str
    offer_type: str
    benefit: str
    official_url: str
    evidence_url: str
    evidence_snippet: str
    extraction_rule: str
    price_baseline: Optional[float]
    price_offer: Optional[float]
    price_unit: Optional[str]
    currency: Optional[str]
    discount_pct: Optional[float]
    discount_band: str
    eligibility: str
    card_required: str
    auto_renewal: str
    student_required: str
    argentina_status: str
    terms_url: Optional[str]
    starts_at: Optional[str]
    expires_at: Optional[str]
    published_at: Optional[str]
    time_window_art: Optional[str]
    confidence: str
    verification_level: str
    status: str
    notes: str
    first_seen_utc: str
    last_seen_utc: str
    offer_id: Optional[int] = None
