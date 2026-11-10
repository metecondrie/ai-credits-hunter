"""Descubrimiento de enlaces candidatos desde feeds publicos y gratuitos.

Un enlace descubierto NO es una oferta verificada: queda en estado
PENDIENTE_VERIFICACION, se guarda en un JSON local y NO se promueve al catalogo
de extractores ni a la base de ofertas. Verificarlo es una decision posterior.

Limites deliberados: solo feeds oficiales, solo dominios conocidos, tope de
items y de enlaces, robots.txt respetado por el HttpFetcher y retardo minimo
por host. No se usan buscadores pagos ni APIs de inferencia.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from . import config, sources
from .extract import _iso_date, _rss_items
from .fetch import HttpFetcher, utcnow
from .htmltext import collapse, trim

# Feeds oficiales adicionales al RSS que ya sigue el cazador. Se verificaron
# accesibles y con items el 2026-11-10 (HTTP 200, robots permitido).
EXTRA_FEEDS = [
    {"id": "aws-whats-new", "provider_key": "aws",
     "url": "https://aws.amazon.com/about-aws/whats-new/recent/feed/"},
    {"id": "cloudflare-blog", "provider_key": "cloudflare",
     "url": "https://blog.cloudflare.com/rss/"},
    {"id": "nvidia-blog", "provider_key": "nvidia",
     "url": "https://blogs.nvidia.com/feed/"},
]

# Puntos de partida: los tres RSS que el cazador ya consulta.
RSS_SEEDS = ("openai-news-rss", "google-ai-blog-rss", "huggingface-blog-rss")

STATUS_PENDING = "PENDIENTE_VERIFICACION"
CANDIDATES_PATH = config.DATA_DIR / "discovered_candidates.json"

MAX_FEEDS = 8
MAX_ITEMS_PER_FEED = 100
MAX_LINKS = 400

# Lenguaje de BENEFICIO, no de tema. Se exigen frases que denoten una oportunidad
# (gratuidad, credito, descuento, prueba o beneficio estudiantil). Palabras sueltas
# como "credit", "student", "education" o "pricing" matchean noticias institucionales
# sin beneficio (por ejemplo "Credit Saison" o "Australian universities"), que el
# extractor RSS del cazador ya filtra: no se reintroducen aqui.
_RELEVANCE = re.compile(
    r"(free[- ]tier|free[- ]plan|free[- ]trial|free credits?|free usage|"
    r"included credits?|monthly credits?|promotional credits?|welcome credit|"
    r"activate credits?|no[- ]cost|at no charge|complimentary|"
    r"\d{1,2}\s?%\s?off|discount|price drop|special offer|limited[- ]time offer|"
    r"free for students|student pack|education discount|education pricing|"
    r"scholarship|aws educate|github education|"
    r"gratis|gratuito|cr[e\u00e9]ditos? gratuit|descuento|promoci[o\u00f3]n|"
    r"prueba gratuita|beneficio estudiantil|precio especial)",
    re.I,
)

# Parametros de seguimiento que se descartan al normalizar.
_TRACKING = re.compile(
    r"^(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|igshid|"
    r"ref|ref_src|ref_url|_ga|spm|vero_id|wickedid|cmpid|campaignid)$", re.I
)


def discovery_feeds() -> list[dict]:
    """Los tres RSS del cazador mas los feeds oficiales adicionales."""
    out = []
    for sid in RSS_SEEDS:
        s = sources.BY_ID.get(sid)
        if s:
            out.append({"id": s.id, "url": s.url, "provider_key": s.provider_key})
    out.extend(EXTRA_FEEDS)
    return out[:MAX_FEEDS]


def official_hosts() -> set[str]:
    """Dominios oficiales conocidos: proveedores del catalogo y hosts de feeds."""
    hosts = set()
    for p in sources.PROVIDERS.values():
        for d in str(p.get("official_domains", "")).split(","):
            d = d.strip().lower()
            if d:
                hosts.add(d)
                hosts.add("www." + d)
    for f in discovery_feeds():
        h = urllib.parse.urlsplit(f["url"]).netloc.lower()
        hosts.add(h)
        hosts.add(h.split(":")[0])
    # El blog de NVIDIA y el de Cloudflare viven en subdominios propios.
    hosts.update({"nvidia.com", "www.nvidia.com", "blogs.nvidia.com",
                  "cloudflare.com", "www.cloudflare.com", "blog.cloudflare.com"})
    return hosts


def normalize_url(url: str) -> str:
    """Normaliza para deduplicar: sin fragmento ni parametros de seguimiento."""
    try:
        parts = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    if host.endswith(":80") and parts.scheme == "http":
        host = host[:-3]
    elif host.endswith(":443") and parts.scheme == "https":
        host = host[:-4]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = []
    for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if not _TRACKING.match(k):
            kept.append((k, v))
    query = urllib.parse.urlencode(sorted(kept))
    return urllib.parse.urlunsplit((parts.scheme.lower(), host, path, query, ""))


def load_candidates(path: Path | None = None) -> list[dict]:
    p = Path(path) if path else CANDIDATES_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    cands = data.get("candidates", []) if isinstance(data, dict) else data
    return [c for c in cands if isinstance(c, dict) and c.get("url")]


def save_candidates(candidates: list[dict], path: Path | None = None) -> Path:
    p = Path(path) if path else CANDIDATES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "updated_utc": utcnow(), "candidates": candidates}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def discover(fetcher: HttpFetcher | None = None,
             path: Path | None = None,
             max_items: int = MAX_ITEMS_PER_FEED) -> dict:
    """Recorre los feeds, extrae enlaces relevantes y guarda los candidatos nuevos.

    No visita los enlaces descubiertos: solo los registra como pendientes.
    """
    f = fetcher or HttpFetcher()
    feeds = discovery_feeds()
    hosts = official_hosts()
    known = {normalize_url(s.url) for s in sources.SOURCES}
    existing = load_candidates(path)
    seen = {c["url"] for c in existing} | known

    examined = 0
    relevant = 0
    feeds_ok = []
    feeds_error = []
    nuevos: list[dict] = []

    for feed in feeds:
        res = f.fetch(feed["url"])
        if res.status != 200 or res.blocked_by_robots:
            feeds_error.append({"id": feed["id"], "http": res.status,
                                "robots": res.blocked_by_robots,
                                "error": res.error or ""})
            continue
        items = _rss_items(res.text)[:max_items]
        feeds_ok.append({"id": feed["id"], "items": len(items)})
        for it in items:
            if examined >= MAX_LINKS:
                break
            examined += 1
            url = normalize_url(it["link"])
            if not url:
                continue
            host = urllib.parse.urlsplit(url).netloc.lower()
            if not any(host == h or host.endswith("." + h) for h in hosts):
                continue                      # fuera de dominios oficiales: se ignora
            blob = f"{it['title']} {it['description']}"
            match = _RELEVANCE.search(blob)
            if not match:
                continue
            relevant += 1
            if url in seen:
                continue                      # duplicado por URL normalizada
            seen.add(url)
            # El fragmento se centra en la frase que disparo la deteccion, no en
            # el inicio de la descripcion: si no, la evidencia no mostraria el motivo.
            lo = max(0, match.start() - 160)
            hi = min(len(blob), match.end() + 240)
            frag = collapse(blob[lo:hi])
            snippet = ("..." if lo > 0 else "") + trim(frag, 420) + ("..." if hi < len(blob) else "")
            nuevos.append({
                "provider": feed["provider_key"],
                "title": trim(it["title"], 200),
                "url": url,
                "original_url": it["link"],
                "discovered_in": feed["id"],
                "published_at": _iso_date(it.get("date", "")),
                "discovered_at_utc": utcnow(),
                "snippet": snippet,
                "matched_phrase": match.group(0),
                "status": STATUS_PENDING,
            })

    if nuevos:
        save_candidates(existing + nuevos, path)

    return {
        "feeds_total": len(feeds),
        "feeds_ok": feeds_ok,
        "feeds_error": feeds_error,
        "links_examined": examined,
        "links_relevant": relevant,
        "new_candidates": len(nuevos),
        "candidates": nuevos,
        "total_saved": len(existing) + len(nuevos),
        "path": str(Path(path) if path else CANDIDATES_PATH),
    }
