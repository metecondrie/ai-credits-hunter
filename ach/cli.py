"""CLI de AI Credits Hunter v4.

    python -m ach init
    python -m ach run
    python -m ach list --band DESCUENTO_50_69
    python -m ach show 3
    python -m ach serve --port 8765
    python -m ach export
    python -m ach doctor
    python -m ach verify --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, classify, config, pipeline, report, sources as src_mod, store
from .fetch import HttpFetcher


def _open(db: str | None, write: bool = True):
    path = config.resolve_db(db)
    if not path.exists() and not write:
        raise SystemExit(f"No existe la base {path}. Ejecuta: python -m ach init")
    conn = store.connect(path)
    if write:
        store.migrate(conn)
        store.seed(conn, src_mod.PROVIDERS, src_mod.SOURCES)
    return path, conn


def cmd_init(args) -> int:
    path = config.resolve_db(args.db)
    conn = store.connect(path)
    applied = store.migrate(conn)
    store.seed(conn, src_mod.PROVIDERS, src_mod.SOURCES)
    v = store.schema_version(conn)
    n_src = conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    conn.close()
    print(f"Base: {path}")
    print(f"Esquema: v{v} (aplicadas ahora: {applied or 'ninguna'})")
    print(f"Fuentes registradas: {n_src}")
    return 0


def cmd_run(args) -> int:
    rep = pipeline.run(
        db_path=Path(args.db) if args.db else None,
        source_ids=args.sources.split(",") if args.sources else None,
        fixture_dir=Path(args.offline) if args.offline else None,
        limit_per_source=args.limit,
        quiet=args.quiet,
        use_ai=args.ai,
    )
    print(pipeline.summary_line(rep))
    path, conn = _open(args.db)
    md = report.write_markdown(conn, rep)
    print(f"Reporte: {md}")
    conn.close()
    return 0 if rep.errors == 0 or rep.candidates > 0 else 2


def cmd_list(args) -> int:
    path, conn = _open(args.db, write=False)
    rows = store.list_offers(
        conn, q=args.q, band=args.band, ar=args.ar, offer_type=args.type,
        level=args.level, status=args.status, include_closed=args.all,
        min_discount=args.min_discount, order=args.order, limit=args.limit,
    )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not rows:
            print("0 ofertas. (Una busqueda sin coincidencias no genera resultados de relleno.)")
        for o in rows:
            disc = (classify.kind_label(o["discount_band"]) if o["discount_pct"] is None
                    else f"{o['discount_pct']:.0f}%")
            print(f"#{o['offer_id']:<4} {o['provider_name'][:16]:<16} "
                  f"{o['product'][:44]:<44} {disc:>8}  {o['verification_level']:<16} "
                  f"{o['argentina_status']}")
    conn.close()
    return 0


def cmd_show(args) -> int:
    path, conn = _open(args.db, write=False)
    o = store.get_offer(conn, args.id)
    if not o:
        print(f"No existe la oferta {args.id}")
        return 1
    print(json.dumps(o, ensure_ascii=False, indent=2))
    conn.close()
    return 0


def cmd_sources(args) -> int:
    path, conn = _open(args.db, write=False)
    for s in store.list_sources(conn):
        print(f"{s['source_id']:<32} {s['kind']:<5} http={s['last_http_status'] or '-':<4} "
              f"cand={s['last_candidates']:<3} {s['last_error'] or ''}")
    conn.close()
    return 0


def cmd_discover(args) -> int:
    from . import discover
    destino = Path(args.out) if args.out else None
    if args.verify:
        res = discover.verify_candidates(path=destino, limit=args.limit)
        print(f"Candidatos examinados: {res['examined']} (tope {args.limit}) | "
              f"pendientes restantes: {res['pending_left']}")
        for c in res["results"]:
            print(f"\n  [{c['status']}] {c.get('title', '')[:74]}")
            print(f"      {c['url']}  (HTTP {c.get('http_status', '-')})")
            print(f"      motivo: {c.get('reason', '')}")
            for e in c.get("evidence", [])[:2]:
                print(f"      evidencia: {e[:240]}")
            cond = c.get("conditions") or {}
            if cond:
                print(f"      importe={cond.get('importe')} | duracion={cond.get('duracion')}")
                print(f"      tarjeta={cond.get('tarjeta')} | elegibilidad={cond.get('elegibilidad')}")
                print(f"      geografia={cond.get('geografia')} | argentina={cond.get('argentina')} "
                      f"| IA={cond.get('relacionado_con_ia')}")
            if c.get("aplicabilidad"):
                print(f"      aplicabilidad: {c['aplicabilidad']}")
        print(f"\nResumen: {res['by_status'] or '{}'}")
        print("La verificacion documental no garantiza vigencia comercial ni elegibilidad.")
        print("Ningun candidato se convierte en oferta del catalogo.")
        print(f"Archivo: {res['path']}")
        return 0
    if args.list:
        cands = discover.sorted_candidates(destino)
        print(f"{len(cands)} candidatos guardados (documentados primero).")
        for c in cands:
            print(f"  [{c.get('status', discover.STATUS_PENDING)}] "
                  f"[{c.get('provider', '?')}] {c.get('title', '')[:66]}")
            print(f"      {c['url']}")
            print(f"      via={c.get('discovered_in', '')} "
                  f"publicado={c.get('published_at') or 'N/D'} "
                  f"comprobado={c.get('checked_at_utc') or 'nunca'}")
            if c.get("reason"):
                print(f"      motivo: {c['reason'][:150]}")
        if not cands:
            print("  (vacio: una busqueda sin coincidencias no genera resultados de relleno.)")
        return 0

    res = discover.discover(path=destino, max_items=args.max_items)
    print(f"Feeds consultados: {len(res['feeds_ok'])}/{res['feeds_total']}")
    for fe in res["feeds_ok"]:
        print(f"  OK    {fe['id']:<22} items={fe['items']}")
    for fe in res["feeds_error"]:
        print(f"  ERROR {fe['id']:<22} http={fe['http']} robots={fe['robots']} "
              f"{fe['error'][:60]}")
    print(f"Enlaces examinados: {res['links_examined']} | "
          f"con lenguaje de oportunidad: {res['links_relevant']}")
    print(f"Candidatos nuevos: {res['new_candidates']} | "
          f"total guardados: {res['total_saved']}")
    for c in res["candidates"]:
        print(f"  [{c['provider']}] {c['title'][:72]}")
        print(f"      {c['url']}")
    if not res["candidates"]:
        print("  (sin candidatos nuevos: no se fabrican resultados.)")
    print(f"Estado: {discover.STATUS_PENDING}. "
          "Un enlace descubierto NO es una oferta verificada.")
    print(f"Archivo: {res['path']}")
    return 0


def cmd_serve(args) -> int:
    from . import web
    web.serve(db_path=Path(args.db) if args.db else None, port=args.port)
    return 0


def cmd_export(args) -> int:
    path, conn = _open(args.db, write=False)
    j = report.export_json(conn, Path(args.out) if args.out else None)
    c = report.export_csv(conn)
    print(f"JSON: {j}\nCSV:  {c}")
    conn.close()
    return 0


def cmd_doctor(args) -> int:
    ok = True
    print(f"Python: {sys.version.split()[0]}")
    path, conn = _open(args.db)
    v = store.schema_version(conn)
    print(f"Base: {path} (esquema v{v})")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fkcheck = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"foreign_keys={fk} integrity={integ} fk_violations={len(fkcheck)}")
    ok = ok and fk == 1 and integ == "ok" and not fkcheck
    stats = store.stats(conn)
    print(f"Ofertas={stats['offers']} activas={stats['active']} "
          f"verificadas={stats['network_verified']} evidencias={stats['evidence']}")
    conn.close()

    f = HttpFetcher(timeout=12, retries=0)
    for s in src_mod.enabled_sources():
        res = f.fetch(s.url)
        state = "OK" if res.ok else ("304" if res.not_modified else f"FALLA {res.error}")
        print(f"  {s.id:<32} {res.status:<4} {len(res.text):>7} bytes  {state}")
        ok = ok and (res.ok or res.not_modified)
    return 0 if ok else 1


def cmd_verify(args) -> int:
    """Re-verifica por red: vuelve a bajar la URL de evidencia y busca el snippet."""
    import re as _re
    from .htmltext import to_text

    def norm(s: str) -> str:
        return _re.sub(r"\s+", "", s or "")

    path, conn = _open(args.db)
    if args.all:
        ids = [r["offer_id"] for r in conn.execute(
            "SELECT offer_id FROM offer WHERE status NOT IN ('EXPIRADA','RETIRADA')")]
    elif args.id:
        ids = [args.id]
    else:
        print("Indica un id o --all")
        return 2

    f = HttpFetcher(timeout=20, retries=1)
    cache: dict[str, object] = {}
    checked = confirmed = unreachable = 0
    for oid in ids:
        o = store.get_offer(conn, oid)
        if not o:
            continue
        url = o["last_evidence_url"] or o["official_url"]
        if url not in cache:
            cache[url] = f.fetch(url)
        res = cache[url]
        checked += 1
        snippet = (o["evidence"][0]["snippet"] if o["evidence"] else "") or ""
        core = norm(snippet.replace("...", ""))[:100]

        if not res.ok:
            unreachable += 1
            note = f"no se pudo re-verificar: {res.error}"
            level = o["verification_level"]
        else:
            hay = norm(res.text) + norm(to_text(res.text))
            if core and core in hay:
                level = "NETWORK_VERIFIED"
                confirmed += 1
                note = "re-verificado: fragmento presente en la pagina"
            else:
                level = "CONTENT_VERIFIED"
                note = "pagina accesible, fragmento no hallado literalmente"
        conn.execute(
            "UPDATE offer SET verification_level=?, updated_utc=? WHERE offer_id=?",
            (level, store.utcnow(), oid))
        conn.execute(
            "INSERT INTO offer_event (offer_id, run_id, event_type, changed_fields, at_utc) "
            "VALUES (?,?,?,?,?)", (oid, None, "VISTA", f"verify:{level}", store.utcnow()))
        if args.verbose:
            print(f"#{oid} {level} - {note}")
    conn.commit()
    conn.close()
    print(f"Re-verificadas {checked}; fragmento confirmado en {confirmed}; "
          f"inaccesibles {unreachable}.")
    return 0


def cmd_ai_status(args) -> int:
    from .ai_settings import AISettingsStore
    store = AISettingsStore()
    cfg = store.public_config()
    print(f"Modo: {'DETERMINISTA (sin IA utilizable)' if cfg['deterministic_mode'] else 'IA configurada'}")
    chain = store.routing_chain()
    if chain:
        print("Cadena de intento (principal + fallbacks):")
        for i, t in enumerate(chain, 1):
            prov = cfg["providers"][t["provider"]]
            marca = " [autoriza costo no verificado]" if prov["allow_unverified_cost"] else ""
            print(f"  {i}. {t['provider']}/{t['model']}{marca}")
    else:
        print("Cadena de intento: (vacia)")
    usage = store.public_usage()
    for pid, u in usage.items():
        prov = cfg["providers"][pid]
        if prov["has_key"] or pid == "demo_local" or u["requests"]:
            print(f"  {pid}: hoy {u['requests']} req / {u['tokens']} tok"
                  f" | key={'si' if prov['has_key'] else 'no'} enabled={prov['enabled']}"
                  + (f" | ultimo error: {u['last_error']}" if u.get("last_error") else ""))
    return 0


def _candidate_from_offer(o: dict):
    """Reconstruye un Candidate desde la oferta persistida + su evidencia.

    La evidencia original (snippet, URL) se conserva y es lo que se pasa a la IA.
    """
    from .models import Candidate
    snippet = o["evidence"][0]["snippet"] if o.get("evidence") else (o.get("evidence_snippet") or "")
    ev_url = o["evidence"][0]["url"] if o.get("evidence") else (o.get("last_evidence_url") or o["official_url"])
    return Candidate(
        source_id=o.get("source_id") or "persistida",
        provider_key=o["provider_key"],
        product=o["product"],
        title=o["title"],
        offer_type=o["offer_type"],
        benefit=o["benefit"],
        official_url=o["official_url"],
        evidence_url=ev_url,
        evidence_snippet=snippet,
        extraction_rule=o.get("extraction_rule") or "persistida",
        price_baseline=o["price_baseline"],
        price_offer=o["price_offer"],
        price_unit=o["price_unit"],
    )


def cmd_ai_classify(args) -> int:
    from .ai_classify import classify_candidate
    from .ai_settings import AISettingsStore

    path, conn = _open(args.db)
    store = AISettingsStore()

    if args.offer:
        ids = [args.offer]
    else:
        rows = conn.execute(
            "SELECT offer_id FROM offer WHERE status NOT IN ('EXPIRADA','RETIRADA') "
            "ORDER BY offer_id DESC LIMIT ?", (args.limit,)).fetchall()
        ids = [r["offer_id"] for r in rows]
    if not ids:
        print("Sin ofertas para clasificar.")
        conn.close()
        return 0

    ok_n = blocked_n = 0
    for oid in ids:
        o = store.get_offer(conn, oid)
        if not o:
            continue
        cand = _candidate_from_offer(o)
        outcome = classify_candidate(cand, store=store)
        if outcome.ok:
            a = outcome.assessment
            store.add_ai_assessment(
                conn, oid, None, outcome.provider, outcome.model,
                a.is_offer, a.benefit_type, a.conditions, a.restrictions,
                a.argentina_eligibility, a.confidence, a.justification,
                outcome.cost_status, raw_response=a.raw_response)
            ok_n += 1
            print(f"#{oid} IA [{outcome.provider}/{outcome.model}] "
                  f"oferta={a.is_offer} tipo={a.benefit_type} "
                  f"AR={a.argentina_eligibility} conf={a.confidence}")
        else:
            store.add_ai_assessment(
                conn, oid, None, outcome.provider or "-", outcome.model or "-",
                None, None, None, None, None, None, None, outcome.cost_status or "",
                error=f"{outcome.blocked}: {outcome.detail}")
            blocked_n += 1
            print(f"#{oid} IA bloqueada: {outcome.blocked} - {outcome.detail[:160]}")
    conn.close()
    print(f"Clasificadas por IA: {ok_n}; bloqueadas: {blocked_n}.")
    print("Recordatorio: la interpretacion IA NO es verificacion oficial; "
          "la evidencia original quedo intacta.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ach", description="AI Credits Hunter v4")
    p.add_argument("--version", action="version", version=f"ach {__version__}")
    p.add_argument("--db", help="ruta de la base de ensayo (default data/promotions_v4.sqlite3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea/migra la base y registra fuentes").set_defaults(func=cmd_init)

    r = sub.add_parser("run", help="ejecuta una corrida real")
    r.add_argument("--sources", help="ids separados por coma")
    r.add_argument("--offline", help="directorio de fixtures (modo prueba, no es una corrida real)")
    r.add_argument("--limit", type=int, help="maximo de candidatos por fuente")
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--ai", action="store_true",
                   help="clasificacion semantica IA de candidatos (requiere "
                        "Configuracion -> IA; sin configurar, queda bloqueada y "
                        "la corrida continua en modo determinista)")
    r.set_defaults(func=cmd_run)

    l = sub.add_parser("list", help="lista ofertas")
    l.add_argument("--q")
    l.add_argument("--band")
    l.add_argument("--ar")
    l.add_argument("--type")
    l.add_argument("--level")
    l.add_argument("--status")
    l.add_argument("--min-discount", type=float)
    l.add_argument("--order", default="discount",
                   choices=["discount", "recent", "provider", "price"])
    l.add_argument("--limit", type=int, default=50)
    l.add_argument("--all", action="store_true", help="incluye expiradas/retiradas")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="detalle JSON de una oferta")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_show)

    sub.add_parser("sources", help="estado de fuentes").set_defaults(func=cmd_sources)

    dsc = sub.add_parser("discover",
                         help="descubre enlaces candidatos en feeds oficiales (no verificados)")
    dsc.add_argument("--list", action="store_true",
                     help="muestra los candidatos guardados sin consultar la red")
    dsc.add_argument("--verify", action="store_true",
                     help="visita los candidatos pendientes y verifica su contenido")
    dsc.add_argument("--limit", type=int, default=10,
                     help="tope de candidatos a verificar por ejecucion (por defecto 10)")
    dsc.add_argument("--out", help="JSON de candidatos (por defecto data/discovered_candidates.json)")
    dsc.add_argument("--max-items", type=int, default=100,
                     help="tope de items por feed (por defecto 100)")
    dsc.set_defaults(func=cmd_discover)

    sv = sub.add_parser("serve", help="interfaz web local")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)

    e = sub.add_parser("export", help="exporta JSON y CSV")
    e.add_argument("--out")
    e.set_defaults(func=cmd_export)

    d = sub.add_parser("doctor", help="chequeos de integridad y conectividad")
    d.set_defaults(func=cmd_doctor)

    v = sub.add_parser("verify", help="re-verifica ofertas por red")
    v.add_argument("id", nargs="?", type=int)
    v.add_argument("--all", action="store_true")
    v.add_argument("--verbose", action="store_true")
    v.set_defaults(func=cmd_verify)

    ai = sub.add_parser("ai", help="clasificacion semantica IA (Configuracion -> IA)")
    ai_sub = ai.add_subparsers(dest="ai_cmd", required=True)
    ai_status = ai_sub.add_parser("status", help="estado de la configuracion IA")
    ai_status.set_defaults(func=cmd_ai_status)
    ai_cls = ai_sub.add_parser("classify", help="clasifica ofertas persistidas con la IA")
    ai_cls.add_argument("--offer", type=int, help="id de oferta puntual")
    ai_cls.add_argument("--limit", type=int, default=10,
                        help="cantidad de ofertas recientes a clasificar (default 10)")
    ai_cls.set_defaults(func=cmd_ai_classify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
