"""Configuracion de IA para AI Credits Hunter v4 (seccion Configuracion -> IA).

Reglas inviolables:
- Las API keys NUNCA se guardan en SQLite, JSON, Git, logs ni reportes.
  Se almacenan EXCLUSIVAMENTE en Windows Credential Manager via `keyring`.
- La configuracion no sensible (modelos, fallback, limites, autorizaciones)
  vive en `data/ai_config.json`; el uso diario en `data/ai_usage.json`.
- Sin ninguna API configurada el cazador sigue funcionando en modo
  determinista (extractores y reglas). La IA es OPCIONAL.
- `allow_unverified_cost`: unico mecanismo por el que el usuario autoriza,
  de forma explicita y por proveedor, llamadas cuyo costo no esta verificado
  como gratuito. Por defecto es False: ante la duda, se BLOQUEA.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import config as ach_config

KEYRING_SERVICE = "AI-Credits-Hunter-v4"
KEYRING_USER_TEMPLATE = "apikey:{provider_id}"

# demo_local: proveedor de demostracion sin red ni clave (tests y demo).
SUPPORTED_PROVIDERS = ("gemini", "groq", "openrouter", "openai_compatible", "demo_local")

DEFAULT_PROVIDER_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "allow_unverified_cost": False,  # autorizacion explicita del usuario
    "base_url": "",                  # solo aplica a openai_compatible
    "limits": {
        "max_requests_per_day": 0,   # 0 = sin limite definido
        "max_tokens_per_day": 0,     # 0 = sin limite definido
    },
}

DEFAULT_ROUTING: Dict[str, Any] = {
    "primary": {"provider": "", "model": ""},
    "fallbacks": [],  # lista ordenada de {"provider": ..., "model": ...}
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "providers": {pid: dict(DEFAULT_PROVIDER_SETTINGS) for pid in SUPPORTED_PROVIDERS},
    "routing": dict(DEFAULT_ROUTING),
}


class AISettingsError(Exception):
    """Error de la capa de configuracion IA."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _atomic_write_json(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def mask_key(key: Optional[str]) -> str:
    """Clave enmascarada para UI. Nunca la clave completa."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


class KeyStore:
    """Almacenamiento seguro de claves (Windows Credential Manager via keyring)."""

    def __init__(self, backend: Any = None) -> None:
        if backend is not None:
            self._kr = backend
        else:
            import keyring  # import diferido: modulo opcional
            self._kr = keyring

    def _user(self, provider_id: str) -> str:
        return KEYRING_USER_TEMPLATE.format(provider_id=provider_id)

    def set_key(self, provider_id: str, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise AISettingsError("La API key no puede estar vacia.")
        self._kr.set_password(KEYRING_SERVICE, self._user(provider_id), api_key.strip())

    def get_key(self, provider_id: str) -> Optional[str]:
        return self._kr.get_password(KEYRING_SERVICE, self._user(provider_id))

    def delete_key(self, provider_id: str) -> None:
        try:
            self._kr.delete_password(KEYRING_SERVICE, self._user(provider_id))
        except Exception:
            pass  # borrado idempotente

    def has_key(self, provider_id: str) -> bool:
        return bool(self.get_key(provider_id))


class AISettingsStore:
    """Fachada unica de la configuracion IA del motor v4."""

    def __init__(self, config_path=None, usage_path=None, keystore: Optional[KeyStore] = None):
        self.config_path = config_path or (ach_config.DATA_DIR / "ai_config.json")
        self.usage_path = usage_path or (ach_config.DATA_DIR / "ai_usage.json")
        self.keys = keystore or KeyStore()

    # ------------------------------------------------------------------ config
    def load_config(self) -> Dict[str, Any]:
        cfg = _read_json(self.config_path, DEFAULT_CONFIG)
        cfg.setdefault("version", 1)
        cfg.setdefault("providers", {})
        for pid in SUPPORTED_PROVIDERS:
            base = json.loads(json.dumps(DEFAULT_PROVIDER_SETTINGS))
            base.update(cfg["providers"].get(pid, {}))
            base["limits"] = {**DEFAULT_PROVIDER_SETTINGS["limits"], **base.get("limits", {})}
            cfg["providers"][pid] = base
        routing = json.loads(json.dumps(DEFAULT_ROUTING))
        routing.update(cfg.get("routing", {}))
        cfg["routing"] = routing
        return cfg

    def save_config(self, cfg: Dict[str, Any]) -> None:
        _atomic_write_json(self.config_path, cfg)

    def public_config(self) -> Dict[str, Any]:
        """Config para UI/API: has_key y clave enmascarada, JAMAS la clave."""
        cfg = self.load_config()
        out = json.loads(json.dumps(cfg))
        for pid in SUPPORTED_PROVIDERS:
            key = self.keys.get_key(pid)
            out["providers"][pid]["has_key"] = bool(key)
            out["providers"][pid]["masked_key"] = mask_key(key)
        out["deterministic_mode"] = not self.ai_available()
        return out

    def ai_available(self) -> bool:
        """Hay al menos un destino utilizable (clave guardada o demo habilitado)."""
        cfg = self.load_config()
        targets = [cfg["routing"]["primary"], *cfg["routing"]["fallbacks"]]
        for t in targets:
            pid = t.get("provider")
            if not pid or pid not in cfg["providers"]:
                continue
            if not cfg["providers"][pid]["enabled"]:
                continue
            if pid == "demo_local" or self.keys.has_key(pid):
                return True
        return False

    # --------------------------------------------------------------- API keys
    def set_api_key(self, provider_id: str, api_key: str) -> None:
        self._require_provider(provider_id)
        if provider_id == "demo_local":
            raise AISettingsError("demo_local no usa API key.")
        self.keys.set_key(provider_id, api_key)
        cfg = self.load_config()
        cfg["providers"][provider_id]["enabled"] = True
        self.save_config(cfg)

    def delete_api_key(self, provider_id: str) -> None:
        self._require_provider(provider_id)
        self.keys.delete_key(provider_id)
        cfg = self.load_config()
        cfg["providers"][provider_id]["enabled"] = False
        routing = cfg["routing"]
        if routing["primary"].get("provider") == provider_id:
            routing["primary"] = {"provider": "", "model": ""}
        routing["fallbacks"] = [f for f in routing["fallbacks"] if f.get("provider") != provider_id]
        self.save_config(cfg)

    # --------------------------------------------------------------- settings
    def update_provider_settings(self, provider_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        self._require_provider(provider_id)
        cfg = self.load_config()
        prov = cfg["providers"][provider_id]
        if "enabled" in settings:
            prov["enabled"] = bool(settings["enabled"])
        if "allow_unverified_cost" in settings:
            prov["allow_unverified_cost"] = bool(settings["allow_unverified_cost"])
        if "base_url" in settings and provider_id == "openai_compatible":
            prov["base_url"] = str(settings["base_url"]).strip()
        if "limits" in settings and isinstance(settings["limits"], dict):
            for field in ("max_requests_per_day", "max_tokens_per_day"):
                if field in settings["limits"]:
                    value = int(settings["limits"][field])
                    if value < 0:
                        raise AISettingsError(f"{field} no puede ser negativo.")
                    prov["limits"][field] = value
        self.save_config(cfg)
        return prov

    # ---------------------------------------------------------------- routing
    def update_routing(self, primary=None, fallbacks=None) -> Dict[str, Any]:
        cfg = self.load_config()
        if primary is not None:
            cfg["routing"]["primary"] = self._validate_target(primary)
        if fallbacks is not None:
            cfg["routing"]["fallbacks"] = [self._validate_target(f) for f in fallbacks]
        self.save_config(cfg)
        return cfg["routing"]

    def _validate_target(self, target: Dict[str, str]) -> Dict[str, str]:
        provider = str(target.get("provider", "")).strip()
        model = str(target.get("model", "")).strip()
        if provider and provider not in SUPPORTED_PROVIDERS:
            raise AISettingsError(f"Proveedor desconocido: {provider}")
        if provider and not model:
            raise AISettingsError("El modelo es obligatorio si hay proveedor.")
        return {"provider": provider, "model": model}

    def routing_chain(self) -> List[Dict[str, str]]:
        """Cadena ordenada de intento: principal + fallbacks habilitados."""
        cfg = self.load_config()
        chain = []
        for t in [cfg["routing"]["primary"], *cfg["routing"]["fallbacks"]]:
            pid, model = t.get("provider"), t.get("model")
            if pid and model and pid in cfg["providers"] and cfg["providers"][pid]["enabled"]:
                chain.append({"provider": pid, "model": model})
        return chain

    # ------------------------------------------------------------------ usage
    def load_usage(self) -> Dict[str, Any]:
        return _read_json(self.usage_path, {})

    def save_usage(self, usage: Dict[str, Any]) -> None:
        _atomic_write_json(self.usage_path, usage)

    def _usage_entry(self, usage: Dict[str, Any], provider_id: str) -> Dict[str, Any]:
        entry = usage.setdefault(provider_id, {})
        if entry.get("date") != _today_utc():
            entry["date"] = _today_utc()
            entry["requests"] = 0
            entry["tokens"] = 0
        entry.setdefault("requests", 0)
        entry.setdefault("tokens", 0)
        return entry

    def check_limits(self, provider_id: str) -> Tuple[bool, str]:
        cfg = self.load_config()
        limits = cfg["providers"][provider_id]["limits"]
        usage = self.load_usage()
        entry = self._usage_entry(usage, provider_id)
        max_req = limits.get("max_requests_per_day", 0)
        max_tok = limits.get("max_tokens_per_day", 0)
        if max_req and entry["requests"] >= max_req:
            return False, f"Limite diario de solicitudes alcanzado ({max_req})."
        if max_tok and entry["tokens"] >= max_tok:
            return False, f"Limite diario de tokens alcanzado ({max_tok})."
        return True, ""

    def record_usage(self, provider_id: str, tokens: int = 0,
                     error: Optional[str] = None, quota_exhausted: bool = False) -> None:
        usage = self.load_usage()
        entry = self._usage_entry(usage, provider_id)
        entry["requests"] += 1
        entry["tokens"] += max(0, int(tokens))
        entry["last_used_at"] = _now_iso()
        if error:
            entry["last_error"] = str(error)[:500]
            entry["last_error_at"] = _now_iso()
        else:
            entry.pop("last_error", None)
            entry.pop("last_error_at", None)
        if quota_exhausted:
            entry["quota_exhausted"] = True
        else:
            entry.pop("quota_exhausted", None)
        self.save_usage(usage)

    def public_usage(self) -> Dict[str, Any]:
        usage = self.load_usage()
        out = {}
        for pid in SUPPORTED_PROVIDERS:
            out[pid] = dict(self._usage_entry(usage, pid)) if pid in usage else {
                "date": _today_utc(), "requests": 0, "tokens": 0,
            }
        self.save_usage(usage)
        return out

    # ------------------------------------------------------------------ misc
    def _require_provider(self, provider_id: str) -> None:
        if provider_id not in SUPPORTED_PROVIDERS:
            raise AISettingsError(f"Proveedor desconocido: {provider_id}")

    def provider_settings(self, provider_id: str) -> Dict[str, Any]:
        self._require_provider(provider_id)
        return self.load_config()["providers"][provider_id]
