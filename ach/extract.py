"""Extractores: convierten una respuesta HTTP en candidatos con evidencia.

Principios:
- Si el patron no aparece, se devuelve lista vacia. Nunca se rellena a mano.
- Cada candidato guarda el fragmento literal que lo respalda y la regla usada.
- Los precios se leen de la pagina; los descuentos se calculan con la formula
  del AGENTS.md (100 * (1 - P1/P0)) solo cuando P0 y P1 existen y son comparables.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import htmltext as ht
from .fetch import FetchResult
from .models import Candidate
from .sources import PROVIDERS, Source

PROMO_TERMS = re.compile(
    r"(\bfree (?:trial|tier|plan|access|credits?|for)\b|\bno[- ]cost\b|\bat no charge\b|"
    r"\bcomplimentary\b|\b\d{1,2}\s?%\s?off\b|\bdiscount\b|\bfree credits?\b|"
    r"\bcredits? (?:worth|for)\b|\bstudent (?:plan|discount|program)s?\b|"
    r"\beducation(?:al)? (?:plan|discount|offer)\b|\bgiveaway\b|\bcoupon\b|"
    r"\blimited[- ]time\b|\bpromotion\b|\bfree of charge\b)",
    re.I,
)
# Segunda senal obligatoria: sin monto, porcentaje, estudiantes o vigencia no es oferta.
PROMO_QUALIFIER = re.compile(
    r"(\d{1,2}\s?%|\$\s?\d|\bstudents?\b|limited time|\buntil\b|\bcredits?\b)",
    re.I,
)
RSS_MAX_AGE_DAYS = 120


def _provider_name(key: str) -> str:
    return PROVIDERS.get(key, {}).get("name", key)


def _json_window(raw: str, needle: str, pad: int = 220) -> str:
    idx = raw.find(needle)
    if idx < 0:
        return ""
    return ht.snippet(raw, idx, idx + len(needle), pad)


def _json_pricing_window(raw: str, model_id: str) -> str:
    """Fragmento literal del objeto pricing del modelo, no una reconstruccion."""
    idx = raw.find(f'"id":"{model_id}"')
    if idx < 0:
        idx = raw.find(f'"id": "{model_id}"')
    if idx < 0:
        return ""
    pidx = raw.find('"pricing"', idx)
    if pidx < 0:
        return ""
    brace = raw.find("{", pidx)
    if brace < 0:
        return ""
    depth = 0
    for i in range(brace, min(len(raw), brace + 4000)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                frag = raw[brace:i + 1]
                return ht.collapse(f'"id":"{model_id}" pricing={frag}')
    return ""


def _utc_hhmm_to_art(hh: int, mm: int) -> str:
    t = datetime(2000, 1, 1, hh, mm, tzinfo=timezone.utc) - timedelta(hours=3)
    return t.strftime("%H:%M")


def _art_window(utc_ranges: list[tuple[str, str]]) -> str | None:
    if not utc_ranges:
        return None
    parts = []
    for a, b in utc_ranges:
        try:
            ah, am = (int(x) for x in a.split(":"))
            bh, bm = (int(x) for x in b.split(":"))
        except ValueError:
            continue
        parts.append(f"{_utc_hhmm_to_art(ah, am)}-{_utc_hhmm_to_art(bh, bm)}")
    if not parts:
        return None
    return "Pico en ART: " + " y ".join(parts) + " (lun-vie). Fuera de eso, off-peak."


# --------------------------------------------------------------------------
# 1) OpenRouter: catalogo JSON con precios por token
# --------------------------------------------------------------------------
def openrouter_free_models(source: Source, res: FetchResult) -> list[Candidate]:
    try:
        payload = json.loads(res.text)
    except Exception:
        return []
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []

    out: list[Candidate] = []
    for m in models:
        try:
            pricing = m.get("pricing") or {}
            prompt = str(pricing.get("prompt"))
            completion = str(pricing.get("completion"))
        except Exception:
            continue
        if prompt != "0" or completion != "0":
            continue

        mid = str(m.get("id") or "").strip()
        name = str(m.get("name") or mid).strip()
        if not mid:
            continue
        ctx = m.get("context_length")
        ctx_txt = f" Contexto maximo: {int(ctx):,} tokens.".replace(",", ".") if isinstance(ctx, int) else ""

        snippet = _json_pricing_window(res.text, mid)
        if not snippet:
            snippet = json.dumps({"id": mid, "pricing": pricing}, ensure_ascii=False)
        rule = "json:data[].pricing.prompt==0 && pricing.completion==0"

        out.append(Candidate(
            source_id=source.id,
            provider_key=source.provider_key,
            product=name,
            title=f"Modelo sin costo por token: {name}",
            offer_type="FREE_MODEL",
            benefit=(
                f"Entrada y salida a USD 0 por token segun el endpoint publico /api/v1/models."
                f"{ctx_txt}"
            ),
            official_url=f"https://openrouter.ai/{mid}",
            evidence_url=source.url,
            evidence_snippet=snippet or "",
            extraction_rule=rule,
            price_baseline=None,
            price_offer=0.0,
            price_unit="USD / token",
            currency="USD",
            discount_pct=None,
            eligibility="Cuenta OpenRouter. Requisitos de tarjeta no informados en este endpoint.",
            card_required="unknown",
            auto_renewal="no",
            argentina_status="ARGENTINA_NO_CONFIRMADA",
            terms_url=source.terms_url,
            confidence="alta",
            notes="Precio 0 publicado por el proveedor. No implica cuota ilimitada ni ausencia de limites de uso.",
            dedupe_extra=mid,
            tags=["modelo-gratuito", "api"],
        ))
    return out


# --------------------------------------------------------------------------
# 2) DeepSeek: tabla PEAK / OFF-PEAK
# --------------------------------------------------------------------------
_DEEPSEEK_BLOCK = re.compile(
    r"(1M INPUT TOKENS\s+\(CACHE HIT\)|1M INPUT TOKENS\s+\(CACHE MISS\)|1M OUTPUT TOKENS)\s+"
    r"OFF-PEAK\s+\$([\d.]+)(?:\s+\$([\d.]+))?\s+"
    r"PEAK\s+\$([\d.]+)(?:\s+\$([\d.]+))?",
    re.I,
)

_LABEL_HUMAN = {
    "1M INPUT TOKENS (CACHE HIT)": "entrada con cache hit",
    "1M INPUT TOKENS (CACHE MISS)": "entrada con cache miss",
    "1M OUTPUT TOKENS": "salida",
}


def deepseek_offpeak(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    if not text:
        return []
    claim = re.search(r"Off-peak rates are half of the peak rates", text, re.I)
    if not claim:
        return []

    model = re.search(r"\bMODEL\s+(deepseek-[a-z0-9.\-]+)", text, re.I)
    model_name = model.group(1) if model else "DeepSeek API"

    window = None
    peak = re.search(
        r"Peak hours are\s+([\d:]{4,5}\s*-\s*[\d:]{4,5})\s+and\s+([\d:]{4,5}\s*-\s*[\d:]{4,5})\s+UTC",
        text, re.I,
    )
    if peak:
        ranges = []
        for grp in peak.groups():
            a, b = [x.strip() for x in grp.split("-")]
            ranges.append((a, b))
        window = _art_window(ranges)

    out: list[Candidate] = []
    for m in _DEEPSEEK_BLOCK.finditer(text):
        label = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        human = _LABEL_HUMAN.get(label, label.lower())
        off = ht.parse_money(m.group(2))
        peak_price = ht.parse_money(m.group(4))
        if off is None or peak_price is None or peak_price <= 0:
            continue
        discount = round(100.0 * (1.0 - off / peak_price), 2)
        unit = f"USD / 1M tokens ({human})"
        snippet = ht.snippet(text, m.start(), m.end(), 120)

        out.append(Candidate(
            source_id=source.id,
            provider_key=source.provider_key,
            product=f"DeepSeek API ({model_name})",
            title=f"Off-peak {human}: ${off:g} vs ${peak_price:g} por 1M tokens",
            offer_type="OFF_PEAK_DISCOUNT",
            benefit=(
                f"Tarifa off-peak ${off:g} contra peak ${peak_price:g} por 1M tokens "
                f"({human}). La pagina declara: 'Off-peak rates are half of the peak rates'."
            ),
            official_url=source.url,
            evidence_url=source.url,
            evidence_snippet=snippet,
            extraction_rule="html:regex PEAK/OFF-PEAK por 1M tokens + claim explicito de mitad de precio",
            price_baseline=peak_price,
            price_offer=off,
            price_unit=unit,
            currency="USD",
            discount_pct=discount,
            eligibility="Cuenta API con saldo (pay-as-you-go). No requiere suscripcion.",
            card_required="unknown",
            auto_renewal="no",
            argentina_status="ARGENTINA_NO_CONFIRMADA",
            terms_url=source.terms_url,
            time_window_utc="Pico: 01:00-04:00 y 06:00-10:00 UTC, lun-vie",
            time_window_art=window,
            confidence="alta",
            notes="Descuento calculado sobre precios publicados, misma unidad y misma modalidad.",
            dedupe_extra=f"{model_name}|{label}",
            tags=["off-peak", "api"],
        ))
    return out


# --------------------------------------------------------------------------
# 3) Asignacion gratuita declarada en HTML (Cloudflare y similares)
# --------------------------------------------------------------------------
def html_free_allocation(source: Source, res: FetchResult) -> list[Candidate]:
    p = source.params
    text = ht.to_text(res.text)
    if not text:
        return []
    m = re.search(p.get("allocation_pattern", r"$^"), text, re.I)
    if not m:
        return []
    amount = m.group(1)
    unit_price = None
    unit_m = re.search(p.get("unit_pattern", r"$^"), text, re.I)
    if unit_m:
        unit_price = ht.parse_money(unit_m.group(1))

    discount = 100.0 if unit_price else None
    snippet = ht.snippet(text, m.start(), m.end(), 180)
    benefit = p.get("benefit_template", "Asignacion gratuita de {amount}").format(
        amount=amount, unit_price=f"${unit_price:g}" if unit_price is not None else "N/D"
    )
    title = p.get("title_template", "Asignacion gratuita de {amount}").format(amount=amount)

    return [Candidate(
        source_id=source.id,
        provider_key=source.provider_key,
        product=p.get("product", _provider_name(source.provider_key)),
        title=title,
        offer_type=p.get("offer_type", "FREE_TIER"),
        benefit=benefit,
        official_url=source.url,
        evidence_url=source.url,
        evidence_snippet=snippet,
        extraction_rule="html:regex de asignacion gratuita + precio unitario",
        price_baseline=unit_price,
        price_offer=0.0 if unit_price else None,
        price_unit=p.get("price_unit"),
        currency="USD" if unit_price else None,
        discount_pct=discount,
        eligibility="Plan gratuito del proveedor; el excedente requiere plan pago.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes="Beneficio y precio unitario leidos de la misma pagina oficial.",
        dedupe_extra=source.id,
        tags=["free-tier", "diario"],
    )]


# --------------------------------------------------------------------------
# 4) RSS/Atom: anuncios con lenguaje promocional
# --------------------------------------------------------------------------
def _rss_items(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET

    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "description": "", "date": ""}
        for child in node:
            name = local(child.tag)
            if name == "title":
                rec["title"] = ht.collapse(child.text or "")
            elif name == "link":
                rec["link"] = (child.text or "").strip() or child.attrib.get("href", "")
            elif name in ("description", "summary", "content"):
                if not rec["description"]:
                    rec["description"] = ht.collapse("".join(child.itertext()))
            elif name in ("pubdate", "published", "updated"):
                rec["date"] = (child.text or "").strip()
        if rec["title"] and rec["link"]:
            items.append(rec)
    return items


def _iso_date(raw: str) -> str | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def rss_promotions(source: Source, res: FetchResult) -> list[Candidate]:
    """Solo items con frase promocional fuerte + segunda senal cuantificable.

    Un anuncio institucional que menciona "free" al pasar no es una oferta.
    """
    out: list[Candidate] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RSS_MAX_AGE_DAYS)

    for item in _rss_items(res.text):
        blob = f"{item['title']} {item['description']}"
        if not PROMO_TERMS.search(blob) or not PROMO_QUALIFIER.search(blob):
            continue
        published = _iso_date(item["date"])
        if published:
            try:
                dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except ValueError:
                pass
        snippet = ht.trim(blob, 380)
        out.append(Candidate(
            source_id=source.id,
            provider_key=source.provider_key,
            product=f"{_provider_name(source.provider_key)} (anuncio)",
            title=ht.trim(item["title"], 180),
            offer_type="ANUNCIO_PROMOCIONAL",
            benefit=ht.trim(item["description"] or item["title"], 400),
            official_url=item["link"],
            evidence_url=source.url,
            evidence_snippet=snippet,
            extraction_rule="rss:frase promocional fuerte + monto/porcentaje/estudiantes/vigencia",
            eligibility="No especificada en el anuncio",
            card_required="unknown",
            auto_renewal="unknown",
            argentina_status="ARGENTINA_NO_CONFIRMADA",
            terms_url=source.terms_url,
            published_at=published,
            confidence="baja",
            notes=(
                "Anuncio oficial. NO confirma por si solo una promocion vigente: "
                "requiere abrir el enlace y verificar condiciones."
            ),
            dedupe_extra=item["link"],
            tags=["anuncio", "requiere-verificacion"],
        ))
    return out[:10]


# --------------------------------------------------------------------------
# 5) Kiro: tabla KIRO FREE / KIRO PRO
# --------------------------------------------------------------------------
_KIRO_FREE = re.compile(
    r"KIRO FREE\s+\$0\s+per month\s+([\d,]+)\s+credits", re.I)
_KIRO_PRO = re.compile(r"KIRO PRO\s+\$([\d.]+)\s+per user\s*/\s*month", re.I)


def kiro_free_plan(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    free = _KIRO_FREE.search(text)
    if not free:
        return []
    credits = free.group(1)
    pro = _KIRO_PRO.search(text)
    baseline = ht.parse_money(pro.group(1)) if pro else None
    discount = 100.0 if baseline else None
    snippet = ht.snippet(text, free.start(), free.end(), 140)
    if pro:
        snippet = snippet + " | PRO: " + ht.snippet(text, pro.start(), pro.end(), 40)

    return [Candidate(
        source_id=source.id,
        provider_key=source.provider_key,
        product="Kiro IDE / CLI",
        title=f"Plan gratuito Kiro: {credits} creditos por mes a $0",
        offer_type="FREE_TIER",
        benefit=(
            f"Plan KIRO FREE a $0 por mes con {credits} creditos."
            + (f" El plan PRO cuesta ${baseline:g} por usuario/mes." if baseline else "")
        ),
        official_url=source.url,
        evidence_url=source.url,
        evidence_snippet=snippet,
        extraction_rule="html:regex 'KIRO FREE $0 per month N credits' + precio PRO",
        price_baseline=baseline,
        price_offer=0.0,
        price_unit="USD / mes",
        currency="USD",
        discount_pct=discount,
        eligibility="Cuenta Kiro; el plan free no requiere pago.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes="Creditos y precio leidos de la tabla de precios oficial.",
        dedupe_extra=source.id,
        tags=["free-tier", "ide"],
    )]


# --------------------------------------------------------------------------
# 6) Vercel AI Gateway: credito mensual incluido
# --------------------------------------------------------------------------
def html_monthly_credit(source: Source, res: FetchResult) -> list[Candidate]:
    p = source.params
    text = ht.to_text(res.text)
    m = re.search(p.get("credit_pattern", r"$^"), text, re.I)
    if not m:
        return []
    amount = ht.parse_money(m.group(1))
    if amount is None:
        return []
    snippet = ht.snippet(text, m.start(), m.end(), 160)
    return [Candidate(
        source_id=source.id,
        provider_key=source.provider_key,
        product=p.get("product", _provider_name(source.provider_key)),
        title=p.get("title_template", "Credito mensual de ${amount} incluido").format(amount=f"{amount:g}"),
        offer_type="CREDITS",
        benefit=p.get("benefit_template", "Credito mensual de ${amount} incluido en el plan gratuito.").format(
            amount=f"{amount:g}"),
        official_url=source.url,
        evidence_url=source.url,
        evidence_snippet=snippet,
        extraction_rule="html:regex de credito mensual incluido",
        price_baseline=amount,
        price_offer=0.0,
        price_unit="USD / mes",
        currency="USD",
        discount_pct=100.0,
        eligibility="Cuenta/equipo del proveedor; el credito se renueva mensualmente.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes="Credito declarado en la pagina de precios; no incluye cargos por encima del credito.",
        dedupe_extra=source.id,
        tags=["creditos", "mensual"],
    )]


EXTRACTORS = {
    "openrouter_free_models": openrouter_free_models,
    "deepseek_offpeak": deepseek_offpeak,
    "html_free_allocation": html_free_allocation,
    "rss_promotions": rss_promotions,
    "kiro_free_plan": kiro_free_plan,
    "html_monthly_credit": html_monthly_credit,
}


def extract(source: Source, res: FetchResult) -> list[Candidate]:
    fn = EXTRACTORS.get(source.extractor)
    if not fn:
        return []
    try:
        return fn(source, res)
    except Exception:
        return []
