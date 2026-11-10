"""Persistencia SQLite: migraciones versionadas, integridad y consultas.

Reglas:
- `PRAGMA foreign_keys=ON` en toda conexion (no es el default de SQLite).
- Migraciones idempotentes, con checksum: si un archivo aplicado cambia, se
  aborta en vez de seguir con un esquema distinto al registrado.
- Ninguna escritura fuera de la base de ensayo (ver config.resolve_db).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config
from .classify import band_of
from .models import Candidate

TRACKED_FIELDS = [
    "title", "benefit", "price_baseline", "price_offer", "price_unit",
    "discount_pct", "discount_band", "argentina_status", "card_required",
    "expires_at", "verification_level", "confidence", "official_url",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[int]:
    """Aplica migraciones pendientes. Devuelve las versiones aplicadas ahora."""
    mdir = migrations_dir or config.MIGRATIONS_DIR
    files = sorted(mdir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No hay migraciones en {mdir}")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
               version INTEGER PRIMARY KEY,
               applied_at_utc TEXT NOT NULL,
               checksum TEXT NOT NULL,
               description TEXT)"""
    )
    applied = {row["version"]: row["checksum"] for row in conn.execute(
        "SELECT version, checksum FROM schema_version")}

    newly: list[int] = []
    for f in files:
        try:
            version = int(f.name.split("_", 1)[0])
        except ValueError:
            continue
        sql = f.read_text(encoding="utf-8")
        digest = _checksum(sql)
        if version in applied:
            if applied[version] != digest:
                raise RuntimeError(
                    f"Migracion {f.name} ya aplicada con otro contenido "
                    f"(registrado {applied[version][:12]}, actual {digest[:12]}). "
                    "No se continua con un esquema divergente."
                )
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at_utc, checksum, description) "
            "VALUES (?,?,?,?)",
            (version, utcnow(), digest, f.stem),
        )
        conn.commit()
        newly.append(version)
    return newly


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"] or 0)
    except sqlite3.Error:
        return 0


# --------------------------------------------------------------------------
# Semilla de proveedores y fuentes
# --------------------------------------------------------------------------
def seed(conn: sqlite3.Connection, providers: dict, sources: Iterable) -> None:
    now = utcnow()
    for key, meta in providers.items():
        conn.execute(
            """INSERT INTO provider (provider_key, name, company, category,
                                     official_domains, identity_status, created_utc)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(provider_key) DO UPDATE SET
                 name=excluded.name, company=excluded.company,
                 category=excluded.category, official_domains=excluded.official_domains""",
            (key, meta["name"], meta.get("company"), meta.get("category"),
             meta.get("official_domains"), meta.get("identity_status", "CONFIRMED"), now),
        )
    for s in sources:
        conn.execute(
            """INSERT INTO source (source_id, name, provider_key, url, kind, extractor,
                                   priority, cadence_hours, enabled)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, kind=excluded.kind,
                 extractor=excluded.extractor, priority=excluded.priority,
                 cadence_hours=excluded.cadence_hours, enabled=excluded.enabled""",
            (s.id, s.name, s.provider_key, s.url, s.kind, s.extractor,
             s.priority, s.cadence_hours, 1 if s.enabled else 0),
        )
    conn.commit()


# --------------------------------------------------------------------------
# Corridas
# --------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, mode: str, total: int) -> int:
    cur = conn.execute(
        "INSERT INTO run (started_utc, mode, sources_total) VALUES (?,?,?)",
        (utcnow(), mode, total),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, **fields: Any) -> None:
    allowed = {
        "sources_ok", "sources_failed", "sources_skipped", "candidates",
        "offers_new", "offers_seen", "offers_changed", "errors", "notes",
    }
    sets = ["finished_utc=?"]
    values: list[Any] = [utcnow()]
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            values.append(v)
    values.append(run_id)
    conn.execute(f"UPDATE run SET {', '.join(sets)} WHERE run_id=?", values)
    conn.commit()


def record_source_run(conn: sqlite3.Connection, run_id: int, source_id: str,
                      url: str, http_status: int | None, nbytes: int | None,
                      elapsed_ms: int | None, candidates: int, error: str | None) -> None:
    conn.execute(
        """INSERT INTO source_run (run_id, source_id, url, http_status, bytes,
                                   elapsed_ms, candidates, error, at_utc)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (run_id, source_id, url, http_status, nbytes, elapsed_ms, candidates, error, utcnow()),
    )
    conn.execute(
        """UPDATE source SET last_run_utc=?, last_http_status=?, last_error=?,
                             last_candidates=?
           WHERE source_id=?""",
        (utcnow(), http_status, error, candidates, source_id),
    )
    conn.commit()


def update_source_cache(conn: sqlite3.Connection, source_id: str, etag: str | None,
                        last_modified: str | None, sha256: str | None) -> None:
    conn.execute(
        "UPDATE source SET last_etag=?, last_modified=?, last_sha256=? WHERE source_id=?",
        (etag, last_modified, sha256, source_id),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Ofertas
# --------------------------------------------------------------------------
def _row_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def upsert_offer(conn: sqlite3.Connection, c: Candidate, run_id: int,
                 level: str, source_id: str) -> tuple[int, str, list[str]]:
    """Inserta o actualiza. Devuelve (offer_id, evento, campos_cambiados)."""
    key = c.dedupe_key()
    now = utcnow()
    band = band_of(c)
    existing = conn.execute(
        "SELECT * FROM offer WHERE dedupe_key=?", (key,)
    ).fetchone()

    new_values = {
        "title": c.title,
        "benefit": c.benefit,
        "price_baseline": c.price_baseline,
        "price_offer": c.price_offer,
        "price_unit": c.price_unit,
        "discount_pct": c.discount_pct,
        "discount_band": band,
        "argentina_status": c.argentina_status,
        "card_required": c.card_required,
        "expires_at": c.expires_at,
        "verification_level": level,
        "confidence": c.confidence,
        "official_url": c.official_url,
    }

    if existing is None:
        cur = conn.execute(
            """INSERT INTO offer (dedupe_key, provider_key, source_id, product, title,
                    offer_type, benefit, price_baseline, price_offer, price_unit, currency,
                    discount_pct, discount_band, eligibility, card_required, auto_renewal,
                    student_required, argentina_status, official_url, terms_url, starts_at,
                    expires_at, published_at, time_window_art, confidence, verification_level,
                    status, notes, first_seen_utc, last_seen_utc, created_utc, updated_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, c.provider_key, source_id, c.product, c.title, c.offer_type, c.benefit,
             c.price_baseline, c.price_offer, c.price_unit, c.currency, c.discount_pct,
             band, c.eligibility, c.card_required, c.auto_renewal, c.student_required,
             c.argentina_status, c.official_url, c.terms_url, c.starts_at, c.expires_at,
             c.published_at, c.time_window_art, c.confidence, level, "NUEVA", c.notes,
             now, now, now, now),
        )
        offer_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
            "VALUES (?,?,?,?,?)", (offer_id, run_id, "NUEVA", "", now))
        conn.commit()
        return offer_id, "NUEVA", []

    changed = [f for f in TRACKED_FIELDS
               if (existing[f] if f in existing.keys() else None) != new_values.get(f)]
    offer_id = int(existing["offer_id"])

    sets = ", ".join(f"{f}=?" for f in new_values)
    conn.execute(
        f"UPDATE offer SET {sets}, last_seen_utc=?, updated_utc=?, "
        f"status=CASE WHEN status IN ('EXPIRADA','RETIRADA') THEN 'CAMBIADA' ELSE ? END "
        f"WHERE offer_id=?",
        list(new_values.values()) + [now, now, "CAMBIADA" if changed else "VISTA", offer_id],
    )
    event = "CAMBIADA" if changed else "VISTA"
    conn.execute(
        "INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
        "VALUES (?,?,?,?,?)",
        (offer_id, run_id, event, ",".join(changed), now),
    )
    conn.commit()
    return offer_id, event, changed


def add_evidence(conn: sqlite3.Connection, offer_id: int, run_id: int, source_id: str,
                 url: str, http_status: int, sha256: str | None, etag: str | None,
                 last_modified: str | None, snippet: str, rule: str, level: str) -> None:
    conn.execute(
        """INSERT INTO evidence (offer_id, run_id, source_id, url, http_status,
               content_sha256, etag, last_modified, snippet, extraction_rule,
               observed_at_utc, verification_level)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (offer_id, run_id, source_id, url, http_status, sha256, etag,
         last_modified, snippet, rule, utcnow(), level),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Interpretaciones de IA (tabla separada; la evidencia original NO se toca)
# --------------------------------------------------------------------------
def add_ai_assessment(conn: sqlite3.Connection, offer_id: int, run_id: int | None,
                      provider: str, model: str, is_offer, benefit_type: str,
                      conditions: str, restrictions: str, argentina_eligibility: str,
                      confidence: str, justification: str, cost_status: str,
                      raw_response: str = "", error: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO ai_assessment
               (offer_id, run_id, provider, model, is_offer, benefit_type,
                conditions, restrictions, argentina_eligibility, confidence,
                justification, cost_status, raw_response, error, created_at_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (offer_id, run_id, provider, model,
         None if is_offer is None else (1 if is_offer else 0),
         benefit_type, conditions, restrictions, argentina_eligibility,
         confidence, justification, cost_status, raw_response, error, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_ai_assessments(conn: sqlite3.Connection, offer_id: int) -> list[dict]:
    return [_row_dict(r) for r in conn.execute(
        "SELECT * FROM ai_assessment WHERE offer_id=? ORDER BY ai_id DESC", (offer_id,))]


def latest_ai_by_offer(conn: sqlite3.Connection) -> dict[int, dict]:
    """Ultima interpretacion IA por oferta (para badges del listado)."""
    rows = conn.execute(
        """SELECT a.* FROM ai_assessment a
           JOIN (SELECT offer_id, MAX(ai_id) AS max_id FROM ai_assessment GROUP BY offer_id) m
             ON a.ai_id = m.max_id"""
    ).fetchall()
    return {int(r["offer_id"]): _row_dict(r) for r in rows}


def expire_offers(conn: sqlite3.Connection, run_id: int | None = None,
                  retire_after_days: int = 60) -> int:
    """Marca EXPIRADA por fecha vencida y RETIRADA por no volver a verse."""
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    rows = conn.execute(
        "SELECT offer_id, expires_at FROM offer "
        "WHERE status NOT IN ('EXPIRADA','RETIRADA') AND expires_at IS NOT NULL "
        "AND substr(expires_at,1,10) < ?", (today,)).fetchall()
    for r in rows:
        conn.execute("UPDATE offer SET status='EXPIRADA', updated_utc=? WHERE offer_id=?",
                     (utcnow(), r["offer_id"]))
        conn.execute("INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
                     "VALUES (?,?,?,?,?)", (r["offer_id"], run_id, "EXPIRADA", "expires_at", utcnow()))
        n += 1

    stale = conn.execute(
        "SELECT offer_id FROM offer WHERE status NOT IN ('EXPIRADA','RETIRADA') "
        "AND julianday('now') - julianday(last_seen_utc) > ?", (retire_after_days,)).fetchall()
    for r in stale:
        conn.execute("UPDATE offer SET status='RETIRADA', updated_utc=? WHERE offer_id=?",
                     (utcnow(), r["offer_id"]))
        conn.execute("INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
                     "VALUES (?,?,?,?,?)", (r["offer_id"], run_id, "RETIRADA", "last_seen", utcnow()))
        n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------
def list_offers(conn: sqlite3.Connection, q: str | None = None,
                band: str | None = None, ar: str | None = None,
                offer_type: str | None = None, level: str | None = None,
                status: str | None = None, include_closed: bool = False,
                min_discount: float | None = None,
                order: str = "discount", limit: int = 200, offset: int = 0) -> list[dict]:
    where = []
    args: list[Any] = []
    if q:
        where.append("(product LIKE ? OR title LIKE ? OR benefit LIKE ? OR provider_name LIKE ?)")
        args += [f"%{q}%"] * 4
    if band:
        where.append("discount_band = ?")
        args.append(band)
    if ar:
        where.append("argentina_status = ?")
        args.append(ar)
    if offer_type:
        where.append("offer_type = ?")
        args.append(offer_type)
    if level:
        where.append("verification_level = ?")
        args.append(level)
    if status:
        where.append("status = ?")
        args.append(status)
    if not include_closed and not status:
        where.append("status NOT IN ('EXPIRADA','RETIRADA')")
    if min_discount is not None:
        where.append("discount_pct IS NOT NULL AND discount_pct >= ?")
        args.append(min_discount)

    order_sql = {
        "discount": "discount_pct DESC NULLS LAST, last_seen_utc DESC",
        "recent": "last_seen_utc DESC, offer_id DESC",
        "provider": "provider_name ASC, product ASC",
        "price": "price_offer ASC NULLS LAST",
    }.get(order, "discount_pct DESC NULLS LAST, last_seen_utc DESC")

    sql = "SELECT * FROM v_offer_public"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [_row_dict(r) for r in conn.execute(sql, args)]


def get_offer(conn: sqlite3.Connection, offer_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM v_offer_public WHERE offer_id=?", (offer_id,)).fetchone()
    if not row:
        return None
    offer = _row_dict(row)
    offer["evidence"] = [_row_dict(r) for r in conn.execute(
        "SELECT * FROM evidence WHERE offer_id=? ORDER BY evidence_id DESC", (offer_id,))]
    offer["events"] = [_row_dict(r) for r in conn.execute(
        "SELECT * FROM offer_event WHERE offer_id=? ORDER BY event_id DESC LIMIT 20", (offer_id,))]
    return offer


def stats(conn: sqlite3.Connection) -> dict:
    def one(sql: str, args: tuple = ()) -> Any:
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else None

    by_band = {r["discount_band"]: r["n"] for r in conn.execute(
        "SELECT discount_band, COUNT(*) n FROM offer GROUP BY discount_band ORDER BY n DESC")}
    by_ar = {r["argentina_status"]: r["n"] for r in conn.execute(
        "SELECT argentina_status, COUNT(*) n FROM offer GROUP BY argentina_status ORDER BY n DESC")}
    by_level = {r["verification_level"]: r["n"] for r in conn.execute(
        "SELECT verification_level, COUNT(*) n FROM offer GROUP BY verification_level")}
    last = conn.execute("SELECT * FROM run ORDER BY run_id DESC LIMIT 1").fetchone()
    return {
        "offers": one("SELECT COUNT(*) FROM offer") or 0,
        "active": one("SELECT COUNT(*) FROM offer WHERE status NOT IN ('EXPIRADA','RETIRADA')") or 0,
        "network_verified": one("SELECT COUNT(*) FROM offer WHERE verification_level='NETWORK_VERIFIED'") or 0,
        "evidence": one("SELECT COUNT(*) FROM evidence") or 0,
        "sources": one("SELECT COUNT(*) FROM source") or 0,
        "runs": one("SELECT COUNT(*) FROM run") or 0,
        "by_band": by_band,
        "by_argentina": by_ar,
        "by_level": by_level,
        "last_run": _row_dict(last) if last else None,
    }


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    return [_row_dict(r) for r in conn.execute(
        "SELECT * FROM source ORDER BY priority, source_id")]


def list_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [_row_dict(r) for r in conn.execute(
        "SELECT * FROM run ORDER BY run_id DESC LIMIT ?", (limit,))]
