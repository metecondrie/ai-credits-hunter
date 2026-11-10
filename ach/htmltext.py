"""Conversion de HTML/XML a texto y utilidades de evidencia.

Todo snippet que se guarda como evidencia sale de aca: es texto literal de la
pagina, con espacios colapsados, nunca reconstruido por el modelo.
"""

from __future__ import annotations

import html as html_mod
import re

_BLOCK = re.compile(r"(?is)<(script|style|svg|noscript|template)[^>]*>.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")

_MONEY = re.compile(r"\$\s?([0-9][0-9.,]*)")
_PCT = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s?%")


def to_text(markup: str) -> str:
    """HTML -> texto plano legible, preservando el orden de lectura."""
    if not markup:
        return ""
    txt = _BLOCK.sub(" ", markup)
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article|table)>", "\n", txt)
    txt = _TAG.sub(" ", txt)
    txt = html_mod.unescape(txt)
    txt = txt.replace("\u00a0", " ").replace("\u200b", "")
    txt = _WS.sub(" ", txt)
    lines = [ln.strip() for ln in txt.split("\n")]
    txt = "\n".join(ln for ln in lines if ln)
    return _NL.sub("\n\n", txt).strip()


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def snippet(text: str, start: int, end: int, pad: int = 160) -> str:
    """Ventana de texto alrededor de un match, recortada en limite de palabra."""
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    frag = collapse(text[lo:hi])
    if lo > 0:
        frag = "..." + frag
    if hi < len(text):
        frag = frag + "..."
    return frag[:600]


def find_all(text: str, pattern: str, flags: int = re.I) -> list[re.Match]:
    return list(re.finditer(pattern, text or "", flags))


def first_snippet(text: str, pattern: str, pad: int = 160) -> tuple[str, str] | None:
    m = re.search(pattern, text or "", re.I)
    if not m:
        return None
    return m.group(0), snippet(text, m.start(), m.end(), pad)


def parse_money(raw: str) -> float | None:
    """'$0.011' / '$1,234.50' / '0,15' -> float. Devuelve None si no se puede."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[-1]) <= 2:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def money_in(text: str) -> list[float]:
    out = []
    for m in _MONEY.finditer(text or ""):
        v = parse_money(m.group(1))
        if v is not None:
            out.append(v)
    return out


def percent_in(text: str) -> list[float]:
    out = []
    for m in _PCT.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            continue
    return out


def trim(text: str, limit: int = 400) -> str:
    text = collapse(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "..."
