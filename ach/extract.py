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
from .models import Candidate, slug
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
            benefit_kind="MODELO_GRATUITO",
        ))
    return out


# --------------------------------------------------------------------------
# 2) DeepSeek: tabla PEAK / OFF-PEAK
# --------------------------------------------------------------------------
_DEEPSEEK_BLOCK = re.compile(
    r"(1M INPUT TOKENS\s+\(CACHE HIT\)|1M INPUT TOKENS\s+\(CACHE MISS\)|1M OUTPUT TOKENS)\s+"
    r"OFF-PEAK\s+(\$[\d.]+(?:\s+\$[\d.]+)*)\s+"
    r"PEAK\s+(\$[\d.]+(?:\s+\$[\d.]+)*)",
    re.I,
)
_DEEPSEEK_PRICE = re.compile(r"\$([\d.]+)")
# La tabla tiene una columna por modelo, en el orden del encabezado MODEL.
# Se exige que la linea empiece con un nombre deepseek- para no capturar
# "MODEL VERSION" ni los nombres retirados que aparecen en las notas al pie.
_DEEPSEEK_MODEL_ROW = re.compile(r"^MODEL\s+(deepseek-[^\n]+)$", re.I | re.M)
_DEEPSEEK_MODEL_NAME = re.compile(r"\bdeepseek-[a-z0-9.\-]+", re.I)
_DEEPSEEK_WINDOW = re.compile(r"(Peak hours are\s+.+?UTC[^.]*\.)", re.I)
_DEEPSEEK_OFFPEAK_REST = re.compile(r"(All other hours are off-peak[^.]*\.)", re.I)

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

    header = _DEEPSEEK_MODEL_ROW.search(text)
    models = _DEEPSEEK_MODEL_NAME.findall(header.group(1)) if header else []

    window = None
    window_utc = None
    peak = _DEEPSEEK_WINDOW.search(text)
    if peak:
        window_utc = ht.collapse(peak.group(1))
        ranges = re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", peak.group(1))
        if ranges:
            window = _art_window(ranges)
    rest = _DEEPSEEK_OFFPEAK_REST.search(text)
    offpeak_rest = ht.collapse(rest.group(1)) if rest else ""

    out: list[Candidate] = []
    for m in _DEEPSEEK_BLOCK.finditer(text):
        label = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        human = _LABEL_HUMAN.get(label, label.lower())
        offs = [ht.parse_money(x) for x in _DEEPSEEK_PRICE.findall(m.group(2))]
        peaks = [ht.parse_money(x) for x in _DEEPSEEK_PRICE.findall(m.group(3))]
        unit = f"USD / 1M tokens ({human})"
        snippet = ht.snippet(text, m.start(), m.end(), 120)

        for idx, (off, peak_price) in enumerate(zip(offs, peaks)):
            # Columna sin modelo identificable en el encabezado: no se atribuye.
            if idx >= len(models):
                break
            if off is None or peak_price is None or peak_price <= 0:
                continue
            model_name = models[idx]
            discount = round(100.0 * (1.0 - off / peak_price), 2)
            notes = ("Descuento calculado sobre precios publicados, misma unidad "
                     "y misma modalidad (cache hit/miss o salida).")
            if offpeak_rest:
                notes = f"{notes} {offpeak_rest}"

            out.append(Candidate(
                source_id=source.id,
                provider_key=source.provider_key,
                product=f"DeepSeek API ({model_name})",
                title=f"Off-peak {human}: ${off:g} vs ${peak_price:g} por 1M tokens",
                offer_type="OFF_PEAK_DISCOUNT",
                benefit=(
                    f"Tarifa off-peak ${off:g} contra peak ${peak_price:g} por 1M tokens "
                    f"({human}) del modelo {model_name}. La pagina declara: "
                    "'Off-peak rates are half of the peak rates'."
                ),
                official_url=source.url,
                evidence_url=source.url,
                evidence_snippet=snippet,
                extraction_rule="html:regex PEAK/OFF-PEAK por 1M tokens, una columna por modelo + claim explicito de mitad de precio",
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
                time_window_utc=window_utc,
                time_window_art=window,
                confidence="alta",
                notes=notes,
                dedupe_extra=f"{model_name}|{label}",
                tags=["off-peak", "api"],
                benefit_kind="TARIFA_HORARIA",
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

    # La cuota diaria incluida y el precio del excedente NO son comparables:
    # distinto periodo, distintos limites y distinto alcance. No hay porcentaje.
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
        price_baseline=None,
        price_offer=0.0,
        price_unit=p.get("price_unit"),
        currency="USD" if unit_price else None,
        discount_pct=None,
        eligibility="Plan gratuito del proveedor; el excedente requiere plan pago.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Cuota gratuita incluida, leida de la pagina oficial. No es un descuento: "
            "el precio del excedente no es una base comparable (otro periodo y otros "
            "limites). Sin base verificable, sin porcentaje."
        ),
        dedupe_extra=source.id,
        tags=["free-tier", "diario"],
        benefit_kind=p.get("benefit_kind", "CUOTA_GRATUITA"),
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
    # FREE y PRO son productos distintos (otros creditos y limites): el precio de
    # PRO no es una base comparable. Es un plan gratuito permanente, no un 100%.
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
        price_baseline=None,
        price_offer=0.0,
        price_unit="USD / mes",
        currency="USD",
        discount_pct=None,
        eligibility="Cuenta Kiro; el plan free no requiere pago.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Plan gratuito permanente leido de la tabla de precios oficial. No es un "
            "descuento: FREE y PRO son productos distintos (otros creditos y limites), "
            "asi que no hay base comparable ni porcentaje."
        ),
        dedupe_extra=source.id,
        tags=["free-tier", "ide"],
        benefit_kind="PLAN_GRATUITO",
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
        # El importe del credito no es un precio de lista: no hay base comparable.
        price_baseline=None,
        price_offer=None,
        price_unit="USD / mes",
        currency="USD",
        discount_pct=None,
        eligibility="Cuenta/equipo del proveedor; el credito se renueva mensualmente.",
        card_required="unknown",
        auto_renewal="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Credito recurrente declarado en la pagina de precios; no incluye cargos por "
            "encima del credito. No es un descuento: el importe acreditado no es un precio "
            "de lista comparable, asi que no hay base verificada ni porcentaje."
        ),
        dedupe_extra=source.id,
        tags=["creditos", "mensual"],
        benefit_kind=p.get("benefit_kind", "CREDITO"),
    )]


# --------------------------------------------------------------------------
# 7) GroqCloud: cuotas del plan Free (payload etiquetado, no la tabla visible)
# --------------------------------------------------------------------------
# La pagina publica dos juegos de limites: freeRows (Free) y devRows (Developer).
# Se lee SOLO freeRows para no atribuir al plan gratuito cuotas del plan pago.
_GROQ_FREE_ROWS = re.compile(r'"freeRows":\s*(\[\[.*?\]\])', re.S)
_GROQ_QUOTAS = ("RPM", "RPD", "TPM", "TPD", "ASH", "ASD")


def groq_free_plan(source: Source, res: FetchResult) -> list[Candidate]:
    raw = res.text or ""
    if "Free Plan Limits" not in raw:
        return []
    # El payload de Next.js escapa las comillas; se normaliza solo para leer JSON.
    m = _GROQ_FREE_ROWS.search(raw.replace('\\"', '"'))
    if not m:
        return []
    try:
        rows = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(rows, list):
        return []

    text = ht.to_text(raw)
    out: list[Candidate] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        model = str(row[0]).strip()
        if not model:
            continue
        quotas = [(k, str(v).strip()) for k, v in zip(_GROQ_QUOTAS, row[1:7])
                  if str(v).strip() not in ("", "-", "N/A")]
        if not quotas:
            continue
        detail = ", ".join(f"{k}={v}" for k, v in quotas)
        idx = text.find(model)
        snippet = (ht.snippet(text, idx, idx + len(model) + 120, 40) if idx >= 0
                   else ht.collapse(m.group(1))[:600])

        out.append(Candidate(
            source_id=source.id,
            provider_key=source.provider_key,
            product=f"GroqCloud ({model})",
            title=f"Plan Free de GroqCloud para {model}",
            offer_type="FREE_TIER",
            benefit=(
                f"Plan Free de GroqCloud con cuotas publicadas para {model}: {detail}. "
                "RPM/RPD son requests por minuto/dia; TPM/TPD tokens por minuto/dia; "
                "ASH/ASD segundos de audio por hora/dia."
            ),
            official_url=source.url,
            evidence_url=source.url,
            evidence_snippet=snippet,
            extraction_rule="html:array 'freeRows' del payload oficial (plan Free) + fragmento literal",
            price_baseline=None,
            price_offer=0.0,
            price_unit="USD / mes",
            currency="USD",
            discount_pct=None,
            eligibility=(
                "Cuenta GroqCloud en plan Free. Las Billing FAQs indican que el upgrade "
                "a Developer exige metodo de pago; para el plan Free no se declara "
                "requisito de tarjeta."
            ),
            card_required="unknown",
            auto_renewal="no",
            argentina_status="ARGENTINA_NO_CONFIRMADA",
            terms_url=source.terms_url,
            confidence="alta",
            notes=(
                "Cuotas del plan Free leidas de 'freeRows'; las del plan Developer "
                "('devRows') no se mezclan. La pagina publica cuotas de uso, no un precio "
                "de lista comparable: no hay descuento porcentual. El precio comercial por "
                "millon de tokens no se interpreta como 100% de descuento. "
                "Tarjeta y disponibilidad en Argentina: No confirmado."
            ),
            dedupe_extra=model,
            tags=["free-tier", "api", "groq"],
            benefit_kind="PLAN_GRATUITO",
        ))
    return out


# --------------------------------------------------------------------------
# 8) Stability AI: creditos iniciales de bienvenida
# --------------------------------------------------------------------------
_STABILITY_FREE = re.compile(r"Get started with\s+([\d,]+)\s+free credits", re.I)
_STABILITY_UNIT = re.compile(r"1\s+credit\s*(?:=|equals)\s*\$(\d+(?:\.\d+)?)", re.I)


def stability_welcome_credits(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    if not text:
        return []
    m = _STABILITY_FREE.search(text)
    if not m:
        return []
    credits = ht.parse_money(m.group(1))
    if credits is None or credits <= 0:
        return []
    unit_m = _STABILITY_UNIT.search(text)
    unit_value = ht.parse_money(unit_m.group(1)) if unit_m else None
    worth = f" (USD {credits * unit_value:g})" if unit_value else ""
    equiv = (f" Equivalencia publicada: 1 credito = USD {unit_value:g}."
             if unit_value else "")

    return [Candidate(
        source_id=source.id,
        provider_key=source.provider_key,
        product="Stability AI API",
        title=f"Creditos de bienvenida Stability AI: {credits:g} gratis{worth}",
        offer_type="CREDITS",
        benefit=(
            f"La pagina de precios oficial declara 'Get started with {m.group(1)} free "
            f"credits'.{equiv} El saldo y la compra de creditos adicional se gestionan "
            "en la pagina de cuenta."
        ),
        official_url=source.url,
        evidence_url=source.url,
        evidence_snippet=ht.snippet(text, m.start(), m.end(), 200),
        extraction_rule="html:regex 'Get started with N free credits' + equivalencia credito/USD",
        price_baseline=None,
        price_offer=None,
        price_unit="USD (creditos)",
        currency="USD" if unit_value else None,
        discount_pct=None,
        eligibility="Requiere cuenta y API key de Stability AI para usar los creditos.",
        card_required="unknown",
        auto_renewal="unknown",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Creditos iniciales de bienvenida, no un descuento porcentual: no hay precio "
            "de lista comparable. Vencimiento, duracion, requisito de tarjeta y "
            "disponibilidad en Argentina: No confirmado en la pagina; no se inventan."
        ),
        dedupe_extra=source.id,
        tags=["creditos", "bienvenida", "api"],
        benefit_kind="CREDITO",
    )]


# --------------------------------------------------------------------------
# 9) Cohere: clave de evaluacion gratuita con tope mensual
# --------------------------------------------------------------------------
_COHERE_EVAL = re.compile(r"evaluation keys\s*\(free but limited in usage\)", re.I)
_COHERE_MONTHLY = re.compile(r"limited to\s+([\d,]+)\s+API calls a month", re.I)


def cohere_trial_key(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    if not text:
        return []
    eval_m = _COHERE_EVAL.search(text)
    calls_m = _COHERE_MONTHLY.search(text)
    if not eval_m or not calls_m:
        return []
    calls = calls_m.group(1)
    start = min(eval_m.start(), calls_m.start())
    end = max(eval_m.end(), calls_m.end())

    return [Candidate(
        source_id=source.id,
        provider_key=source.provider_key,
        product="Cohere API (clave de evaluacion)",
        title=f"Clave de evaluacion gratuita de Cohere: {calls} llamadas/mes",
        offer_type="TRIAL",
        benefit=(
            f"Cohere declara 'evaluation keys (free but limited in usage)' y que las "
            f"claves trial estan limitadas a {calls} API calls a month. Las claves "
            "production son pagas y mucho menos limitadas; la pagina publica ademas "
            "limites por modelo (por ejemplo 20 req/min en la familia Command A)."
        ),
        official_url=source.url,
        evidence_url=source.url,
        evidence_snippet=ht.snippet(text, start, end, 40),
        extraction_rule="html:regex 'evaluation keys (free...)' + tope mensual de llamadas",
        price_baseline=None,
        price_offer=0.0,
        price_unit="USD (clave de evaluacion)",
        currency="USD",
        discount_pct=None,
        eligibility=(
            "Cuenta Cohere y clave de evaluacion (trial). No es acceso de produccion: "
            "para uso productivo la documentacion remite a claves production pagas."
        ),
        card_required="unknown",
        auto_renewal="unknown",
        argentina_status="ARGENTINA_NO_CONFIRMADA",
        terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Clave de evaluacion gratuita CON TOPE mensual declarado: no es acceso "
            "gratuito ilimitado ni de produccion. Tarjeta, vencimiento y disponibilidad "
            "en Argentina: No confirmado en la pagina."
        ),
        dedupe_extra=source.id,
        tags=["prueba", "api", "evaluacion"],
        benefit_kind="PRUEBA_GRATUITA",
    )]


# --------------------------------------------------------------------------
# 10) P1.2: fuentes oficiales adicionales con beneficio documentado
# --------------------------------------------------------------------------
_ALIBABA_QUOTA = re.compile(r"The free quota is valid for\s+(\d+)\s+days", re.I)
_ALIBABA_PROTECT = re.compile(r"enable Free Quota Only[^.]*\.", re.I)
_ALIBABA_BILLING = re.compile(r"you are automatically billed on a pay-as-you-go basis", re.I)


def alibaba_free_quota(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _ALIBABA_QUOTA.search(text)
    if not m:
        return []
    days = m.group(1)
    protect = _ALIBABA_PROTECT.search(text)
    billing = _ALIBABA_BILLING.search(text)
    if not protect or not billing:
        return []          # sin la advertencia de cargo no se publica el beneficio
    end = max(m.end(), protect.end(), billing.end())
    start = min(m.start(), protect.start(), billing.start())
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Alibaba Cloud Model Studio",
        title=f"Cuota gratuita para nuevos usuarios de Model Studio: {days} dias",
        offer_type="TRIAL",
        benefit=(
            f"Cuota gratuita para nuevos usuarios, valida por {days} dias desde la "
            "activacion del servicio, la publicacion del modelo o la aprobacion de la "
            "solicitud (lo que ocurra mas tarde). La pagina advierte que al agotarse "
            "la cuota se factura automaticamente en pay-as-you-go, y que para evitarlo "
            "hay que activar 'Free Quota Only', que detiene el servicio al agotarse."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, start, end, 60),
        extraction_rule="html:validez de la cuota + advertencia de cargo + proteccion Free Quota Only",
        price_baseline=None, price_offer=None, price_unit=None, currency=None,
        discount_pct=None,
        eligibility=(
            "Usuarios nuevos de Alibaba Cloud Model Studio. Desde el 15 de septiembre "
            "hay que completar la informacion de la cuenta antes de activar el servicio."
        ),
        card_required="unknown", auto_renewal="unknown", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "RIESGO DE CARGO: 'Free Quota Only' viene DESACTIVADO por defecto; al agotar "
            "la cuota se factura automaticamente. Activarlo en la consola antes de usar "
            "el servicio. Los importes por modelo se consultan en la consola, no en esta "
            "pagina: no se inventan cantidades. Tarjeta, pais y renovacion: No confirmado."
        ),
        dedupe_extra=source.id, tags=["cuota-gratuita", "api", "riesgo-cargo"],
        benefit_kind="PRUEBA_GRATUITA",
    )]


_CEREBRAS_CREDIT = re.compile(
    r"Add a valid payment method to receive a one-time \$(\d+) promotional credit", re.I)
_CEREBRAS_EXPIRY = re.compile(r"The credit expires\s+(\d+)\s+days after activation", re.I)
_CEREBRAS_NOCHARGE = re.compile(r"You will not be charged or automatically enrolled", re.I)


def cerebras_promo_credit(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _CEREBRAS_CREDIT.search(text)
    exp = _CEREBRAS_EXPIRY.search(text)
    if not m or not exp:
        return []
    amount, days = m.group(1), exp.group(1)
    nocharge = _CEREBRAS_NOCHARGE.search(text)
    end = max(m.end(), exp.end(), nocharge.end() if nocharge else 0)
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Cerebras Inference",
        title=f"Credito promocional de Cerebras: USD {amount} por {days} dias",
        offer_type="CREDITS",
        benefit=(
            f"La documentacion oficial declara un credito promocional unico de USD {amount} "
            f"al agregar un metodo de pago valido, que vence a los {days} dias de activado. "
            + ("La pagina afirma que no se cobra ni se enrola automaticamente en uso pago. "
               if nocharge else "")
            + "El nivel gratuito es para desarrollo, evaluacion y experimentacion; "
              "no esta pensado para produccion."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, m.start(), end, 60),
        extraction_rule="html:credito promocional + vencimiento + condicion de metodo de pago",
        price_baseline=None, price_offer=None, price_unit="USD (credito)",
        currency="USD", discount_pct=None,
        eligibility=(
            "Cuenta Cerebras con un metodo de pago valido agregado. Credito unico, "
            "no transferible, sin valor en efectivo; puede revocarse por fraude o abuso."
        ),
        card_required="yes", auto_renewal="no", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Requiere metodo de pago (publicado). La pagina declara que no hay cargo ni "
            "enrolamiento automatico; al vencer o agotarse el credito, el acceso a API y "
            "Playground se pausa salvo compra de creditos PayGo. No es descuento porcentual. "
            "Pais y elegibilidad argentina: No confirmado."
        ),
        dedupe_extra=source.id, tags=["creditos", "api", "requiere-tarjeta"],
        benefit_kind="CREDITO",
    )]


_MODAL_CREDIT = re.compile(r"\$(\d+)\s*/\s*month free credits", re.I)
_MODAL_PLAN = re.compile(r"\$0\s*\+\s*compute\s*/\s*month", re.I)


def modal_free_credits(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _MODAL_CREDIT.search(text)
    if not m:
        return []
    amount = m.group(1)
    plan = _MODAL_PLAN.search(text)
    end = max(m.end(), plan.end() if plan else 0)
    start = min(m.start(), plan.start() if plan else m.start())
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Modal (plan Starter)",
        title=f"Modal Starter: USD {amount} mensuales de computo incluidos",
        offer_type="CREDITS",
        benefit=(
            f"El plan Starter figura a USD 0 + computo por mes e incluye USD {amount} "
            "mensuales de creditos de computo, 3 asientos de workspace, 100 contenedores "
            "+ 10 GPU de concurrencia y 1 TiB/mes de egreso de red gratuito. El computo "
            "por encima del credito incluido se factura por uso."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, start, end, 80),
        extraction_rule="html:plan Starter + creditos mensuales de computo",
        price_baseline=None, price_offer=None, price_unit="USD / mes (credito de computo)",
        currency="USD", discount_pct=None,
        eligibility="Cuenta Modal en plan Starter; el credito se renueva cada mes.",
        card_required="unknown", auto_renewal="unknown", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Es credito de computo incluido, no un descuento: no hay precio de lista "
            "comparable. Los endpoints y el uso por encima del credito son facturables. "
            "Tarjeta, pais y vencimiento: No confirmado en la pagina."
        ),
        dedupe_extra=source.id, tags=["creditos", "infraestructura", "mensual"],
        benefit_kind="CREDITO",
    )]


_AZURE_STUDENT = re.compile(
    r"Azure for Students gets you started with \$(\d+) in Azure credits to be used "
    r"within the first (\d+) months", re.I)
_AZURE_STUDENT_NOCARD = re.compile(r"without requiring a credit card at sign-up", re.I)
_AZURE_STUDENT_ELIG = re.compile(r"You must affirm that you are age 18 or older", re.I)


def azure_student_credit(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _AZURE_STUDENT.search(text)
    if not m:
        return []
    amount, months = m.group(1), m.group(2)
    nocard = _AZURE_STUDENT_NOCARD.search(text)
    elig = _AZURE_STUDENT_ELIG.search(text)
    end = max(m.end(), nocard.end() if nocard else 0, elig.end() if elig else 0)
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Azure for Students",
        title=f"Azure for Students: USD {amount} de credito en {months} meses, sin tarjeta",
        offer_type="STUDENT",
        benefit=(
            f"Microsoft declara USD {amount} en creditos de Azure para usar dentro de los "
            f"primeros {months} meses, mas servicios gratuitos seleccionados"
            + (", sin requerir tarjeta de credito al registrarse." if nocard else ".")
            + " Los creditos no usados no se acumulan ni se transfieren a otras "
              "suscripciones."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, m.start(), end, 60),
        extraction_rule="html:credito estudiantil + plazo + condicion de tarjeta",
        price_baseline=None, price_offer=None, price_unit="USD (credito)",
        currency="USD", discount_pct=None,
        eligibility=(
            "Solo estudiantes: hay que afirmar tener 18 anos o mas y asistir a una "
            "institucion educativa acreditada que otorgue titulos de dos o cuatro anos, "
            "como estudiante de tiempo completo."
        ),
        card_required="no" if nocard else "unknown",
        auto_renewal="no", student_required="yes",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Beneficio estudiantil, no descuento porcentual. La pagina declara que no se "
            "requiere tarjeta al registrarse. Los creditos vencen a los 12 meses y no son "
            "transferibles. Disponibilidad en Argentina: No confirmado."
        ),
        dedupe_extra=source.id, tags=["estudiantil", "creditos", "cloud", "sin-tarjeta"],
        benefit_kind="BENEFICIO_ESTUDIANTIL",
    )]


_GCP_TRIAL = re.compile(
    r"preloaded with \$(\d+) in free Welcome credit which is valid for (\d+) days", re.I)
_GCP_NOCHARGE = re.compile(r"you won't be charged unless you manually upgrade", re.I)
_GCP_CARD = re.compile(r"You can use your personal credit card to verify your identity", re.I)


def gcp_free_trial(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _GCP_TRIAL.search(text)
    if not m:
        return []
    amount, days = m.group(1), m.group(2)
    nocharge = _GCP_NOCHARGE.search(text)
    card = _GCP_CARD.search(text)
    end = max(m.end(), nocharge.end() if nocharge else 0, card.end() if card else 0)
    start = min(m.start(), nocharge.start() if nocharge else m.start(),
                card.start() if card else m.start())
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Google Cloud Free Trial",
        title=f"Google Cloud: USD {amount} de credito de bienvenida por {days} dias",
        offer_type="CREDITS",
        benefit=(
            f"La cuenta de facturacion de prueba se precarga con USD {amount} de credito "
            f"de bienvenida valido por {days} dias. La pagina declara que la cuenta se "
            "cierra sola al gastar el credito o cumplirse el plazo, y que no hay cargos "
            "salvo upgrade manual a una cuenta paga. Tambien se pueden usar los productos "
            "Free Tier hasta sus limites mensuales."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, start, end, 60),
        extraction_rule="html:credito de bienvenida + validez + politica de cargos",
        price_baseline=None, price_offer=None, price_unit="USD (credito)",
        currency="USD", discount_pct=None,
        eligibility=(
            "Cuentas nuevas elegibles para Google Cloud Free Trial. Se usa una tarjeta "
            "personal para verificar identidad; no hace falta tarjeta corporativa."
        ),
        card_required="yes" if card else "unknown",
        auto_renewal="no", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Credito de bienvenida con vencimiento, no descuento. Se requiere tarjeta "
            "para verificar identidad, pero la pagina afirma que no hay cargos mientras "
            "no se haga upgrade manual. Pais y elegibilidad concreta: No confirmado."
        ),
        dedupe_extra=source.id, tags=["creditos", "cloud", "prueba", "requiere-tarjeta"],
        benefit_kind="CREDITO",
    )]


_AWS_EDUCATE_NOCARD = re.compile(r"No credit card needed", re.I)
_AWS_EDUCATE = re.compile(
    r"Learners as young as (\d+) can register for AWS Educate with just an email "
    r"address, gaining access to free hands-on labs", re.I)


def aws_educate(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _AWS_EDUCATE.search(text)
    nocard = _AWS_EDUCATE_NOCARD.search(text)
    if not m or not nocard:
        return []
    age = m.group(1)
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="AWS Educate",
        title=f"AWS Educate: laboratorios gratuitos sin tarjeta, desde {age} anos",
        offer_type="STUDENT",
        benefit=(
            f"AWS declara que estudiantes desde {age} anos pueden registrarse en AWS "
            "Educate solo con un correo electronico, accediendo a laboratorios practicos "
            "gratuitos para aprender y practicar cloud. La pagina indica explicitamente "
            "'No credit card needed'."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, min(m.start(), nocard.start()),
                                   max(m.end(), nocard.end()), 60),
        extraction_rule="html:registro sin tarjeta + laboratorios gratuitos + edad minima",
        price_baseline=None, price_offer=None, price_unit=None, currency=None,
        discount_pct=None,
        eligibility=(
            f"Estudiantes desde {age} anos, registro con correo electronico. Pensado "
            "para aprendizaje principiante y conexion con empleo."
        ),
        card_required="no", auto_renewal="no", student_required="yes",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Son recursos y laboratorios de aprendizaje, NO creditos para APIs de IA: "
            "la pagina no publica creditos de ese tipo y no se inventan. Sin tarjeta "
            "(publicado). Disponibilidad en Argentina: No confirmado."
        ),
        dedupe_extra=source.id, tags=["estudiantil", "laboratorios", "sin-tarjeta"],
        benefit_kind="BENEFICIO_ESTUDIANTIL",
    )]


_AZURE_FREE = re.compile(
    r"Get free services and a \$(\d+) credit to explore Azure for up to (\d+) days", re.I)
_AZURE_FREE_ALWAYS = re.compile(r"Free monthly amounts of 65\+ always-free services", re.I)
_AZURE_FREE_HOLD = re.compile(r"temporary \$1 authorization placed on your card", re.I)


def azure_free_account(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _AZURE_FREE.search(text)
    if not m:
        return []
    amount, days = m.group(1), m.group(2)
    always = _AZURE_FREE_ALWAYS.search(text)
    hold = _AZURE_FREE_HOLD.search(text)
    end = max(m.end(), always.end() if always else 0, hold.end() if hold else 0)
    start = min(m.start(), always.start() if always else m.start(),
                hold.start() if hold else m.start())
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product="Azure free account",
        title=f"Cuenta gratuita de Azure: USD {amount} de credito por {days} dias",
        offer_type="CREDITS",
        benefit=(
            f"Microsoft declara servicios gratuitos mas USD {amount} de credito para "
            f"explorar Azure hasta {days} dias"
            + (", y cantidades mensuales gratuitas de 65+ servicios siempre gratuitos."
               if always else ".")
            + " Hay proteccion de gasto: la tarjeta no se cobra, y hay que pasar a "
              "pay-as-you-go para continuar tras el plazo o al agotar el credito."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, start, end, 60),
        extraction_rule="html:credito de cuenta gratuita + plazo + servicios siempre gratuitos",
        price_baseline=None, price_offer=None, price_unit="USD (credito)",
        currency="USD", discount_pct=None,
        eligibility=(
            "Clientes nuevos de Azure. Durante la verificacion puede colocarse una "
            "autorizacion temporal de USD 1 que se revierte al verificar."
        ),
        card_required="yes" if hold else "unknown",
        auto_renewal="no", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            "Credito con vencimiento mas servicios gratuitos, no descuento porcentual. "
            "Se pide tarjeta para verificacion (autorizacion temporal de USD 1 revertida), "
            "con proteccion de gasto declarada. Pais: No confirmado. Es una oferta distinta "
            "de Azure for Students: no se mezclan ni se duplican."
        ),
        dedupe_extra=source.id, tags=["creditos", "cloud", "requiere-tarjeta"],
        benefit_kind="CREDITO",
    )]


_FIREWORKS_FREE = re.compile(r"([A-Za-z0-9 .\-]+?) is free through ([A-Za-z]+ \d{1,2})", re.I)
_FIREWORKS_NOCARD = re.compile(r"No credit card required", re.I)


def fireworks_free_model(source: Source, res: FetchResult) -> list[Candidate]:
    text = ht.to_text(res.text)
    m = _FIREWORKS_FREE.search(text)
    nocard = _FIREWORKS_NOCARD.search(text)
    if not m or not nocard:
        return []
    model, until = ht.collapse(m.group(1)), m.group(2)
    if len(model) > 80:
        return []
    return [Candidate(
        source_id=source.id, provider_key=source.provider_key,
        product=f"Fireworks AI ({model})",
        title=f"Fireworks: {model} gratis hasta el {until}",
        offer_type="TRIAL",
        benefit=(
            f"La pagina de precios declara que {model} es gratuito hasta el {until} "
            "en la UI y en la Serverless Training API, y que no se requiere tarjeta de "
            "credito. El resto del uso se factura con creditos prepagos."
        ),
        official_url=source.url, evidence_url=source.url,
        evidence_snippet=ht.snippet(text, m.start(), max(m.end(), nocard.end()), 60),
        extraction_rule="html:modelo gratuito por tiempo limitado + condicion de tarjeta",
        price_baseline=None, price_offer=None, price_unit=None, currency=None,
        discount_pct=None,
        eligibility="Cuenta Fireworks; oferta acotada a la UI y la Serverless Training API.",
        card_required="no", auto_renewal="unknown", student_required="no",
        argentina_status="ARGENTINA_NO_CONFIRMADA", terms_url=source.terms_url,
        confidence="alta",
        notes=(
            f"Acceso gratuito por tiempo limitado (hasta el {until}), no un descuento "
            "porcentual ni un plan gratuito permanente. La pagina no explicita el ano del "
            "vencimiento: no se inventa ni se fija expires_at. Tarjeta no requerida "
            "(publicado). Pais: No confirmado."
        ),
        dedupe_extra=slug(model), tags=["prueba", "tiempo-limitado", "sin-tarjeta"],
        benefit_kind="PRUEBA_GRATUITA",
    )]


EXTRACTORS = {
    "openrouter_free_models": openrouter_free_models,
    "deepseek_offpeak": deepseek_offpeak,
    "html_free_allocation": html_free_allocation,
    "rss_promotions": rss_promotions,
    "kiro_free_plan": kiro_free_plan,
    "html_monthly_credit": html_monthly_credit,
    "groq_free_plan": groq_free_plan,
    "stability_welcome_credits": stability_welcome_credits,
    "cohere_trial_key": cohere_trial_key,
    "alibaba_free_quota": alibaba_free_quota,
    "cerebras_promo_credit": cerebras_promo_credit,
    "modal_free_credits": modal_free_credits,
    "azure_student_credit": azure_student_credit,
    "gcp_free_trial": gcp_free_trial,
    "aws_educate": aws_educate,
    "azure_free_account": azure_free_account,
    "fireworks_free_model": fireworks_free_model,
}


def extract(source: Source, res: FetchResult) -> list[Candidate]:
    fn = EXTRACTORS.get(source.extractor)
    if not fn:
        return []
    try:
        return fn(source, res)
    except Exception:
        return []
