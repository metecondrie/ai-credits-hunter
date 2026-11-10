"""Adaptadores de proveedores IA para el motor v4.

- list_models / test_connectivity: SOLO endpoints de listado (sin cargo).
- chat: llamada real de generacion. NUNCA se ejecuta sin que el orquestador
  (ach/ai_classify.py) haya verificado limites diarios y costo.
- Regla de costo (requisito 7): NO se asume gratuidad por marca o familia
  de modelo. Solo OpenRouter permite verificar gratuidad desde la API
  (sufijo ':free' o pricing 0). Todo lo demas es 'unknown' y queda bloqueado
  salvo autorizacion explicita del usuario (allow_unverified_cost).
- demo_local: proveedor de demostracion sin red ni clave, para pruebas y la
  demo verificable. Sus respuestas se marcan cost_status='demo_local'.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

DEFAULT_TIMEOUT = 30

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

PROVIDER_LABELS = {
    "gemini": "Google Gemini (AI Studio)",
    "groq": "GroqCloud",
    "openrouter": "OpenRouter",
    "openai_compatible": "Compatible OpenAI (base URL propia)",
    "demo_local": "Proveedor DEMO local (sin red, solo pruebas)",
}

COST_FREE = "free_verified"
COST_UNKNOWN = "unknown"
COST_DEMO = "demo_local"


class ProviderError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, quota_exhausted: bool = False):
        super().__init__(message)
        self.status = status
        self.quota_exhausted = quota_exhausted


# Inyeccion de red para tests (monkeypatch). Firma: (url, headers, payload, timeout) -> dict
HttpPostFn = Callable[[str, Dict[str, str], Optional[bytes], int], Dict[str, Any]]


def _http_json(url: str, headers: Optional[Dict[str, str]] = None,
               payload: Optional[bytes] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {}, data=payload,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        quota = exc.code in (402, 429)
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise ProviderError(f"HTTP {exc.code} del proveedor. {detail}".strip(),
                            status=exc.code, quota_exhausted=quota)
    except urllib.error.URLError as exc:
        raise ProviderError(f"Sin conectividad con el proveedor: {exc.reason}")
    except (json.JSONDecodeError, ValueError):
        raise ProviderError("Respuesta no valida del proveedor (JSON corrupto).")


def _http_post_json(url: str, headers: Optional[Dict[str, str]] = None,
                    payload: Optional[bytes] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    return _http_json(url, headers=headers, payload=payload, timeout=timeout)


class ChatResult:
    def __init__(self, text: str, tokens: int = 0, raw: Optional[Dict[str, Any]] = None):
        self.text = text
        self.tokens = tokens
        self.raw = raw or {}


class BaseProvider:
    provider_id = "base"
    label = "Base"
    needs_key = True
    free_tier_info = ""

    def list_models(self, api_key: str, base_url: str = "") -> List[Dict[str, Any]]:
        raise NotImplementedError

    def chat(self, api_key: str, model: str, messages: List[Dict[str, str]],
             base_url: str = "", max_tokens: int = 1024,
             http_post: Optional[HttpPostFn] = None) -> ChatResult:
        raise NotImplementedError

    def assess_cost(self, model: str, api_key: str = "", base_url: str = "") -> str:
        """COST_FREE solo si la gratuidad es verificable; si no, COST_UNKNOWN."""
        return COST_UNKNOWN

    def test_connectivity(self, api_key: str, model: str = "", base_url: str = "") -> Dict[str, Any]:
        models = self.list_models(api_key, base_url=base_url)
        result: Dict[str, Any] = {
            "ok": True, "provider": self.provider_id,
            "models_available": len(models), "model": model, "model_available": None,
            "free_tier_info": self.free_tier_info,
        }
        if model:
            ids = {m["id"] for m in models}
            result["model_available"] = model in ids
            if not result["model_available"]:
                result["ok"] = False
                result["detail"] = (f"El modelo '{model}' no figura entre los "
                                    f"{len(models)} disponibles para esta clave.")
        return result


class GeminiProvider(BaseProvider):
    provider_id = "gemini"
    label = PROVIDER_LABELS["gemini"]
    free_tier_info = (
        "AI Studio suele ofrecer free tier en modelos Flash, pero NO se asume: "
        "sin verificacion de costo desde la API, las llamadas quedan bloqueadas "
        "salvo autorizacion explicita."
    )

    def list_models(self, api_key: str, base_url: str = "") -> List[Dict[str, Any]]:
        base = (base_url or GEMINI_BASE).rstrip("/")
        data = _http_json(f"{base}/models?key={api_key}&pageSize=1000")
        models = []
        for m in data.get("models", []):
            name = str(m.get("name", ""))
            model_id = name.split("/", 1)[-1] if "/" in name else name
            if model_id:
                models.append({"id": model_id, "label": m.get("displayName") or model_id,
                               "free": False, "free_hint": "Costo no verificable desde la API"})
        return models

    def chat(self, api_key: str, model: str, messages, base_url: str = "",
             max_tokens: int = 1024, http_post: Optional[HttpPostFn] = None) -> ChatResult:
        post = http_post or _http_post_json
        base = (base_url or GEMINI_BASE).rstrip("/")
        contents = [{"role": "user" if m["role"] == "user" else "model",
                     "parts": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1,
                                 "responseMimeType": "application/json"},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = post(f"{base}/models/{model}:generateContent?key={api_key}",
                    headers={"Content-Type": "application/json"},
                    payload=json.dumps(body).encode("utf-8"))
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini devolvio una respuesta sin texto utilizable.")
        tokens = int((data.get("usageMetadata") or {}).get("totalTokenCount", 0) or 0)
        return ChatResult(text=text, tokens=tokens, raw=data)


class _OpenAIStyleProvider(BaseProvider):
    """Chat completions estilo OpenAI (Groq, OpenRouter, compatibles)."""

    default_base = ""

    def _headers(self, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def list_models(self, api_key: str, base_url: str = "") -> List[Dict[str, Any]]:
        base = (base_url or self.default_base).rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = _http_json(f"{base}/models", headers=headers)
        return [{"id": str(m.get("id", "")), "label": str(m.get("id", "")),
                 "free": False, "free_hint": "Costo no verificable desde la API"}
                for m in data.get("data", []) if m.get("id")]

    def chat(self, api_key: str, model: str, messages, base_url: str = "",
             max_tokens: int = 1024, http_post: Optional[HttpPostFn] = None) -> ChatResult:
        post = http_post or _http_post_json
        base = (base_url or self.default_base).rstrip("/")
        body = {"model": model, "messages": messages, "temperature": 0.1,
                "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
        data = post(f"{base}/chat/completions", headers=self._headers(api_key),
                    payload=json.dumps(body).encode("utf-8"))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.label} devolvio una respuesta sin texto utilizable.")
        tokens = int((data.get("usage") or {}).get("total_tokens", 0) or 0)
        return ChatResult(text=text, tokens=tokens, raw=data)


class GroqProvider(_OpenAIStyleProvider):
    provider_id = "groq"
    label = PROVIDER_LABELS["groq"]
    default_base = GROQ_BASE
    free_tier_info = (
        "GroqCloud publica free tier con limites de tasa, pero el plan de la "
        "cuenta no es verificable desde la API: ante la duda, llamada bloqueada."
    )


class OpenRouterProvider(_OpenAIStyleProvider):
    provider_id = "openrouter"
    label = PROVIDER_LABELS["openrouter"]
    default_base = OPENROUTER_BASE
    free_tier_info = (
        "Unico proveedor con gratuidad verificable desde la API: modelos ':free' "
        "o con pricing 0. Esos se marcan GRATIS y no requieren autorizacion extra."
    )

    def list_models(self, api_key: str, base_url: str = "") -> List[Dict[str, Any]]:
        base = (base_url or self.default_base).rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = _http_json(f"{base}/models", headers=headers)
        models = []
        for m in data.get("data", []):
            model_id = str(m.get("id", ""))
            if not model_id:
                continue
            free = self._is_free(model_id, m.get("pricing") or {})
            models.append({"id": model_id, "label": m.get("name") or model_id, "free": free,
                           "free_hint": "Gratuito verificado (:free / pricing 0)" if free
                           else "De pago segun pricing"})
        models.sort(key=lambda m: (not m["free"], m["id"]))
        return models

    @staticmethod
    def _is_free(model_id: str, pricing: Dict[str, Any]) -> bool:
        if model_id.endswith(":free"):
            return True
        try:
            return (float(pricing.get("prompt", "1") or 1) == 0.0
                    and float(pricing.get("completion", "1") or 1) == 0.0)
        except (TypeError, ValueError):
            return False

    def assess_cost(self, model: str, api_key: str = "", base_url: str = "") -> str:
        if model.endswith(":free"):
            return COST_FREE
        try:
            models = self.list_models(api_key, base_url=base_url)
        except ProviderError:
            return COST_UNKNOWN
        for m in models:
            if m["id"] == model:
                return COST_FREE if m["free"] else COST_UNKNOWN
        return COST_UNKNOWN


class OpenAICompatibleProvider(_OpenAIStyleProvider):
    provider_id = "openai_compatible"
    label = PROVIDER_LABELS["openai_compatible"]
    free_tier_info = (
        "Endpoint generico /v1 (Mistral, Z.ai, DeepSeek, Together...). "
        "La gratuidad no es verificable: bloqueado salvo autorizacion explicita."
    )

    def _require_base(self, base_url: str) -> str:
        if not base_url:
            raise ProviderError("Falta la Base URL del proveedor compatible.")
        return base_url.rstrip("/")

    def list_models(self, api_key: str, base_url: str = "") -> List[Dict[str, Any]]:
        return super().list_models(api_key, base_url=self._require_base(base_url))

    def chat(self, api_key: str, model: str, messages, base_url: str = "",
             max_tokens: int = 1024, http_post: Optional[HttpPostFn] = None) -> ChatResult:
        return super().chat(api_key, model, messages,
                            base_url=self._require_base(base_url),
                            max_tokens=max_tokens, http_post=http_post)


class DemoLocalProvider(BaseProvider):
    """Proveedor de demostracion: sin red, sin clave, respuesta determinista.

    Existe SOLO para pruebas y la demo verificable. Sus resultados se marcan
    cost_status='demo_local' y nunca se presentan como verificacion oficial.
    """

    provider_id = "demo_local"
    label = PROVIDER_LABELS["demo_local"]
    needs_key = False
    free_tier_info = "Proveedor de demostracion local. No contacta ninguna API real."

    def list_models(self, api_key: str = "", base_url: str = "") -> List[Dict[str, Any]]:
        return [{"id": "demo-clasificador-1", "label": "Clasificador DEMO (local)",
                 "free": True, "free_hint": "Demo local sin red"}]

    def assess_cost(self, model: str, api_key: str = "", base_url: str = "") -> str:
        return COST_DEMO

    def chat(self, api_key: str, model: str, messages, base_url: str = "",
             max_tokens: int = 1024, http_post: Optional[HttpPostFn] = None) -> ChatResult:
        # Respuesta estructurada determinista a partir del contenido del prompt,
        # para que la demo y los tests sean reproducibles sin red.
        blob = " ".join(m["content"] for m in messages).lower()
        is_offer = any(k in blob for k in ("free", "gratis", "discount", "descuento",
                                           "credits", "trial", "%"))
        benefit_type = ("FREE_TIER" if ("free tier" in blob or "gratis" in blob or " free" in blob)
                        else "CREDITS" if "credit" in blob
                        else "DISCOUNT" if ("discount" in blob or "descuento" in blob or "%" in blob)
                        else "ANUNCIO")
        arg = ("ARGENTINA_NO_CONFIRMADA" if "argentina" not in blob and "worldwide" not in blob
               else "DISPONIBLE_POR_DECLARACION")
        payload = {
            "is_offer": is_offer,
            "benefit_type": benefit_type,
            "conditions": "No especificadas (respuesta DEMO local, sin red).",
            "restrictions": "Desconocidas (DEMO).",
            "argentina_eligibility": arg,
            "confidence": "baja",
            "justification": "Respuesta DEMO local determinista para pruebas del recorrido; "
                             "no proviene de un modelo real ni verifica la oferta.",
        }
        return ChatResult(text=json.dumps(payload), tokens=0, raw={"demo": True})


PROVIDERS: Dict[str, BaseProvider] = {
    "gemini": GeminiProvider(),
    "groq": GroqProvider(),
    "openrouter": OpenRouterProvider(),
    "openai_compatible": OpenAICompatibleProvider(),
    "demo_local": DemoLocalProvider(),
}


def get_provider(provider_id: str) -> BaseProvider:
    if provider_id not in PROVIDERS:
        raise ProviderError(f"Proveedor desconocido: {provider_id}")
    return PROVIDERS[provider_id]
