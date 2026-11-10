"""Registro declarativo de fuentes publicas.

Cada fuente declara URL, tipo de contenido y el extractor que la interpreta.
No hay busqueda web generica ni scraping de buscadores: solo endpoints y
paginas oficiales de documentacion/precios/anuncios.

`enabled=False` deja la fuente registrada pero fuera de la corrida.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    provider_key: str
    url: str
    kind: str            # json | html | rss
    extractor: str
    official_domain: str
    priority: str = "A"
    cadence_hours: int = 12
    enabled: bool = True
    terms_url: str | None = None
    params: dict = field(default_factory=dict)
    notes: str = ""


SOURCES: list[Source] = [
    Source(
        id="openrouter-free-models",
        name="OpenRouter - catalogo de modelos y precios",
        provider_key="openrouter",
        url="https://openrouter.ai/api/v1/models",
        kind="json",
        extractor="openrouter_free_models",
        official_domain="openrouter.ai",
        priority="A",
        cadence_hours=12,
        terms_url="https://openrouter.ai/docs/limits",
        notes="Endpoint publico JSON. Modelos con pricing.prompt=0 y pricing.completion=0.",
    ),
    Source(
        id="deepseek-pricing",
        name="DeepSeek API - Models & Pricing",
        provider_key="deepseek",
        url="https://api-docs.deepseek.com/quick_start/pricing",
        kind="html",
        extractor="deepseek_offpeak",
        official_domain="api-docs.deepseek.com",
        priority="A",
        cadence_hours=12,
        terms_url="https://api-docs.deepseek.com/",
        notes="Pagina renderizada en servidor con tabla PEAK / OFF-PEAK en USD por 1M tokens.",
    ),
    Source(
        id="cloudflare-workers-ai-pricing",
        name="Cloudflare Workers AI - Pricing",
        provider_key="cloudflare",
        url="https://developers.cloudflare.com/workers-ai/platform/pricing/",
        kind="html",
        extractor="html_free_allocation",
        official_domain="developers.cloudflare.com",
        priority="A",
        cadence_hours=24,
        terms_url="https://developers.cloudflare.com/workers-ai/",
        params={
            "allocation_pattern": (
                r"free allocation allows anyone to use a total of ([\d,]+)\s+Neurons per day at no charge"
            ),
            "unit_pattern": r"\$([\d.]+)\s*per\s*1,?000\s*Neurons",
            "product": "Workers AI",
            "offer_type": "FREE_TIER",
            "price_unit": "USD / 1000 Neurons",
            "title_template": "Asignacion gratuita de {amount} Neurons por dia",
            "benefit_template": (
                "Cloudflare regala {amount} Neurons por dia sin cargo; el excedente se factura "
                "a {unit_price} por 1000 Neurons."
            ),
        },
        notes="Solo texto servido en HTML; si el sitio pasa a render JS la fuente devuelve 0 ofertas.",
    ),
    Source(
        id="kiro-pricing",
        name="Kiro - Pricing (plan gratuito)",
        provider_key="kiro",
        url="https://kiro.dev/pricing",
        kind="html",
        extractor="kiro_free_plan",
        official_domain="kiro.dev",
        priority="A",
        cadence_hours=24,
        terms_url="https://kiro.dev/terms",
        notes="Tabla KIRO FREE / KIRO PRO renderizada en servidor.",
    ),
    Source(
        id="vercel-ai-gateway-pricing",
        name="Vercel AI Gateway - Pricing (credito mensual)",
        provider_key="vercel",
        url="https://vercel.com/docs/ai-gateway/pricing",
        kind="html",
        extractor="html_monthly_credit",
        official_domain="vercel.com",
        priority="B",
        cadence_hours=24,
        terms_url="https://vercel.com/legal/terms",
        params={
            "credit_pattern": r"Monthly credit\s+\$([\d.]+)\s*/\s*month included",
            "product": "Vercel AI Gateway",
            "title_template": "Credito mensual de ${amount} en AI Gateway",
            "benefit_template": (
                "Cada equipo de Vercel recibe ${amount} de credito mensual incluido en AI Gateway, "
                "sin markup de plataforma."
            ),
        },
        notes="Documentacion de precios servida en HTML.",
    ),
    Source(
        id="openai-news-rss",
        name="OpenAI News (RSS)",
        provider_key="openai",
        url="https://openai.com/news/rss.xml",
        kind="rss",
        extractor="rss_promotions",
        official_domain="openai.com",
        priority="B",
        cadence_hours=12,
        terms_url="https://openai.com/policies/terms-of-use/",
        notes="Anuncios oficiales. Solo se retienen items con lenguaje promocional explicito.",
    ),
    Source(
        id="google-ai-blog-rss",
        name="Google AI Blog (RSS)",
        provider_key="google",
        url="https://blog.google/technology/ai/rss/",
        kind="rss",
        extractor="rss_promotions",
        official_domain="blog.google",
        priority="B",
        cadence_hours=12,
        terms_url="https://policies.google.com/terms",
        notes="Anuncios oficiales del blog de IA de Google.",
    ),
    Source(
        id="huggingface-blog-rss",
        name="Hugging Face Blog (RSS)",
        provider_key="huggingface",
        url="https://huggingface.co/blog/feed.xml",
        kind="rss",
        extractor="rss_promotions",
        official_domain="huggingface.co",
        priority="C",
        cadence_hours=24,
        terms_url="https://huggingface.co/terms-of-service",
        notes="Blog oficial; util para creditos, planes Pro y programas educativos.",
    ),
]

BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}

PROVIDERS: dict[str, dict] = {
    "openrouter": {
        "name": "OpenRouter",
        "company": "OpenRouter",
        "category": "api_gateway",
        "official_domains": "openrouter.ai",
        "identity_status": "CONFIRMED",
    },
    "deepseek": {
        "name": "DeepSeek",
        "company": "DeepSeek",
        "category": "api",
        "official_domains": "deepseek.com, api-docs.deepseek.com",
        "identity_status": "CONFIRMED",
    },
    "cloudflare": {
        "name": "Cloudflare Workers AI",
        "company": "Cloudflare",
        "category": "cloud_compute",
        "official_domains": "cloudflare.com, developers.cloudflare.com",
        "identity_status": "CONFIRMED",
    },
    "openai": {
        "name": "OpenAI",
        "company": "OpenAI",
        "category": "api",
        "official_domains": "openai.com",
        "identity_status": "CONFIRMED",
    },
    "google": {
        "name": "Google",
        "company": "Google",
        "category": "api",
        "official_domains": "google.com, blog.google, ai.google.dev",
        "identity_status": "CONFIRMED",
    },
    "huggingface": {
        "name": "Hugging Face",
        "company": "Hugging Face",
        "category": "mlops",
        "official_domains": "huggingface.co",
        "identity_status": "CONFIRMED",
    },
    "kiro": {
        "name": "Kiro (AWS)",
        "company": "Amazon Web Services",
        "category": "ide_agent",
        "official_domains": "kiro.dev",
        "identity_status": "CONFIRMED",
    },
    "vercel": {
        "name": "Vercel AI Gateway",
        "company": "Vercel",
        "category": "api_gateway",
        "official_domains": "vercel.com",
        "identity_status": "CONFIRMED",
    },
}


def enabled_sources(ids: list[str] | None = None) -> list[Source]:
    if ids:
        missing = [i for i in ids if i not in BY_ID]
        if missing:
            raise SystemExit(f"Fuente(s) desconocida(s): {', '.join(missing)}")
        return [BY_ID[i] for i in ids]
    return [s for s in SOURCES if s.enabled]
