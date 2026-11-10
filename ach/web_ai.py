"""Panel «Configuracion -> Inteligencia artificial» integrado en la web v4.

Se sirve desde el MISMO servidor de ach/web.py (no es otra aplicacion).
Las claves se guardan SOLO en Windows Credential Manager (keyring); la API
devuelve exclusivamente la clave enmascarada.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .ai_providers import PROVIDER_LABELS, ProviderError, get_provider
from .ai_settings import AISettingsError, AISettingsStore

_STORE: AISettingsStore | None = None


def get_store() -> AISettingsStore:
    global _STORE
    if _STORE is None:
        _STORE = AISettingsStore()
    return _STORE


def reset_store_for_tests(store: AISettingsStore) -> None:
    """Inyeccion para tests."""
    global _STORE
    _STORE = store


# --------------------------------------------------------------------------
# API (json -> (status, payload))
# --------------------------------------------------------------------------
def api_get(path: str) -> tuple[int, Dict[str, Any]]:
    store = get_store()
    if path == "/api/ai/config":
        return 200, {"ok": True, "config": store.public_config()}
    if path == "/api/ai/usage":
        return 200, {"ok": True, "usage": store.public_usage()}
    if path.endswith("/models") and path.startswith("/api/ai/providers/"):
        pid = path.split("/")[4]
        try:
            prov = get_provider(pid)
        except ProviderError as exc:
            return 404, {"ok": False, "error": str(exc)}
        key = store.keys.get_key(pid) or ""
        if prov.needs_key and not key:
            return 400, {"ok": False, "error": f"No hay API key guardada para {pid}."}
        base_url = store.provider_settings(pid).get("base_url", "")
        try:
            models = prov.list_models(key, base_url=base_url)
        except ProviderError as exc:
            return exc.status or 502, {"ok": False, "error": str(exc),
                                       "quota_exhausted": exc.quota_exhausted}
        return 200, {"ok": True, "provider": pid, "count": len(models),
                     "models": models, "free_tier_info": prov.free_tier_info}
    return 404, {"ok": False, "error": "Ruta no encontrada."}


def api_put(path: str, body: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    store = get_store()
    try:
        if path.endswith("/key") and path.startswith("/api/ai/providers/"):
            pid = path.split("/")[4]
            store.set_api_key(pid, str(body.get("key", "")))
            return 200, {"ok": True, "provider": pid}
        if path.endswith("/settings") and path.startswith("/api/ai/providers/"):
            pid = path.split("/")[4]
            prov = store.update_provider_settings(pid, body)
            return 200, {"ok": True, "provider": pid, "settings": prov}
        if path == "/api/ai/routing":
            routing = store.update_routing(primary=body.get("primary"),
                                           fallbacks=body.get("fallbacks"))
            return 200, {"ok": True, "routing": routing}
        return 404, {"ok": False, "error": "Ruta no encontrada."}
    except AISettingsError as exc:
        return 400, {"ok": False, "error": str(exc)}


def api_delete(path: str) -> tuple[int, Dict[str, Any]]:
    store = get_store()
    if path.endswith("/key") and path.startswith("/api/ai/providers/"):
        pid = path.split("/")[4]
        try:
            store.delete_api_key(pid)
        except AISettingsError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "provider": pid}
    return 404, {"ok": False, "error": "Ruta no encontrada."}


def api_post(path: str, body: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    store = get_store()
    if path == "/api/ai/test":
        pid = str(body.get("provider", "")).strip()
        model = str(body.get("model", "")).strip()
        try:
            prov = get_provider(pid)
        except ProviderError as exc:
            return 400, {"ok": False, "error": str(exc)}
        allowed, reason = store.check_limits(pid)
        if not allowed:
            return 429, {"ok": False, "error": reason, "quota_exhausted": True}
        key = store.keys.get_key(pid) or ""
        if prov.needs_key and not key:
            return 400, {"ok": False, "error": f"No hay API key guardada para {pid}."}
        base_url = store.provider_settings(pid).get("base_url", "")
        try:
            result = prov.test_connectivity(key, model=model, base_url=base_url)
        except ProviderError as exc:
            store.record_usage(pid, error=str(exc), quota_exhausted=exc.quota_exhausted)
            return exc.status or 502, {"ok": False, "error": str(exc),
                                       "quota_exhausted": exc.quota_exhausted}
        store.record_usage(pid, error=result.get("detail"))
        return 200, result
    return 404, {"ok": False, "error": "Ruta no encontrada."}


# --------------------------------------------------------------------------
# Pagina HTML del panel (mismo estilo que la web v4)
# --------------------------------------------------------------------------
PANEL_BODY = """
<div id="detBanner" class="panel" style="border-color:var(--warn);display:none">
<b style="color:var(--warn)">Modo determinista activo:</b>
<span class="muted">no hay ninguna IA utilizable configurada. El cazador sigue funcionando
con sus extractores y reglas tradicionales (HTTP/RSS/regex/SQLite), sin LLM.</span>
</div>

<div class="panel" style="margin-top:14px">
<h2>Modelo principal y orden de fallback</h2>
<p class="muted">Identificador exacto del modelo, o tocá un modelo listado desde la API
del proveedor para usarlo acá. La cadena se intenta en orden al clasificar ofertas.</p>
<div style="display:grid;grid-template-columns:1fr 2fr;gap:10px">
  <div><label class="muted">Proveedor principal</label><select id="primaryProvider"></select></div>
  <div><label class="muted">Modelo principal (ID exacto)</label>
  <input id="primaryModel" placeholder="ej.: meta-llama/llama-3.3-70b-instruct:free"></div>
  <div><label class="muted">Fallback — proveedor</label><select id="fbProvider"></select></div>
  <div style="display:flex;gap:8px">
    <input id="fbModel" placeholder="modelo fallback" style="flex:1">
    <button onclick="addFallback()">＋ Agregar</button>
  </div>
</div>
<table id="fbTable" style="margin-top:10px"><tbody></tbody></table>
<div style="margin-top:10px"><button onclick="saveRouting()">Guardar modelo y fallback</button>
<span id="routingStatus" class="muted" style="margin-left:10px"></span></div>
</div>

<div class="panel" style="margin-top:14px;border-color:var(--warn)">
<b style="color:var(--warn)">Regla de costo (innegociable):</b>
<span class="muted">ninguna llamada se ejecuta si el costo no es verificable como gratuito,
salvo que autorices explícitamente el casillero de cada proveedor. NO se asume gratuidad
por ser Gemini Flash o Groq. Los modelos OpenRouter <code>:free</code> son los únicos con
gratuidad verificada automáticamente. La prueba de conexión solo lista modelos (sin cargo).</span>
</div>

<div id="providersGrid"></div>

<script>
const PROVIDER_META = %PROVIDER_META%;
const PROVIDER_IDS = Object.keys(PROVIDER_META);
let CONFIG = null, USAGE = null;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(method, path, body){
  const res = await fetch(path, {method,
    headers: body ? {"Content-Type":"application/json"} : {},
    body: body ? JSON.stringify(body) : undefined});
  const data = await res.json().catch(() => ({ok:false, error:"Respuesta no JSON"}));
  return {status: res.status, ...data};
}

async function refresh(){
  const [cfg, usg] = await Promise.all([api("GET","/api/ai/config"), api("GET","/api/ai/usage")]);
  CONFIG = cfg.config; USAGE = usg.usage; renderAll();
}
function renderAll(){
  $("detBanner").style.display = CONFIG.deterministic_mode ? "block" : "none";
  renderRouting(); renderProviders();
}
function fillProviderSelect(sel, withEmpty){
  sel.innerHTML = "";
  if (withEmpty){ const o=document.createElement("option"); o.value=""; o.textContent="(sin definir)"; sel.appendChild(o); }
  for (const pid of PROVIDER_IDS){
    if (pid === "demo_local") continue;  // el demo se habilita solo en tarjeta propia
    const o=document.createElement("option"); o.value=pid; o.textContent=PROVIDER_META[pid].name; sel.appendChild(o);
  }
}
function renderRouting(){
  fillProviderSelect($("primaryProvider"), true);
  fillProviderSelect($("fbProvider"), false);
  const r = CONFIG.routing;
  $("primaryProvider").value = r.primary.provider || "";
  $("primaryModel").value = r.primary.model || "";
  const tbody = $("fbTable").querySelector("tbody"); tbody.innerHTML = "";
  r.fallbacks.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted">${i+1}</td><td>${esc(PROVIDER_META[f.provider]?.name||f.provider)}</td>
      <td><code>${esc(f.model)}</code></td>
      <td><button onclick="moveFallback(${i},-1)" ${i===0?"disabled":""}>↑</button>
      <button onclick="moveFallback(${i},1)" ${i===r.fallbacks.length-1?"disabled":""}>↓</button>
      <button onclick="removeFallback(${i})">✕</button></td>`;
    tbody.appendChild(tr);
  });
}
function renderProviders(){
  const grid = $("providersGrid"); grid.innerHTML = "";
  for (const pid of PROVIDER_IDS){
    const p = CONFIG.providers[pid], u = USAGE[pid] || {};
    const card = document.createElement("div");
    card.className = "panel"; card.style.marginTop = "14px";
    const keyInput = pid === "demo_local" ? "" : `
      <label class="muted">API key (se guarda SOLO en Windows Credential Manager; nunca en SQLite, Git, logs ni reportes)</label>
      <div style="display:flex;gap:8px">
        <input type="password" id="key-${pid}" style="flex:1"
          placeholder="${p.has_key ? esc(p.masked_key) + '  (guardada — escribí para reemplazar)' : 'Pegá tu clave acá'}">
        <button onclick="saveKey('${pid}')">Guardar</button>
        ${p.has_key ? `<button onclick="deleteKey('${pid}')">Borrar</button>` : ""}
      </div>`;
    const baseUrl = pid === "openai_compatible" ? `
      <label class="muted">Base URL (ej.: https://api.deepseek.com/v1)</label>
      <input id="baseurl-${pid}" value="${esc(p.base_url||"")}" placeholder="https://…/v1">` : "";
    card.innerHTML = `
      <h2>${esc(PROVIDER_META[pid].name)}
        ${p.has_key ? '<span class="badge bv">clave guardada</span>' : '<span class="badge">sin clave</span>'}
        ${p.enabled ? '<span class="badge bv">habilitado</span>' : ''}
        ${u.quota_exhausted ? '<span class="badge b90">cuota agotada</span>' : ''}
      </h2>
      <p class="muted">${esc(PROVIDER_META[pid].hint)}</p>
      ${keyInput}${baseUrl}
      <div style="margin-top:10px">
        <input type="checkbox" id="enabled-${pid}" ${p.enabled?"checked":""}>
        <label for="enabled-${pid}">Habilitado</label>
        <input type="checkbox" id="allowcost-${pid}" style="margin-left:16px" ${p.allow_unverified_cost?"checked":""}>
        <label for="allowcost-${pid}" style="color:var(--warn)">Autorizo llamadas aunque el costo NO esté verificado como gratuito</label>
      </div>
      <div style="display:flex;gap:10px;margin-top:10px">
        <div><label class="muted">Límite solicitudes/día (0 = sin límite)</label>
          <input type="number" min="0" id="limreq-${pid}" value="${p.limits.max_requests_per_day}"></div>
        <div><label class="muted">Límite tokens/día (0 = sin límite)</label>
          <input type="number" min="0" id="limtok-${pid}" value="${p.limits.max_tokens_per_day}"></div>
      </div>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button onclick="saveSettings('${pid}')">Guardar ajustes</button>
        <button onclick="loadModels('${pid}')">Listar modelos</button>
        <button onclick="testProvider('${pid}')">Probar conexión</button>
        <span id="test-${pid}" class="muted"></span>
      </div>
      <div class="panel" id="models-${pid}" style="display:none;max-height:240px;overflow-y:auto;margin-top:10px"></div>
      <p class="muted" style="margin-top:10px">
        Uso hoy (UTC): <b>${u.requests||0}</b> solicitudes · <b>${u.tokens||0}</b> tokens ·
        Último uso: <b>${u.last_used_at ? esc(u.last_used_at) : "nunca"}</b><br>
        ${u.last_error ? `<span style="color:var(--bad)">Último error: ${esc(u.last_error)}</span>` : "Sin errores registrados."}
      </p>`;
    grid.appendChild(card);
  }
}
async function saveKey(pid){
  const input = $("key-"+pid), key = input.value.trim();
  if (!key){ alert("Pegá una API key primero."); return; }
  const r = await api("PUT", `/api/ai/providers/${pid}/key`, {key});
  if (r.ok){ input.value=""; await refresh(); } else alert("Error: "+(r.error||"desconocido"));
}
async function deleteKey(pid){
  if (!confirm("¿Borrar la API key de "+PROVIDER_META[pid].name+" del Credential Manager?")) return;
  const r = await api("DELETE", `/api/ai/providers/${pid}/key`);
  if (r.ok) await refresh(); else alert("Error: "+(r.error||"desconocido"));
}
async function saveSettings(pid){
  const body = {enabled: $("enabled-"+pid).checked,
    allow_unverified_cost: $("allowcost-"+pid).checked,
    limits: {max_requests_per_day: parseInt($("limreq-"+pid).value||"0",10),
             max_tokens_per_day: parseInt($("limtok-"+pid).value||"0",10)}};
  if (pid === "openai_compatible") body.base_url = $("baseurl-"+pid).value.trim();
  const r = await api("PUT", `/api/ai/providers/${pid}/settings`, body);
  if (r.ok) await refresh(); else alert("Error: "+(r.error||"desconocido"));
}
async function loadModels(pid){
  const box = $("models-"+pid); box.style.display = "block";
  box.innerHTML = '<p class="muted">Consultando la API del proveedor…</p>';
  const r = await api("GET", `/api/ai/providers/${pid}/models`);
  if (!r.ok){ box.innerHTML = `<p style="color:var(--bad)">${esc(r.error||"Error al listar")}</p>`; return; }
  let html = r.free_tier_info ? `<p class="muted">ℹ️ ${esc(r.free_tier_info)}</p>` : "";
  for (const m of r.models){
    html += `<div style="padding:5px 0;border-bottom:1px solid var(--line);cursor:pointer"
      onclick="useModel('${pid}','${esc(m.id)}')">
      <code>${esc(m.id)}</code>
      ${m.free ? '<span class="badge bv">GRATIS verificado</span>' : '<span class="badge">costo no verificado</span>'}
      <span class="muted">${esc(m.free_hint||"")}</span></div>`;
  }
  box.innerHTML = html || '<p class="muted">Sin modelos.</p>';
}
function useModel(pid, id){ $("primaryProvider").value = pid; $("primaryModel").value = id;
  window.scrollTo({top:0, behavior:"smooth"}); }
async function testProvider(pid){
  const el = $("test-"+pid);
  const model = ($("primaryProvider").value === pid) ? $("primaryModel").value.trim() : "";
  el.textContent = " Probando (solo listado, sin cargo)…";
  const r = await api("POST", "/api/ai/test", {provider: pid, model});
  el.textContent = r.ok
    ? ` ✅ Conexión OK — ${r.models_available} modelos.` + (model ? (r.model_available ? ` '${model}' disponible.` : ` '${model}' NO figura.`) : "")
    : " ❌ " + (r.error||"Fallo") + (r.quota_exhausted ? " (CUOTA AGOTADA)" : "");
  const usg = await api("GET","/api/ai/usage"); USAGE = usg.usage; renderProviders();
}
function addFallback(){
  const provider = $("fbProvider").value, model = $("fbModel").value.trim();
  if (!model){ alert("Indicá el identificador exacto del modelo fallback."); return; }
  CONFIG.routing.fallbacks.push({provider, model}); $("fbModel").value = ""; renderRouting();
}
function moveFallback(i, dir){
  const fb = CONFIG.routing.fallbacks, j = i + dir;
  if (j < 0 || j >= fb.length) return;
  [fb[i], fb[j]] = [fb[j], fb[i]]; renderRouting();
}
function removeFallback(i){ CONFIG.routing.fallbacks.splice(i,1); renderRouting(); }
async function saveRouting(){
  const r = await api("PUT", "/api/ai/routing", {
    primary: {provider: $("primaryProvider").value, model: $("primaryModel").value.trim()},
    fallbacks: CONFIG.routing.fallbacks});
  $("routingStatus").textContent = r.ok
    ? "✅ Guardado. Aplica sin reiniciar ni tocar código."
    : "❌ " + (r.error || "Error al guardar");
  if (r.ok) CONFIG.routing = r.routing;
}
refresh();
</script>
"""


def panel_html() -> str:
    meta = json.dumps({
        pid: {"name": PROVIDER_LABELS[pid],
              "hint": getattr(get_provider(pid), "free_tier_info", "")}
        for pid in PROVIDER_LABELS
    }, ensure_ascii=False)
    return PANEL_BODY.replace("%PROVIDER_META%", meta)
