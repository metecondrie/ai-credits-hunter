"""Pipeline: fuente oficial -> HTTP -> extraccion -> clasificacion -> SQLite.

Una corrida real nunca fabrica ofertas: si la fuente falla, se registra el error
y la corrida sigue. Si no hay coincidencias, el resultado es cero ofertas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import classify, config, extract, sources as src_mod, store
from .fetch import FetchResult, HttpFetcher, utcnow
from .sources import PROVIDERS, Source


@dataclass
class SourceOutcome:
    source_id: str
    url: str
    http_status: int
    candidates: int
    error: str | None = None
    skipped: str | None = None
    elapsed_ms: int = 0
    bytes: int = 0


@dataclass
class RunReport:
    run_id: int
    mode: str
    started_utc: str
    finished_utc: str
    outcomes: list[SourceOutcome] = field(default_factory=list)
    candidates: int = 0
    offers_new: int = 0
    offers_seen: int = 0
    offers_changed: int = 0
    errors: int = 0
    expired: int = 0
    db_path: str = ""
    ai_classified: int = 0
    ai_blocked: int = 0

    @property
    def sources_ok(self) -> int:
        return sum(1 for o in self.outcomes if o.candidates > 0 or (o.http_status == 200 and not o.error))

    @property
    def sources_failed(self) -> int:
        return sum(1 for o in self.outcomes if o.error and not o.skipped)

    @property
    def sources_skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.skipped)


def _fixture_result(source: Source, fixture_dir: Path) -> FetchResult:
    for ext in (".json", ".html", ".xml", ".rss", ".txt"):
        p = fixture_dir / f"{source.id}{ext}"
        if p.exists():
            raw = p.read_bytes()
            import hashlib
            return FetchResult(
                url=source.url,
                status=200,
                text=raw.decode("utf-8", errors="replace"),
                sha256=hashlib.sha256(raw).hexdigest(),
                etag=None,
                last_modified=None,
                fetched_at_utc=utcnow(),
                bytes_read=len(raw),
                headers={"x-fixture": str(p)},
            )
    return FetchResult(url=source.url, status=0, error=f"SIN_FIXTURE:{source.id}")


def _touch_source_offers(conn, run_id: int, source_id: str) -> None:
    """304 Not Modified: la fuente no cambio, las ofertas siguen vigentes."""
    now = utcnow()
    rows = conn.execute(
        "SELECT offer_id FROM offer WHERE source_id=? AND status NOT IN ('EXPIRADA','RETIRADA')",
        (source_id,)).fetchall()
    for r in rows:
        conn.execute("UPDATE offer SET last_seen_utc=?, updated_utc=?, status='VISTA' WHERE offer_id=?",
                     (now, now, r["offer_id"]))
        conn.execute("INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
                     "VALUES (?,?,?,?,?)", (r["offer_id"], run_id, "VISTA", "sin_cambios_304", now))
    conn.commit()


def run(
    db_path: Path | None = None,
    source_ids: list[str] | None = None,
    fixture_dir: Path | None = None,
    fetcher: HttpFetcher | None = None,
    limit_per_source: int | None = None,
    quiet: bool = False,
    use_ai: bool = False,
    ai_store=None,
    ai_http_post=None,
) -> RunReport:
    path = config.resolve_db(db_path)
    config.ensure_dirs()

    conn = store.connect(path)
    store.migrate(conn)
    selected = src_mod.enabled_sources(source_ids)
    store.seed(conn, PROVIDERS, src_mod.SOURCES)

    mode = "fixtures" if fixture_dir else "live"
    run_id = store.start_run(conn, mode, len(selected))
    started = utcnow()
    report = RunReport(run_id=run_id, mode=mode, started_utc=started,
                       finished_utc="", db_path=str(path))

    f = fetcher or HttpFetcher()

    for source in selected:
        if not quiet:
            print(f"[{source.id}] {source.url}")

        if fixture_dir:
            res = _fixture_result(source, Path(fixture_dir))
        else:
            cached = conn.execute(
                "SELECT last_etag, last_modified FROM source WHERE source_id=?",
                (source.id,)).fetchone()
            res = f.fetch(source.url,
                          etag=cached["last_etag"] if cached else None,
                          last_modified=cached["last_modified"] if cached else None)

        if res.not_modified:
            _touch_source_offers(conn, run_id, source.id)
            outcome = SourceOutcome(source.id, source.url, 304, 0, skipped="SIN_CAMBIOS_304")
            report.outcomes.append(outcome)
            store.record_source_run(conn, run_id, source.id, source.url, 304,
                                    res.bytes_read, res.elapsed_ms, 0, None)
            if not quiet:
                print("   -> 304 sin cambios")
            continue

        if not res.ok:
            outcome = SourceOutcome(source.id, source.url, res.status, 0,
                                    error=res.error or "ERROR")
            report.outcomes.append(outcome)
            report.errors += 1
            store.record_source_run(conn, run_id, source.id, source.url, res.status,
                                    res.bytes_read, res.elapsed_ms, 0, res.error)
            if not quiet:
                print(f"   -> ERROR {res.error}")
            continue

        cands = extract.extract(source, res)
        if limit_per_source:
            cands = cands[:limit_per_source]

        stored = 0
        for c in cands:
            c = classify.assess(c, res.status, fixture=bool(fixture_dir))
            level = classify.verification_level(c, res.status, fixture=bool(fixture_dir))
            offer_id, event, _changed = store.upsert_offer(conn, c, run_id, level, source.id)
            store.add_evidence(conn, offer_id, run_id, source.id, c.evidence_url,
                               res.status, res.sha256, res.etag, res.last_modified,
                               c.evidence_snippet, c.extraction_rule, level)
            stored += 1
            if use_ai:
                # Clasificacion semantica OPCIONAL: se guarda en ai_assessment
                # (tabla separada). Un fallo o bloqueo de la IA NUNCA rompe la
                # corrida ni altera la evidencia original.
                from . import ai_classify
                outcome = ai_classify.classify_candidate(
                    c, store=ai_store, http_post=ai_http_post)
                if outcome.ok:
                    a = outcome.assessment
                    store.add_ai_assessment(
                        conn, offer_id, run_id, outcome.provider, outcome.model,
                        a.is_offer, a.benefit_type, a.conditions, a.restrictions,
                        a.argentina_eligibility, a.confidence, a.justification,
                        outcome.cost_status, raw_response=a.raw_response)
                    report.ai_classified += 1
                    if not quiet:
                        print(f"   -> IA [{outcome.provider}/{outcome.model}] "
                              f"oferta={a.is_offer} tipo={a.benefit_type}")
                else:
                    store.add_ai_assessment(
                        conn, offer_id, run_id, outcome.provider or "-",
                        outcome.model or "-", None, None, None, None, None, None,
                        None, outcome.cost_status or "",
                        error=f"{outcome.blocked}: {outcome.detail}")
                    report.ai_blocked += 1
                    if not quiet:
                        print(f"   -> IA bloqueada: {outcome.blocked}")
            if event == "NUEVA":
                report.offers_new += 1
            elif event == "CAMBIADA":
                report.offers_changed += 1
            else:
                report.offers_seen += 1

        report.candidates += stored
        store.update_source_cache(conn, source.id, res.etag, res.last_modified, res.sha256)
        store.record_source_run(conn, run_id, source.id, source.url, res.status,
                                res.bytes_read, res.elapsed_ms, stored, None)
        report.outcomes.append(SourceOutcome(source.id, source.url, res.status, stored,
                                             elapsed_ms=res.elapsed_ms, bytes=res.bytes_read))
        if not quiet:
            print(f"   -> {stored} candidatos")

    report.expired = store.expire_offers(conn, run_id)
    report.finished_utc = utcnow()
    store.finish_run(
        conn, run_id,
        sources_ok=report.sources_ok,
        sources_failed=report.sources_failed,
        sources_skipped=report.sources_skipped,
        candidates=report.candidates,
        offers_new=report.offers_new,
        offers_seen=report.offers_seen,
        offers_changed=report.offers_changed,
        errors=report.errors,
        notes=f"http_requests={f.stats['requests']} bytes={f.stats['bytes']} "
              f"ai_classified={report.ai_classified} ai_blocked={report.ai_blocked}",
    )
    conn.close()
    return report


def summary_line(report: RunReport) -> str:
    return (
        f"run#{report.run_id} {report.mode} | fuentes {len(report.outcomes)} "
        f"(ok {report.sources_ok}, fallas {report.sources_failed}, sin cambios {report.sources_skipped}) "
        f"| candidatos {report.candidates} | nuevas {report.offers_new} "
        f"| vistas {report.offers_seen} | cambiadas {report.offers_changed} "
        f"| vencidas {report.expired} | errores {report.errors}"
        f" | IA: {report.ai_classified} clasificadas, {report.ai_blocked} bloqueadas"
    )
