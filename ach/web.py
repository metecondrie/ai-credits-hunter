"""Interfaz web local (solo stdlib, solo 127.0.0.1).

Rutas:
  /                    listado con filtros
  /oferta/<id>         detalle + evidencia
  /fuentes             estado de cada fuente
  /corridas            historial de corridas
  /api/ofertas         JSON
  /api/estadisticas    JSON
"""

from __future__ import annotations

import html
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, store, web_ai

CSS = """
:root{--bg:#0e1116;--panel:#151a22;--line:#232b36;--txt:#e6edf3;--dim:#8b98a9;
--accent:#2dd4bf;--warn:#f59e0b;--bad:#ef4444;--good:#22c55e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 -apple-system,
"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{position:sticky;top:0;background:rgba(14,17,22,.95);border-bottom:1px solid var(--line);
padding:14px 22px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;z-index:5}
header h1{font-size:16px;margin:0;letter-spacing:.4px}
header a{color:var(--dim);text-decoration:none;font-size:13px}
header a:hover{color:var(--accent)}
main{max-width:1180px;margin:0 auto;padding:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .n{font-size:24px;font-weight:600}
.card .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.6px}
form.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
input,select,button{background:var(--panel);color:var(--txt);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;font-size:14px}
button{cursor:pointer}button:hover{border-color:var(--accent);color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:var(--dim);font-weight:500;font-size:12px;text-transform:uppercase;
letter-spacing:.5px;border-bottom:1px solid var(--line);padding:8px 10px}
td{border-bottom:1px solid var(--line);padding:10px;vertical-align:top}
tr:hover td{background:#121821}
a.o{color:var(--txt);text-decoration:none;font-weight:600}
a.o:hover{color:var(--accent)}
.muted{color:var(--dim);font-size:12.5px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;
border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.b90{color:#fecaca;border-color:#7f1d1d;background:#2a1215}
.b70{color:#fed7aa;border-color:#7c2d12;background:#2a1a10}
.b50{color:#fde68a;border-color:#713f12;background:#261f0c}
.b30{color:#bfdbfe;border-color:#1e3a8a;background:#101a2b}
.bv{color:#bbf7d0;border-color:#14532d;background:#0f2016}
.bu{color:var(--dim)}
.detail{display:grid;grid-template-columns:2fr 1fr;gap:18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px}
pre{white-space:pre-wrap;word-break:break-word;background:#0b0f14;border:1px solid var(--line);
border-radius:8px;padding:12px;font-size:12.5px;color:#c9d4e0}
h2{font-size:18px;margin:0 0 12px}
h3{font-size:14px;margin:18px 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px}
.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 12px;font-size:14px}
.kv div:nth-child(odd){color:var(--dim)}
footer{color:var(--dim);font-size:12px;padding:26px 0;text-align:center}
@media(max-width:760px){.detail{grid-template-columns:1fr}}
"""

BANDS = {
    "DESCUENTO_90_PLUS": "b90", "GRATIS_100": "b90",
    "DESCUENTO_70_89": "b70", "DESCUENTO_50_69": "b50",
    "DESCUENTO_30_49": "b30", "SIN_BASE_VERIFICADA": "bu",
    "SIN_DESCUENTO": "bu",
}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def page(title: str, body: str) -> bytes:
    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>AI CREDITS HUNTER <span style="color:var(--accent)">v4</span></h1>
<a href="/">Ofertas</a><a href="/fuentes">Fuentes</a><a href="/corridas">Corridas</a>
<a href="/configuracion/ia">Configuraci&oacute;n &rarr; IA</a>
<a href="/api/ofertas">API</a></header>
<main>{body}</main>
<footer>Datos obtenidos por HTTP de fuentes oficiales. Verificacion: NETWORK_VERIFIED exige
coincidencia literal en la pagina. Sin APIs pagas.</footer></body></html>"""
    return doc.encode("utf-8")


def _badge(o: dict) -> str:
    cls = BANDS.get(o["discount_band"], "bu")
    txt = "sin base" if o["discount_pct"] is None else f"{o['discount_pct']:.0f}%"
    return f'<span class="badge {cls}">{esc(txt)}</span>'


def _price(o: dict) -> str:
    if o["price_offer"] is None:
        return '<span class="muted">N/D</span>'
    unit = f" {o['price_unit']}" if o["price_unit"] else ""
    base = "" if o["price_baseline"] is None else f'<span class="muted">de {o["price_baseline"]:g}</span> '
    return f'{base}<b>{o["price_offer"]:g}</b>{esc(unit)}'


class Handler(BaseHTTPRequestHandler):
    db_path: Path = config.DEFAULT_DB

    def log_message(self, fmt, *args):  # silencio en consola
        pass

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 256 * 1024:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}

    def _api_mutation(self, fn) -> None:
        """PUT/POST/DELETE de /api/ai/* (panel de configuracion IA)."""
        route = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        try:
            if fn is web_ai.api_put:
                status, payload = fn(route, self._read_json_body())
            elif fn is web_ai.api_post:
                status, payload = fn(route, self._read_json_body())
            else:
                status, payload = fn(route)
        except Exception as exc:
            status, payload = 500, {"ok": False, "error": f"Error interno: {type(exc).__name__}"}
        self._send(json.dumps(payload, ensure_ascii=False).encode(),
                   status=status, ctype="application/json; charset=utf-8")

    def do_PUT(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/api/ai/"):
            return self._api_mutation(web_ai.api_put)
        self._send(b'{"ok":false,"error":"Ruta no encontrada."}', status=404,
                   ctype="application/json; charset=utf-8")

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/api/ai/"):
            return self._api_mutation(web_ai.api_post)
        self._send(b'{"ok":false,"error":"Ruta no encontrada."}', status=404,
                   ctype="application/json; charset=utf-8")

    def do_DELETE(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/api/ai/"):
            return self._api_mutation(web_ai.api_delete)
        self._send(b'{"ok":false,"error":"Ruta no encontrada."}', status=404,
                   ctype="application/json; charset=utf-8")

    def _conn(self):
        return store.connect(self.db_path, readonly=True)

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/":
                return self._send(page("Ofertas - AI Credits Hunter", self._index(qs)))
            if route.startswith("/oferta/"):
                return self._offer(route.split("/")[-1])
            if route == "/fuentes":
                return self._send(page("Fuentes", self._sources()))
            if route == "/corridas":
                return self._send(page("Corridas", self._runs()))
            if route == "/configuracion/ia":
                return self._send(page("Configuracion -> Inteligencia artificial",
                                       web_ai.panel_html()))
            if route.startswith("/api/ai/"):
                status, payload = web_ai.api_get(route)
                return self._send(json.dumps(payload, ensure_ascii=False).encode(),
                                  status=status, ctype="application/json; charset=utf-8")
            if route == "/api/ofertas":
                return self._api_offers(qs)
            if route == "/api/estadisticas":
                conn = self._conn()
                try:
                    data = store.stats(conn)
                finally:
                    conn.close()
                return self._send(json.dumps(data, ensure_ascii=False).encode(),
                                  ctype="application/json; charset=utf-8")
            return self._send(page("404", "<h2>No encontrado</h2>"), 404)
        except Exception as exc:
            return self._send(page("Error", f"<h2>Error</h2><pre>{esc(exc)}</pre>"), 500)

    # ------------------------------------------------------------------
    def _index(self, qs: dict) -> str:
        def arg(k, d=""):
            return qs.get(k, [d])[0]

        q = arg("q")
        band = arg("band")
        ar = arg("ar")
        level = arg("level")
        order = arg("order", "discount")

        conn = self._conn()
        try:
            stats = store.stats(conn)
            rows = store.list_offers(conn, q=q or None, band=band or None, ar=ar or None,
                                     level=level or None, order=order, limit=300)
            ai_map = store.latest_ai_by_offer(conn)
        finally:
            conn.close()

        def opt(value, label, current):
            sel = " selected" if value == current else ""
            return f'<option value="{esc(value)}"{sel}>{esc(label)}</option>'

        cards = f"""
<div class="cards">
  <div class="card"><div class="n">{stats['active']}</div><div class="l">Ofertas activas</div></div>
  <div class="card"><div class="n">{stats['network_verified']}</div><div class="l">Verificadas por red</div></div>
  <div class="card"><div class="n">{stats['evidence']}</div><div class="l">Evidencias</div></div>
  <div class="card"><div class="n">{stats['sources']}</div><div class="l">Fuentes</div></div>
  <div class="card"><div class="n">{stats['runs']}</div><div class="l">Corridas</div></div>
</div>"""

        filters = f"""
<form class="filters" method="get" action="/">
  <input name="q" placeholder="Buscar producto o proveedor" value="{esc(q)}" size="28">
  <select name="band">{opt('', 'Todas las bandas', band)}
    {opt('GRATIS_100', '100% gratis', band)}
    {opt('DESCUENTO_90_PLUS', '90%+', band)}
    {opt('DESCUENTO_70_89', '70-89%', band)}
    {opt('DESCUENTO_50_69', '50-69%', band)}
    {opt('DESCUENTO_30_49', '30-49%', band)}
    {opt('SIN_BASE_VERIFICADA', 'Sin base verificada', band)}
  </select>
  <select name="ar">{opt('', 'Argentina: todas', ar)}
    {opt('DISPONIBLE_POR_DECLARACION', 'Disponible (declarado)', ar)}
    {opt('ARGENTINA_NO_CONFIRMADA', 'Sin confirmar', ar)}
    {opt('REQUIERE_REVISION_GEO', 'Revisar geografia', ar)}
  </select>
  <select name="level">{opt('', 'Verificacion: todas', level)}
    {opt('NETWORK_VERIFIED', 'NETWORK_VERIFIED', level)}
    {opt('CONTENT_VERIFIED', 'CONTENT_VERIFIED', level)}
    {opt('UNVERIFIED', 'UNVERIFIED', level)}
  </select>
  <select name="order">{opt('discount', 'Mayor descuento', order)}
    {opt('recent', 'Mas recientes', order)}{opt('provider', 'Proveedor', order)}
    {opt('price', 'Menor precio', order)}
  </select>
  <button type="submit">Filtrar</button>
</form>"""

        if not rows:
            table = ('<div class="panel"><h2>Sin ofertas para mostrar</h2>'
                     '<p class="muted">Una busqueda sin coincidencias devuelve cero resultados: '
                     'no se generan ofertas de relleno. Ejecuta una corrida con '
                     '<code>python -m ach run</code>.</p></div>')
        else:
            body = []
            for o in rows:
                ai = ai_map.get(o["offer_id"])
                if ai and not ai["error"]:
                    verdict = "si" if ai["is_offer"] else "no"
                    ai_badge = (f'<span class="badge" style="border-color:var(--warn);color:var(--warn)" '
                                f'title="Interpretacion IA ({esc(ai["provider"])}/{esc(ai["model"])}) — NO es verificacion oficial">'
                                f'IA: {verdict} / {esc(ai["benefit_type"])}</span>')
                elif ai and ai["error"]:
                    ai_badge = '<span class="badge bu" title="IA bloqueada o sin configurar">IA: —</span>'
                else:
                    ai_badge = '<span class="muted">—</span>'
                body.append(f"""<tr>
<td><a class="o" href="/oferta/{o['offer_id']}">{esc(o['product'])}</a>
<div class="muted">{esc(o['title'])[:120]}</div></td>
<td>{esc(o['provider_name'])}<div class="muted">{esc(o['offer_type'])}</div></td>
<td>{_price(o)}</td>
<td>{_badge(o)}</td>
<td><span class="badge">{esc(o['argentina_status'])}</span></td>
<td><span class="badge {'bv' if o['verification_level']=='NETWORK_VERIFIED' else 'bu'}">
{esc(o['verification_level'])}</span></td>
<td>{ai_badge}</td>
<td class="muted">{esc(o['last_seen_utc'][:10])}</td></tr>""")
            table = f"""<table><thead><tr><th>Producto</th><th>Proveedor</th><th>Precio</th>
<th>Desc.</th><th>Argentina</th><th>Verificacion</th><th>IA*</th><th>Visto</th></tr></thead>
<tbody>{''.join(body)}</tbody></table>
<p class="muted">{len(rows)} oferta(s) mostradas. *IA = interpretacion de un modelo
(configurable en Configuraci&oacute;n &rarr; IA); NO es verificacion oficial.</p>"""

        return cards + filters + table

    # ------------------------------------------------------------------
    def _offer(self, raw_id: str) -> None:
        try:
            offer_id = int(raw_id)
        except ValueError:
            return self._send(page("404", "<h2>Oferta invalida</h2>"), 404)
        conn = self._conn()
        try:
            o = store.get_offer(conn, offer_id)
            ai_rows = store.get_ai_assessments(conn, offer_id) if o else []
        finally:
            conn.close()
        if not o:
            return self._send(page("404", "<h2>Oferta no encontrada</h2>"), 404)

        ev = "".join(
            f"""<div class="panel" style="margin-bottom:12px">
<h3>Evidencia #{e['evidence_id']} - HTTP {e['http_status']} - {esc(e['observed_at_utc'])}</h3>
<div class="muted">{esc(e['url'])}</div>
<pre>{esc(e['snippet'])}</pre>
<div class="muted">sha256: {esc(e['content_sha256'] or 'N/D')}<br>
regla: {esc(e['extraction_rule'])}<br>nivel: {esc(e['verification_level'])}</div></div>"""
            for e in o["evidence"])

        # Interpretaciones IA: tabla separada, NUNCA verificacion oficial.
        ai_html = ""
        if ai_rows:
            cards = []
            for a in ai_rows:
                if a["error"]:
                    cards.append(f"""<div class="panel" style="margin-bottom:10px;border-color:var(--bad)">
<b style="color:var(--bad)">IA bloqueada</b> <span class="muted">{esc(a['created_at_utc'])}</span>
<div class="muted">{esc(a['error'])}</div></div>""")
                    continue
                veredicto = ("<b style='color:var(--good)'>Es oferta</b>" if a["is_offer"]
                             else "<b style='color:var(--bad)'>No es oferta</b>")
                cards.append(f"""<div class="panel" style="margin-bottom:10px;border-color:var(--warn)">
<div>{veredicto} <span class="badge">{esc(a['benefit_type'])}</span>
<span class="badge">{esc(a['argentina_eligibility'])}</span>
<span class="badge">confianza: {esc(a['confidence'])}</span></div>
<div class="kv" style="margin-top:8px">
  <div>Condiciones</div><div>{esc(a['conditions'])}</div>
  <div>Restricciones</div><div>{esc(a['restrictions'])}</div>
  <div>Justificacion</div><div>{esc(a['justification'])}</div>
  <div>Modelo</div><div class="muted">{esc(a['provider'])} / {esc(a['model'])}
    (costo: {esc(a['cost_status'])})</div>
  <div>Fecha</div><div class="muted">{esc(a['created_at_utc'])}</div>
</div></div>""")
            ai_html = f"""<div style="grid-column:1/-1">
<h2>Interpretacion de IA ({len(ai_rows)})</h2>
<p class="muted" style="border:1px solid var(--warn);border-radius:8px;padding:8px 12px">
<b style="color:var(--warn)">Esto NO es una verificacion oficial.</b>
Es la interpretacion de un modelo de IA sobre la descripcion, el fragmento de evidencia
y la URL. La evidencia original (arriba) permanece intacta y es la unica fuente de verdad;
la verificacion oficial exige coincidencia literal en la pagina (nivel NETWORK_VERIFIED).</p>
{''.join(cards)}</div>"""

        body = f"""
<p><a href="/" class="muted">&larr; volver</a></p>
<div class="detail">
<div class="panel">
  <h2>{esc(o['product'])}</h2>
  <p class="muted">{esc(o['provider_name'])} - {esc(o['offer_type'])}</p>
  <div class="kv">
    <div>Titulo</div><div>{esc(o['title'])}</div>
    <div>Beneficio</div><div>{esc(o['benefit'])}</div>
    <div>Precio normal</div><div>{esc(o['price_baseline'])} {esc(o['price_unit'] or '')}</div>
    <div>Precio oferta</div><div>{esc(o['price_offer'])} {esc(o['price_unit'] or '')}</div>
    <div>Descuento</div><div>{_badge(o)} {esc(o['discount_band'])}</div>
    <div>Argentina</div><div>{esc(o['argentina_status'])}</div>
    <div>Tarjeta</div><div>{esc(o['card_required'])}</div>
    <div>Auto-renovacion</div><div>{esc(o['auto_renewal'])}</div>
    <div>Elegibilidad</div><div>{esc(o['eligibility'])}</div>
    <div>Horario</div><div>{esc(o['time_window_art'] or 'N/D')}</div>
    <div>Oficial</div><div><a href="{esc(o['official_url'])}" target="_blank" rel="noopener">
{esc(o['official_url'])}</a></div>
    <div>Terminos</div><div>{esc(o['terms_url'] or 'N/D')}</div>
    <div>Verificacion</div><div>{esc(o['verification_level'])} ({esc(o['confidence'])})</div>
    <div>Estado</div><div>{esc(o['status'])}</div>
    <div>Visto</div><div>{esc(o['first_seen_utc'])} -> {esc(o['last_seen_utc'])}</div>
    <div>Notas</div><div>{esc(o.get('notes'))}</div>
  </div>
</div>
<div><h2>Evidencias ({len(o['evidence'])})</h2>{ev or '<p class="muted">Sin evidencia.</p>'}</div>
{ai_html}
</div>"""
        self._send(page(o["product"], body))

    # ------------------------------------------------------------------
    def _sources(self) -> str:
        conn = self._conn()
        try:
            rows = store.list_sources(conn)
        finally:
            conn.close()
        body = "".join(f"""<tr><td><b>{esc(r['source_id'])}</b>
<div class="muted">{esc(r['url'])}</div></td>
<td>{esc(r['kind'])} / {esc(r['extractor'])}</td>
<td>{esc(r['last_http_status'] or '-')}</td>
<td>{esc(r['last_candidates'])}</td>
<td class="muted">{esc(r['last_run_utc'] or 'nunca')}</td>
<td class="muted">{esc(r['last_error'] or '-')}</td></tr>""" for r in rows)
        return f"""<h2>Fuentes registradas</h2>
<table><thead><tr><th>Fuente</th><th>Tipo</th><th>HTTP</th><th>Candidatos</th>
<th>Ultima corrida</th><th>Error</th></tr></thead><tbody>{body}</tbody></table>"""

    def _runs(self) -> str:
        conn = self._conn()
        try:
            rows = store.list_runs(conn)
        finally:
            conn.close()
        body = "".join(f"""<tr><td>#{r['run_id']}</td><td>{esc(r['started_utc'])}</td>
<td>{esc(r['mode'])}</td><td>{r['sources_ok']}/{r['sources_total']}</td>
<td>{r['candidates']}</td><td>{r['offers_new']}</td><td>{r['offers_changed']}</td>
<td>{r['errors']}</td><td class="muted">{esc(r['notes'] or '')}</td></tr>""" for r in rows)
        return f"""<h2>Corridas</h2>
<table><thead><tr><th>ID</th><th>Inicio</th><th>Modo</th><th>Fuentes ok</th><th>Candidatos</th>
<th>Nuevas</th><th>Cambiadas</th><th>Errores</th><th>Notas</th></tr></thead>
<tbody>{body}</tbody></table>"""

    def _api_offers(self, qs: dict) -> None:
        def arg(k, d=""):
            return qs.get(k, [d])[0]

        conn = self._conn()
        try:
            rows = store.list_offers(
                conn, q=arg("q") or None, band=arg("band") or None,
                ar=arg("ar") or None, level=arg("level") or None,
                order=arg("order", "discount"),
                limit=int(arg("limit", "200")),
            )
        finally:
            conn.close()
        payload = {"count": len(rows), "offers": rows}
        self._send(json.dumps(payload, ensure_ascii=False, indent=2).encode(),
                   ctype="application/json; charset=utf-8")


def serve(db_path: Path | None = None, port: int = 8765, host: str = "127.0.0.1") -> None:
    path = config.resolve_db(db_path)
    if not Path(path).exists():
        raise SystemExit(f"No existe la base {path}. Ejecuta primero: python -m ach init")
    Handler.db_path = Path(path)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"AI Credits Hunter v4 en http://{host}:{port}  (base: {path})")
    print("Ctrl+C para detener.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        httpd.server_close()
