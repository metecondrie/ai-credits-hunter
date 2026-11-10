"""Cliente HTTP determinista, cortes y respetuoso.

- Solo biblioteca estandar (urllib).
- Limite de tamano, timeouts, reintentos con backoff.
- ETag / Last-Modified para no re-descargar lo que no cambio.
- robots.txt por host (si prohibe, la fuente se omite y se informa).
- Un request por host cada HOST_MIN_INTERVAL_SEC como maximo.
- Nunca usa proxies, VPN ni evasiones.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import config


@dataclass
class FetchResult:
    url: str
    status: int = 0
    text: str = ""
    sha256: str = ""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    fetched_at_utc: str = ""
    elapsed_ms: int = 0
    error: Optional[str] = None
    not_modified: bool = False
    bytes_read: int = 0
    blocked_by_robots: bool = False
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _robots_match(rule: str, target: str) -> bool:
    """Empareja una regla de robots.txt con comodin '*' y ancla final '$'.

    Antes se comparaba solo el prefijo previo al '*', asi que una regla como
    '/*.json' o '/*/blogs/*/tag/' se reducia a '/' y bloqueaba el host entero.
    El comodin vale cualquier secuencia; el resto de la regla es literal.
    """
    ancla = rule.endswith("$")
    cuerpo = rule[:-1] if ancla else rule
    patron = "".join(".*" if c == "*" else re.escape(c) for c in cuerpo)
    return re.match("^" + patron + ("$" if ancla else ""), target) is not None


class _Robots:
    """Cache de robots.txt por host, con parser minimo."""

    def __init__(self) -> None:
        self._cache: dict[str, list[str]] = {}

    def _disallow_for_all(self, body: str) -> list[str]:
        rules: list[str] = []
        applies = False
        for raw in body.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                applies = value == "*"
            elif key == "disallow" and applies and value:
                rules.append(value)
        return rules

    def allowed(self, url: str, fetcher: "HttpFetcher") -> bool:
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._cache:
            rules: list[str] = []
            try:
                res = fetcher._raw_get(host + "/robots.txt", timeout=6, max_bytes=200_000)
                if res.status == 200:
                    rules = self._disallow_for_all(res.text)
            except Exception:
                rules = []
            self._cache[host] = rules
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        for rule in self._cache[host]:
            if _robots_match(rule, path):
                return False
        return True


class HttpFetcher:
    def __init__(
        self,
        timeout: float | None = None,
        retries: int | None = None,
        delay: float | None = None,
        max_bytes: int | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout = timeout if timeout is not None else config.HTTP_TIMEOUT_SEC
        self.retries = retries if retries is not None else config.HTTP_RETRIES
        self.delay = delay if delay is not None else config.HTTP_DELAY_SEC
        self.max_bytes = max_bytes if max_bytes is not None else config.HTTP_MAX_BYTES
        self.user_agent = user_agent or config.USER_AGENT
        self.robots = _Robots()
        self._last_host_hit: dict[str, float] = {}
        self.stats = {"requests": 0, "bytes": 0, "errors": 0, "robots_blocked": 0}

    # -- internos ---------------------------------------------------------
    def _throttle(self, host: str) -> None:
        now = time.monotonic()
        last = self._last_host_hit.get(host, 0.0)
        wait = config.HOST_MIN_INTERVAL_SEC - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._last_host_hit[host] = time.monotonic()

    def _decode(self, raw: bytes, encoding: str | None) -> str:
        enc = (encoding or "").lower()
        if enc == "gzip":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except Exception:
                pass
        elif enc == "deflate":
            try:
                raw = zlib.decompress(raw)
            except Exception:
                try:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    pass
        for charset in ("utf-8", "latin-1"):
            try:
                return raw.decode(charset)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def _raw_get(self, url: str, timeout: float, max_bytes: int,
                 headers: dict | None = None) -> FetchResult:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": self.user_agent})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(max_bytes + 1)
                truncated = len(raw) > max_bytes
                raw = raw[:max_bytes]
                text = self._decode(raw, resp.headers.get("Content-Encoding"))
                return FetchResult(
                    url=url,
                    status=resp.getcode() or 0,
                    text=text,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                    fetched_at_utc=utcnow(),
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    bytes_read=len(raw),
                    error="TRUNCADO_A_LIMITE" if truncated else None,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read(max_bytes)
            except Exception:
                pass
            finally:
                try:
                    exc.close()
                except Exception:
                    pass
            return FetchResult(
                url=url,
                status=exc.code,
                text=self._decode(body, exc.headers.get("Content-Encoding") if exc.headers else None),
                sha256=hashlib.sha256(body).hexdigest() if body else "",
                fetched_at_utc=utcnow(),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"HTTP {exc.code} {exc.reason}",
            )
        except Exception as exc:  # URLError, timeout, SSL, DNS
            return FetchResult(
                url=url,
                status=0,
                fetched_at_utc=utcnow(),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )

    # -- publico ----------------------------------------------------------
    def fetch(self, url: str, etag: str | None = None,
              last_modified: str | None = None,
              respect_robots: bool = True) -> FetchResult:
        host = urllib.parse.urlsplit(url).netloc

        if respect_robots and not self.robots.allowed(url, self):
            self.stats["robots_blocked"] += 1
            return FetchResult(
                url=url, status=0, fetched_at_utc=utcnow(),
                blocked_by_robots=True,
                error="OMITIDO_POR_ROBOTS_TXT",
            )

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es-AR;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        last_error = None
        for attempt in range(self.retries + 1):
            self._throttle(host)
            self.stats["requests"] += 1
            res = self._raw_get(url, self.timeout, self.max_bytes, headers)
            self.stats["bytes"] += res.bytes_read

            if res.status == 304:
                res.not_modified = True
                return res
            if res.ok:
                return res

            last_error = res
            retryable = res.status == 0 or res.status in (429, 500, 502, 503, 504)
            if not retryable or attempt >= self.retries:
                break
            time.sleep(min(8.0, self.delay * (2 ** attempt) + 0.5))

        self.stats["errors"] += 1
        return last_error or FetchResult(url=url, status=0, error="ERROR_DESCONOCIDO")
