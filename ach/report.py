"""Reportes: Markdown legible, CSV y JSON, siempre con procedencia."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config, store
from .pipeline import RunReport


def _fmt_price(v, unit, currency) -> str:
    if v is None:
        return "N/D"
    u = (unit or "").strip()
    cur = (currency or "").strip()
    prefix = "" if (cur and cur.lower() in u.lower()) else cur
    body = f"{v:g}"
    if u:
        body += f" {u}"
    return f"{prefix} {body}".strip()


def _fmt_disc(o: dict) -> str:
    if o["discount_pct"] is None:
        return "sin base"
    return f"{o['discount_pct']:.1f}%"


def write_markdown(conn, report: RunReport, out_dir: Path | None = None) -> Path:
    out = Path(out_dir or config.REPORTS_DIR)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"reporte_{stamp}.md"

    offers = store.list_offers(conn, order="discount", limit=500, include_closed=True)
    stats = store.stats(conn)
    lines: list[str] = []
    a = lines.append

    a(f"# AI Credits Hunter v4 - Reporte de corrida {report.run_id}")
    a("")
    a(f"- Inicio: {report.started_utc}")
    a(f"- Fin: {report.finished_utc}")
    a(f"- Modo: **{report.mode}**")
    a(f"- Base: `{report.db_path}`")
    a(f"- Fuentes: {len(report.outcomes)} (ok {report.sources_ok}, fallas {report.sources_failed}, "
      f"sin cambios {report.sources_skipped})")
    a(f"- Candidatos: {report.candidates} | nuevas {report.offers_new} | "
      f"vistas {report.offers_seen} | cambiadas {report.offers_changed} | vencidas {report.expired}")
    a("")
    a("## Estado de la base")
    a("")
    a(f"- Ofertas totales: {stats['offers']} (activas {stats['active']})")
    a(f"- Verificadas por red: {stats['network_verified']}")
    a(f"- Evidencias registradas: {stats['evidence']}")
    a(f"- Por banda: {', '.join(f'{k}={v}' for k, v in stats['by_band'].items()) or 'sin datos'}")
    a(f"- Por nivel: {', '.join(f'{k}={v}' for k, v in stats['by_level'].items()) or 'sin datos'}")
    a("")

    a("## Ofertas")
    a("")
    a("| # | Proveedor | Producto | Tipo | Precio normal | Precio oferta | Desc. | AR | Verificacion |")
    a("|---|---|---|---|---|---|---|---|---|")
    for i, o in enumerate(offers, 1):
        a(f"| {i} | {o['provider_name']} | {o['product'][:48]} | {o['offer_type']} | "
          f"{_fmt_price(o['price_baseline'], o['price_unit'], o['currency'])} | "
          f"{_fmt_price(o['price_offer'], o['price_unit'], o['currency'])} | "
          f"{_fmt_disc(o)} | {o['argentina_status']} | {o['verification_level']} |")
    a("")

    a("## Detalle y evidencia")
    a("")
    for o in offers:
        a(f"### {o['provider_name']} - {o['product']}")
        a("")
        a(f"- **Titulo**: {o['title']}")
        a(f"- **Tipo**: {o['offer_type']} | **Estado**: {o['status']} | **Confianza**: {o['confidence']}")
        a(f"- **Beneficio**: {o['benefit']}")
        a(f"- **Precio**: {_fmt_price(o['price_baseline'], o['price_unit'], o['currency'])} -> "
          f"{_fmt_price(o['price_offer'], o['price_unit'], o['currency'])} "
          f"({_fmt_disc(o)}, banda {o['discount_band']})")
        a(f"- **Tarjeta**: {o['card_required']} | **Auto-renovacion**: {o['auto_renewal']} | "
          f"**Argentina**: {o['argentina_status']}")
        if o.get("time_window_art"):
            a(f"- **Horario**: {o['time_window_art']}")
        a(f"- **Oficial**: {o['official_url']}")
        a(f"- **Verificacion**: {o['verification_level']} | Evidencias: {o['evidence_count']}")
        if o.get("last_evidence_url"):
            a(f"- **Evidencia**: {o['last_evidence_url']}")
        a("")

    a("## Fuentes")
    a("")
    a("| Fuente | HTTP | Candidatos | Error |")
    a("|---|---|---|---|")
    for o in report.outcomes:
        a(f"| {o.source_id} | {o.http_status} | {o.candidates} | {o.error or o.skipped or '-'} |")
    a("")
    a("---")
    a("Generado por AI Credits Hunter v4. Sin APIs pagas. Los datos provienen de las URLs citadas;")
    a("una respuesta HTTP 200 no se interpreta como promocion confirmada.")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_json(conn, path: Path | None = None) -> Path:
    out = Path(path or (config.REPORTS_DIR / "ofertas_v4.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    offers = []
    for o in store.list_offers(conn, order="recent", limit=5000, include_closed=True):
        full = store.get_offer(conn, o["offer_id"])
        offers.append(full)
    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(offers),
        "offers": offers,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def export_csv(conn, path: Path | None = None) -> Path:
    out = Path(path or (config.REPORTS_DIR / "ofertas_v4.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = store.list_offers(conn, order="discount", limit=5000, include_closed=True)
    fields = ["offer_id", "provider_name", "product", "title", "offer_type", "price_baseline",
              "price_offer", "price_unit", "currency", "discount_pct", "discount_band",
              "argentina_status", "card_required", "auto_renewal", "official_url",
              "confidence", "verification_level", "status", "first_seen_utc", "last_seen_utc"]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return out
