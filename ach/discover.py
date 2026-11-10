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


# --------------------------------------------------------------------------
# Verificacion documental de candidatos (P1.5)
# --------------------------------------------------------------------------
STATUS_VERIFIED = "VERIFICADO_DOCUMENTAL"
STATUS_DISCARDED = "DESCARTADO"
STATUS_REVIEW = "REQUIERE_REVISION"
STATUS_ERROR = "ERROR_VERIFICACION"
NO_CONFIRMADO = "No confirmado"
MAX_VERIFY = 10

# Orden de presentacion: primero lo documentado, despues lo pendiente.
STATUS_ORDER = {STATUS_VERIFIED: 0, STATUS_REVIEW: 1, STATUS_PENDING: 2,
                STATUS_ERROR: 3, STATUS_DISCARDED: 4}

# Intencion de oferta dirigida al lector. Se evitan verbos genericos como
# "including" o "receive", que aparecen en cualquier prosa o en la navegacion.
_OFFER_INTENT = re.compile(
    r"(you can|you get|you'll get|we offer|get started|sign up|sign-up|"
    r"at no charge|at no cost|no cost to|free for|free to|up to \$|"
    r"during the preview|for a limited time|no credit card required|"
    r"you receive|can order|available at no)", re.I)

# Contexto ajeno a una oferta: facturacion, contabilidad o relato de un tercero.
_NON_OFFER = re.compile(
    r"(amortiz\w*|billing|invoice|cost after|led to|tracked|case study|"
    r"customer story|\broi\b|paid subscriptions|revenue|accounting|"
    r"how often|success story|customers around the world)", re.I)

# IA: se exigen terminos especificos. "model" o "ML" sueltos aparecen en la
# navegacion de cualquier sitio de cloud y daban falsos positivos.
_AI_CONTEXT = re.compile(
    r"(\bai\b|artificial intelligence|machine learning|\bllm\b|\bllms\b|"
    r"inference|generative|\bgpu\b|bedrock|chatgpt|copilot|sagemaker|"
    r"inteligencia artificial|ia generativa)", re.I)

# Empresarial: sin "customers" ni "teams", que son ruido de navegacion.
_ENTERPRISE = re.compile(
    r"(enterprise|organizations?|for business|startups?|companies|corporate|"
    r"data center|direct connect|interconnect|colocation)", re.I)
_STUDENT = re.compile(r"(verified students?|for students|student pack|"
                      r"education discount|academic|scholarship)", re.I)
_INDIVIDUAL = re.compile(r"(anyone|individual|personal use|new users?|everyone|"
                           r"for developers)", re.I)


def _oracion(text: str, pos: int) -> str:
    """Oracion que contiene la posicion: evita evaluar navegacion o pie de pagina."""
    lo = max(text.rfind(". ", 0, pos), text.rfind("\n", 0, pos)) + 1
    hi = text.find(". ", pos)
    if hi < 0:
        hi = min(len(text), pos + 400)
    return collapse(text[lo:hi + 1])


def _first(pattern, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return collapse(m.group(0)) if m else NO_CONFIRMADO


def _condiciones(text: str, evidencia: str) -> dict:
    """Extrae solo lo publicado; lo ausente queda 'No confirmado'.

    Importe, duracion, tarjeta y elegibilidad se buscan en la evidencia del
    beneficio, no en toda la pagina: el menu y el pie traen condiciones ajenas.
    """
    foco = evidencia or text
    tarjeta = NO_CONFIRMADO
    if re.search(r"no credit card (required|needed)|without (a )?credit card", foco, re.I):
        tarjeta = "no"
    elif re.search(r"(credit card|payment method|valid payment|card to verify)", foco, re.I):
        tarjeta = "si (se menciona metodo de pago o tarjeta)"
    if _STUDENT.search(foco):
        elegibilidad = "estudiantil"
    elif _ENTERPRISE.search(foco):
        elegibilidad = "empresarial"
    elif _INDIVIDUAL.search(foco):
        elegibilidad = "individual"
    elif _ENTERPRISE.search(text):
        elegibilidad = "empresarial (contexto de la pagina, no del fragmento)"
    else:
        elegibilidad = NO_CONFIRMADO
    geo = _first(r"(available in [A-Z][^.;]{0,80}|[A-Z][a-z]+ \([A-Z][a-z .]+\) Region|Argentina)", foco)
    return {
        "importe": _first(r"(US[D\$]\s?[\d,.]+|\$\s?[\d,.]+|\d[\d,]*\s+(free )?credits?|\d+\s+Gbps)", foco),
        "duracion": _first(r"(during the preview|for a limited time|\d+\s+(days|months|years)|one year|until [A-Z][a-z]+ \d{1,2})", foco),
        "tarjeta": tarjeta,
        "elegibilidad": elegibilidad,
        "geografia": geo,
        "argentina": "mencionada (revisar contexto)" if re.search(r"argentina", foco, re.I) else NO_CONFIRMADO,
        "relacionado_con_ia": bool(_AI_CONTEXT.search(foco)),
    }


def _evaluar_texto(text: str) -> tuple[str, str, list[str]]:
    """Decide el estado por la ORACION que contiene el beneficio, sin prejuzgar.

    Evaluar una ventana amplia alrededor de la frase contaminaba el resultado
    con la navegacion y los CTA del sitio (un 'free trial' del menu no es una
    oferta del articulo). Se descartan fragmentos cortos, tipicos de menu.
    """
    fuertes, ruido, ambiguas = [], [], []
    vistas = set()
    for m in _RELEVANCE.finditer(text):
        oracion = _oracion(text, m.start())
        if len(oracion) < 30 or oracion in vistas:
            continue
        vistas.add(oracion)
        intent = _OFFER_INTENT.search(oracion)
        ajeno = _NON_OFFER.search(oracion)
        if intent and not ajeno:
            fuertes.append(oracion)
        elif ajeno:
            ruido.append(oracion)
        else:
            ambiguas.append(oracion)

    if not (fuertes or ruido or ambiguas):
        return (STATUS_DISCARDED,
                "La pagina no contiene lenguaje de beneficio en contenido legible: "
                "la frase del feed no aparece o solo esta en navegacion.", [])
    if fuertes:
        return (STATUS_VERIFIED,
                "Beneficio explicito en la misma oracion, con intencion de oferta "
                "dirigida al usuario (gratuidad, disponibilidad o plazo declarado).",
                fuertes[:3])
    if ruido and not ambiguas:
        return (STATUS_DISCARDED,
                "La frase de beneficio aparece en contexto ajeno a una oferta "
                "(facturacion, contabilidad o relato de un tercero): falso positivo.",
                ruido[:3])
    return (STATUS_REVIEW,
            "Hay lenguaje de beneficio pero la oracion es ambigua o no aclara "
            "elegibilidad ni condiciones: requiere revision humana.",
            (ambiguas or ruido)[:3])


def verify_candidate(c: dict, fetcher: HttpFetcher) -> dict:
    """Visita una URL y devuelve los campos de verificacion para ese candidato."""
    url = c.get("url", "")
    base = {"verification_url": url, "checked_at_utc": utcnow()}
    try:
        res = fetcher.fetch(url)
    except Exception as exc:                       # red caida, timeout, TLS
        return {**base, "status": STATUS_ERROR,
                "reason": f"Fallo de transporte: {type(exc).__name__}: {str(exc)[:160]}",
                "evidence": [], "http_status": 0, "conditions": {}}
    base["http_status"] = res.status
    if res.blocked_by_robots:
        return {**base, "status": STATUS_ERROR,
                "reason": "robots.txt prohibe la ruta: no se visita ni se elude el bloqueo.",
                "evidence": [], "conditions": {}}
    if res.status != 200 or not res.text:
        return {**base, "status": STATUS_ERROR,
                "reason": f"Pagina inaccesible (HTTP {res.status}). {res.error or ''}".strip(),
                "evidence": [], "conditions": {}}

    from .htmltext import to_text
    text = to_text(res.text)
    if len(text) < 200:
        return {**base, "status": STATUS_ERROR,
                "reason": "La pagina no sirve contenido legible (probable render por "
                          "JavaScript): no hay evidencia literal que comprobar.",
                "evidence": [], "conditions": {}}

    status, reason, evidencia = _evaluar_texto(text)
    cond = _condiciones(text, " ".join(evidencia))
    aplicabilidad = ""
    if status == STATUS_VERIFIED:
        if cond["elegibilidad"].startswith("empresarial"):
            aplicabilidad = ("Oferta genuina pero de alcance EMPRESARIAL: no aplicable a "
                             "usuarios individuales.")
        if not cond["relacionado_con_ia"]:
            aplicabilidad = (aplicabilidad + " No se detecta relacion explicita con IA "
                             "en el contenido: infraestructura o servicio general.").strip()
    return {**base, "status": status, "reason": reason, "evidence": evidencia,
            "conditions": cond, "aplicabilidad": aplicabilidad,
            "content_sha256": res.sha256 or ""}


def verify_candidates(path: Path | None = None,
                      fetcher: HttpFetcher | None = None,
                      limit: int = MAX_VERIFY) -> dict:
    """Verifica hasta `limit` candidatos pendientes, sin navegacion recursiva."""
    f = fetcher or HttpFetcher()
    todos = load_candidates(path)
    pendientes = [c for c in todos if c.get("status") == STATUS_PENDING][:max(0, limit)]
    resultados = []
    for c in pendientes:
        upd = verify_candidate(c, f)
        c.update(upd)
        resultados.append(c)
    if resultados:
        save_candidates(todos, path)
    conteo = {}
    for c in resultados:
        conteo[c["status"]] = conteo.get(c["status"], 0) + 1
    return {
        "examined": len(resultados),
        "pending_left": sum(1 for c in todos if c.get("status") == STATUS_PENDING),
        "by_status": conteo,
        "results": resultados,
        "total_saved": len(todos),
        "path": str(Path(path) if path else CANDIDATES_PATH),
    }


def sorted_candidates(path: Path | None = None) -> list[dict]:
    """Documentadas primero, pendientes despues; el resto al final."""
    return sorted(load_candidates(path),
                  key=lambda c: (STATUS_ORDER.get(c.get("status", ""), 9),
                                 c.get("discovered_at_utc", "")))
