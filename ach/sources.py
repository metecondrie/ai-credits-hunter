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
        url="https://api-docs.deepseek.com/quick_start/pricing/",
        kind="html",
        extractor="deepseek_offpeak",
        official_domain="api-docs.deepseek.com",
        priority="A",
        cadence_hours=12,
        terms_url="https://api-docs.deepseek.com/",
        # Sin la barra final el host estatico responde HTTP 200 con el documento
        # "Your First API Call": la tabla de precios no esta y el extractor da 0.
        notes="Pagina Docusaurus renderizada en servidor con tabla PEAK / OFF-PEAK "
              "en USD por 1M tokens, una columna por modelo. La barra final es obligatoria.",
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
            "benefit_kind": "CUOTA_GRATUITA",
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
            "benefit_kind": "CREDITO",
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
    # --- P1.1: fuentes oficiales adicionales verificables -------------------
    Source(
        id="groq-free-plan",
        name="GroqCloud - Free Plan Limits",
        provider_key="groq",
        url="https://console.groq.com/docs/rate-limits",
        kind="html",
        extractor="groq_free_plan",
        official_domain="console.groq.com",
        priority="B",
        cadence_hours=24,
        terms_url="https://console.groq.com/docs/billing-faqs",
        notes="Cuotas del plan Free por modelo, publicadas en el payload 'freeRows'. "
              "Las del plan Developer ('devRows') NO se mezclan: son otro plan.",
    ),
    Source(
        id="stability-welcome-credits",
        name="Stability AI - Creditos de bienvenida",
        provider_key="stability",
        url="https://platform.stability.ai/pricing",
        kind="html",
        extractor="stability_welcome_credits",
        official_domain="platform.stability.ai",
        priority="B",
        cadence_hours=24,
        terms_url="https://platform.stability.ai/docs/getting-started",
        notes="Creditos iniciales gratuitos y equivalencia credito/USD declaradas en "
              "la pagina de precios. Requiere cuenta y API key.",
    ),
    Source(
        id="cohere-trial-key",
        name="Cohere - Clave de evaluacion gratuita",
        provider_key="cohere",
        url="https://docs.cohere.com/docs/rate-limits",
        kind="html",
        extractor="cohere_trial_key",
        official_domain="docs.cohere.com",
        priority="B",
        cadence_hours=24,
        terms_url="https://docs.cohere.com/docs/rate-limits",
        notes="Clave de evaluacion gratuita con tope mensual declarado. No es acceso "
              "de produccion ni ilimitado: las claves production son pagas.",
    ),
    # --- P1.2: ampliacion masiva de fuentes oficiales -----------------------
    Source(
        id="alibaba-model-studio-free-quota",
        name="Alibaba Cloud Model Studio - Cuota gratuita nuevos usuarios",
        provider_key="alibaba",
        url="https://www.alibabacloud.com/help/en/model-studio/new-free-quota",
        kind="html", extractor="alibaba_free_quota",
        official_domain="alibabacloud.com", priority="A", cadence_hours=24,
        enabled=False,
        terms_url="https://www.alibabacloud.com/help/en/model-studio/",
        notes="Cuota gratuita por 90 dias. RIESGO: al agotarse se factura automaticamente; "
              "la proteccion 'Free Quota Only' viene desactivada por defecto. "
              "DESHABILITADA: el parser de robots del motor reduce las reglas con "
              "comodin ('/*.json') al prefijo '/', bloqueando todo el host. El extractor "
              "y su fixture estan listos; reactivar cuando se corrija ese parser.",
    ),
    Source(
        id="cerebras-promo-credit",
        name="Cerebras Inference - Credito promocional",
        provider_key="cerebras",
        url="https://inference-docs.cerebras.ai/support/pricing",
        kind="html", extractor="cerebras_promo_credit",
        official_domain="cerebras.ai", priority="B", cadence_hours=24,
        terms_url="https://inference-docs.cerebras.ai/support/pricing",
        notes="Credito unico de USD 5 a 30 dias agregando metodo de pago. La tabla de "
              "tiers es cliente; se extrae solo el texto publicado en el HTML.",
    ),
    Source(
        id="modal-free-credits",
        name="Modal - Creditos de computo del plan Starter",
        provider_key="modal",
        url="https://modal.com/pricing",
        kind="html", extractor="modal_free_credits",
        official_domain="modal.com", priority="B", cadence_hours=24,
        terms_url="https://modal.com/pricing",
        notes="USD 30 mensuales de computo incluidos en Starter. El computo excedente "
              "y los endpoints son facturables: no es un descuento.",
    ),
    Source(
        id="azure-for-students",
        name="Azure for Students - Credito estudiantil",
        provider_key="azure",
        url="https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p",
        kind="html", extractor="azure_student_credit",
        official_domain="azure.microsoft.com", priority="A", cadence_hours=24,
        terms_url="https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p",
        notes="USD 100 a 12 meses, sin tarjeta al registrarse. Solo estudiantes "
              "mayores de 18 en institucion acreditada de tiempo completo.",
    ),
    Source(
        id="gcp-free-trial",
        name="Google Cloud Free Trial - Credito de bienvenida",
        provider_key="google",
        url="https://cloud.google.com/signup-faqs",
        kind="html", extractor="gcp_free_trial",
        official_domain="cloud.google.com", priority="A", cadence_hours=24,
        terms_url="https://cloud.google.com/free/docs/free-cloud-features",
        notes="USD 300 por 90 dias para cuentas nuevas. Tarjeta personal para verificar "
              "identidad; sin cargos salvo upgrade manual.",
    ),
    Source(
        id="aws-educate",
        name="AWS Educate - Laboratorios gratuitos",
        provider_key="aws",
        url="https://aws.amazon.com/education/awseducate/",
        kind="html", extractor="aws_educate",
        official_domain="aws.amazon.com", priority="B", cadence_hours=24,
        enabled=False,
        terms_url="https://aws.amazon.com/education/awseducate/",
        notes="Laboratorios y recursos de aprendizaje sin tarjeta, desde 13 anos. "
              "No publica creditos para APIs de IA: no se inventan. "
              "DESHABILITADA: el parser de robots del motor reduce las reglas con "
              "comodin ('/*/blogs/') al prefijo '/', bloqueando todo el host. El "
              "extractor y su fixture estan listos; reactivar al corregir ese parser.",
    ),
    Source(
        id="azure-free-account",
        name="Azure free account - Credito y servicios gratuitos",
        provider_key="azure",
        url="https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account",
        kind="html", extractor="azure_free_account",
        official_domain="azure.microsoft.com", priority="A", cadence_hours=24,
        terms_url="https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account",
        notes="USD 200 por 30 dias mas 65+ servicios siempre gratuitos. Oferta distinta "
              "de Azure for Students: no se duplica.",
    ),
    Source(
        id="fireworks-free-model",
        name="Fireworks AI - Modelo gratuito por tiempo limitado",
        provider_key="fireworks",
        url="https://fireworks.ai/pricing",
        kind="html", extractor="fireworks_free_model",
        official_domain="fireworks.ai", priority="B", cadence_hours=24,
        terms_url="https://fireworks.ai/pricing",
        notes="Modelo gratuito hasta una fecha publicada, sin tarjeta. La pagina no "
              "explicita el ano: no se fija expires_at ni se inventa.",
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
    "groq": {
        "name": "GroqCloud",
        "company": "Groq",
        "category": "api",
        "official_domains": "groq.com, console.groq.com",
        "identity_status": "CONFIRMED",
    },
    "stability": {
        "name": "Stability AI",
        "company": "Stability AI",
        "category": "api",
        "official_domains": "stability.ai, platform.stability.ai",
        "identity_status": "CONFIRMED",
    },
    "cohere": {
        "name": "Cohere",
        "company": "Cohere",
        "category": "api",
        "official_domains": "cohere.com, docs.cohere.com",
        "identity_status": "CONFIRMED",
    },
    "alibaba": {
        "name": "Alibaba Cloud Model Studio",
        "company": "Alibaba Cloud",
        "category": "api",
        "official_domains": "alibabacloud.com",
        "identity_status": "CONFIRMED",
    },
    "cerebras": {
        "name": "Cerebras Inference",
        "company": "Cerebras Systems",
        "category": "api",
        "official_domains": "cerebras.ai, inference-docs.cerebras.ai",
        "identity_status": "CONFIRMED",
    },
    "modal": {
        "name": "Modal",
        "company": "Modal Labs",
        "category": "cloud_compute",
        "official_domains": "modal.com",
        "identity_status": "CONFIRMED",
    },
    "azure": {
        "name": "Microsoft Azure",
        "company": "Microsoft",
        "category": "cloud_compute",
        "official_domains": "azure.microsoft.com, microsoft.com",
        "identity_status": "CONFIRMED",
    },
    "aws": {
        "name": "Amazon Web Services",
        "company": "Amazon",
        "category": "cloud_compute",
        "official_domains": "aws.amazon.com, amazon.com",
        "identity_status": "CONFIRMED",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "company": "Fireworks AI",
        "category": "api",
        "official_domains": "fireworks.ai",
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
