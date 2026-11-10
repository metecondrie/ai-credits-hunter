"""Tests de la integracion IA en AI Credits Hunter v4.

Sin red, sin claves reales: keyring mockeado en memoria y HTTP mockeado.
Cubre: recorrido completo fixture -> IA -> SQLite -> interfaz, bloqueos de
costo y limite, cadena de fallback, parseo robusto y modo determinista.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ach import pipeline, store
from ach.ai_classify import (
    BLOCKED_ALL_FAILED, BLOCKED_COST, BLOCKED_LIMIT, BLOCKED_NO_CHAIN,
    build_messages, classify_candidate, parse_response,
)
from ach.ai_providers import COST_DEMO, COST_FREE, COST_UNKNOWN
from ach.ai_settings import AISettingsError, AISettingsStore, KeyStore, mask_key
from ach.models import Candidate


# --------------------------------------------------------------------------
# Mocks
# --------------------------------------------------------------------------
class FakeKeyring:
    def __init__(self):
        self._store = {}

    def set_password(self, service, user, password):
        self._store[(service, user)] = password

    def get_password(self, service, user):
        return self._store.get((service, user))

    def delete_password(self, service, user):
        if (service, user) not in self._store:
            raise KeyError(user)
        del self._store[(service, user)]


GOOD_JSON = json.dumps({
    "is_offer": True,
    "benefit_type": "FREE_TIER",
    "conditions": "Sin tarjeta; limite de 15 RPM.",
    "restrictions": "Limites de tasa del free tier.",
    "argentina_eligibility": "ARGENTINA_NO_CONFIRMADA",
    "confidence": "media",
    "justification": "La evidencia menciona plan gratuito permanente.",
})


def mock_http_post_ok(url, headers=None, payload=None, timeout=30):
    """Respuesta chat/completions estilo OpenAI con JSON valido."""
    return {
        "choices": [{"message": {"content": GOOD_JSON}}],
        "usage": {"total_tokens": 321},
    }


# Catalogo simulado: un modelo pago y otro gratuito por pricing 0.
OPENROUTER_CATALOG = {"data": [
    {"id": "openai/gpt-5", "name": "GPT-5",
     "pricing": {"prompt": "0.000005", "completion": "0.000015"}},
    {"id": "gratis-por-pricing", "name": "Gratis por pricing",
     "pricing": {"prompt": "0", "completion": "0"}},
]}


def mock_http_post_openrouter(url, headers=None, payload=None, timeout=30):
    """Responde segun la URL: catalogo /models o chat/completions.

    Regresion P0.4: assess_cost() consulta el catalogo por la misma via que
    chat(). Con un mock que solo sabe responder al chat, esa consulta se iba a
    la red real aunque la prueba pareciera offline.
    """
    if url.rstrip("/").endswith("/models"):
        return OPENROUTER_CATALOG
    return {"choices": [{"message": {"content": GOOD_JSON}}],
            "usage": {"total_tokens": 321}}


def make_candidate() -> Candidate:
    return Candidate(
        source_id="test-source",
        provider_key="openrouter",
        product="OpenRouter Free Models",
        title="Free tier models on OpenRouter",
        offer_type="ANUNCIO_PROMOCIONAL",
        benefit="Access to free tier models with rate limits, no credit card.",
        official_url="https://openrouter.ai/models",
        evidence_url="https://openrouter.ai/models",
        evidence_snippet="Free tier available: llama-3.3-70b-instruct:free with daily limits.",
        extraction_rule="test_rule",
        price_baseline=None,
        price_offer=0.0,
        price_unit="USD",
    )


def make_store(tmp: tempfile.TemporaryDirectory) -> AISettingsStore:
    return AISettingsStore(
        config_path=Path(tmp.name) / "ai_config.json",
        usage_path=Path(tmp.name) / "ai_usage.json",
        keystore=KeyStore(backend=FakeKeyring()),
    )


# --------------------------------------------------------------------------
# Configuracion y seguridad de claves
# --------------------------------------------------------------------------
class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = make_store(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_only_in_keyring(self):
        self.store.set_api_key("gemini", "AIza-test-key-0000000000")
        with open(self.store.config_path, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("AIza-test-key", raw)

    def test_public_config_masks_key(self):
        key = "sk-or-v1-abcdef1234567890"
        self.store.set_api_key("openrouter", key)
        pub = self.store.public_config()
        self.assertNotIn(key, json.dumps(pub))
        self.assertEqual(pub["providers"]["openrouter"]["masked_key"], mask_key(key))

    def test_allow_unverified_cost_defaults_false(self):
        cfg = self.store.load_config()
        for pid in ("gemini", "groq", "openrouter", "openai_compatible"):
            self.assertFalse(cfg["providers"][pid]["allow_unverified_cost"])

    def test_ai_available_only_with_enabled_target(self):
        self.assertFalse(self.store.ai_available())
        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_routing(primary={"provider": "groq", "model": "llama-3.3-70b-versatile"})
        self.assertTrue(self.store.ai_available())


# --------------------------------------------------------------------------
# Parseo robusto de respuestas
# --------------------------------------------------------------------------
class ParseTestCase(unittest.TestCase):
    def test_plain_json(self):
        a = parse_response(GOOD_JSON)
        self.assertTrue(a.is_offer)
        self.assertEqual(a.benefit_type, "FREE_TIER")
        self.assertEqual(a.argentina_eligibility, "ARGENTINA_NO_CONFIRMADA")

    def test_json_in_markdown_fence(self):
        a = parse_response(f"Claro, aqui va:\n```json\n{GOOD_JSON}\n```\nSaludos.")
        self.assertTrue(a.is_offer)

    def test_json_with_surrounding_text(self):
        a = parse_response(f"Resultado: {GOOD_JSON} fin.")
        self.assertTrue(a.is_offer)

    def test_non_json_rejected(self):
        with self.assertRaises(ValueError):
            parse_response("Esto es una opinion sin estructura.")

    def test_missing_keys_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(json.dumps({"is_offer": True}))

    def test_invalid_enums_normalized(self):
        data = json.loads(GOOD_JSON)
        data["benefit_type"] = "INVENTADO"
        data["confidence"] = "altisima"
        data["argentina_eligibility"] = "SI"
        a = parse_response(json.dumps(data))
        self.assertEqual(a.benefit_type, "OTRO")
        self.assertEqual(a.confidence, "baja")
        self.assertEqual(a.argentina_eligibility, "ARGENTINA_NO_CONFIRMADA")

    def test_is_offer_true_booleano_aceptado(self):
        a = parse_response(GOOD_JSON)
        self.assertIs(a.is_offer, True)

    def test_is_offer_false_booleano_aceptado(self):
        """`false` autentico es un veredicto valido: rechazado, no error."""
        data = json.loads(GOOD_JSON)
        data["is_offer"] = False
        a = parse_response(json.dumps(data))
        self.assertIs(a.is_offer, False)

    def test_is_offer_false_textual_rechazado(self):
        """Regresion P0.1: bool("false") era True y clasificaba una oferta inexistente."""
        crudo = GOOD_JSON.replace('"is_offer": true', '"is_offer": "false"')
        self.assertIn('"is_offer": "false"', crudo)
        with self.assertRaises(ValueError):
            parse_response(crudo)

    def test_is_offer_no_booleano_rechazado(self):
        base = json.loads(GOOD_JSON)
        invalidos = ["false", "true", "si", "no", "", 0, 1, 1.0, -1, None,
                     [], {}, ["true"], {"valor": True}]
        for invalido in invalidos:
            with self.subTest(is_offer=invalido):
                data = dict(base)
                data["is_offer"] = invalido
                with self.assertRaises(ValueError):
                    parse_response(json.dumps(data))

    def test_is_offer_invalido_menciona_el_campo_en_el_error(self):
        data = json.loads(GOOD_JSON)
        data["is_offer"] = "false"
        with self.assertRaises(ValueError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("is_offer", str(ctx.exception))


# --------------------------------------------------------------------------
# Clasificacion: cadena, bloqueos y fallback
# --------------------------------------------------------------------------
class ClassifyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = make_store(self.tmp)
        self.cand = make_candidate()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_chain_returns_explicit_block(self):
        outcome = classify_candidate(self.cand, store=self.store)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.blocked, BLOCKED_NO_CHAIN)

    def test_cost_unknown_blocks_without_authorization(self):
        """Groq: gratuidad NO asumida. Sin autorizacion -> bloqueo (requisito 7)."""
        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_routing(primary={"provider": "groq", "model": "llama-3.3-70b-versatile"})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=mock_http_post_ok)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.blocked, BLOCKED_COST)

    def test_explicit_authorization_allows_call(self):
        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.store.update_routing(primary={"provider": "groq", "model": "llama-3.3-70b-versatile"})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=mock_http_post_ok)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.cost_status, COST_UNKNOWN)
        self.assertEqual(outcome.tokens, 321)
        usage = self.store.public_usage()["groq"]
        self.assertEqual(usage["requests"], 1)
        self.assertEqual(usage["tokens"], 321)

    def test_openrouter_free_model_is_verified_free(self):
        self.store.set_api_key("openrouter", "sk-or-test")
        self.store.update_routing(
            primary={"provider": "openrouter",
                     "model": "meta-llama/llama-3.3-70b-instruct:free"})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=mock_http_post_ok)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.cost_status, COST_FREE)

    def test_openrouter_paid_model_blocked_without_authorization(self):
        """P0.4: el catalogo se consulta por el transporte inyectado, sin red.

        El bloqueo sigue siendo real: el modelo figura con pricing distinto de
        cero, asi que el costo no es verificable como gratuito.
        """
        urls = []

        def registro(url, headers=None, payload=None, timeout=30):
            urls.append(url)
            return mock_http_post_openrouter(url, headers, payload, timeout)

        self.store.set_api_key("openrouter", "sk-or-test")
        self.store.update_routing(primary={"provider": "openrouter", "model": "openai/gpt-5"})
        outcome = classify_candidate(self.cand, store=self.store, http_post=registro)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.blocked, BLOCKED_COST)
        # El resultado agregado no propaga cost_status: el bloqueo por costo
        # queda registrado en el intento, con su motivo.
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(outcome.attempts[0]["blocked"], BLOCKED_COST)
        self.assertIn("no verificable como gratuito", outcome.attempts[0]["detail"])
        self.assertTrue(any(u.rstrip("/").endswith("/models") for u in urls), urls)
        # Bloqueado antes de gastar una llamada de chat.
        self.assertFalse(any("chat/completions" in u for u in urls), urls)

    def test_openrouter_zero_pricing_model_is_verified_free(self):
        """La verificacion de gratuidad por pricing 0 se conserva (P0.4)."""
        self.store.set_api_key("openrouter", "sk-or-test")
        self.store.update_routing(
            primary={"provider": "openrouter", "model": "gratis-por-pricing"})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=mock_http_post_openrouter)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.cost_status, COST_FREE)

    def test_openrouter_free_suffix_needs_no_catalog_query(self):
        """El atajo ':free' sigue sin consultar el catalogo ni la red."""
        def solo_chat(url, headers=None, payload=None, timeout=30):
            if url.rstrip("/").endswith("/models"):
                raise AssertionError("el sufijo :free no debe consultar el catalogo")
            return mock_http_post_openrouter(url, headers, payload, timeout)

        self.store.set_api_key("openrouter", "sk-or-test")
        self.store.update_routing(
            primary={"provider": "openrouter",
                     "model": "meta-llama/llama-3.3-70b-instruct:free"})
        outcome = classify_candidate(self.cand, store=self.store, http_post=solo_chat)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.cost_status, COST_FREE)

    def test_assess_cost_accepts_injected_transport(self):
        """El seam cubre assess_cost() y list_models(), no solo chat()."""
        from ach import ai_providers
        vistas = []

        def transporte(url, headers=None, payload=None, timeout=30):
            vistas.append(url)
            return OPENROUTER_CATALOG

        prov = ai_providers.get_provider("openrouter")
        modelos = prov.list_models("sk-or-test", http_post=transporte)
        self.assertEqual(len(vistas), 1)
        self.assertTrue(vistas[0].rstrip("/").endswith("/models"))
        self.assertEqual(prov.assess_cost("openai/gpt-5", api_key="sk-or-test",
                                          http_post=transporte), COST_UNKNOWN)
        self.assertEqual(prov.assess_cost("gratis-por-pricing", api_key="sk-or-test",
                                          http_post=transporte), COST_FREE)
        self.assertEqual(len(vistas), 3)
        self.assertTrue(any(m["id"] == "gratis-por-pricing" and m["free"] for m in modelos))

    def test_daily_limit_blocks(self):
        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_provider_settings("groq", {
            "allow_unverified_cost": True, "limits": {"max_requests_per_day": 1}})
        self.store.update_routing(primary={"provider": "groq", "model": "llama-3.3-70b-versatile"})
        first = classify_candidate(self.cand, store=self.store, http_post=mock_http_post_ok)
        self.assertTrue(first.ok)
        second = classify_candidate(self.cand, store=self.store, http_post=mock_http_post_ok)
        self.assertFalse(second.ok)
        self.assertEqual(second.blocked, BLOCKED_LIMIT)

    def test_fallback_chain_second_model_answers(self):
        def fail_then_ok(url, headers=None, payload=None, timeout=30):
            from ach.ai_providers import ProviderError
            raise ProviderError("HTTP 429 rate limit", status=429, quota_exhausted=True)

        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.store.update_routing(
            primary={"provider": "groq", "model": "modelo-caido"},
            fallbacks=[{"provider": "demo_local", "model": "demo-clasificador-1"}])
        self.store.update_provider_settings("demo_local", {"enabled": True})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=fail_then_ok)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.provider, "demo_local")
        self.assertEqual(len(outcome.attempts), 1)  # el primero fallo y registro el intento
        self.assertTrue(outcome.attempts[0]["blocked"])

    def test_all_models_failed_explicit(self):
        def always_fail(url, headers=None, payload=None, timeout=30):
            from ach.ai_providers import ProviderError
            raise ProviderError("HTTP 500", status=500)

        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.store.update_routing(primary={"provider": "groq", "model": "x"})
        outcome = classify_candidate(self.cand, store=self.store, http_post=always_fail)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.blocked, BLOCKED_ALL_FAILED)

    def test_is_offer_invalido_no_genera_clasificacion_positiva(self):
        """Regresion P0.1: veredicto no booleano -> intento bloqueado, sin assessment."""
        contenido = GOOD_JSON.replace('"is_offer": true', '"is_offer": "false"')

        def http_veredicto_textual(url, headers=None, payload=None, timeout=30):
            return {"choices": [{"message": {"content": contenido}}],
                    "usage": {"total_tokens": 120}}

        self.store.set_api_key("groq", "gsk_test_123456")
        self.store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.store.update_routing(primary={"provider": "groq", "model": "llama-3.3-70b-versatile"})
        outcome = classify_candidate(self.cand, store=self.store,
                                     http_post=http_veredicto_textual)
        self.assertFalse(outcome.ok)
        self.assertIsNone(outcome.assessment)
        self.assertEqual(outcome.blocked, BLOCKED_ALL_FAILED)
        self.assertIn("is_offer", outcome.detail)

    def test_prompt_contains_description_evidence_and_url(self):
        msgs = build_messages(self.cand)
        user = msgs[1]["content"]
        self.assertIn(self.cand.benefit, user)
        self.assertIn(self.cand.evidence_snippet[:100], user)
        self.assertIn(self.cand.evidence_url, user)

    def test_demo_local_needs_no_key(self):
        self.store.update_provider_settings("demo_local", {"enabled": True})
        self.store.update_routing(
            primary={"provider": "demo_local", "model": "demo-clasificador-1"})
        outcome = classify_candidate(self.cand, store=self.store)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.cost_status, COST_DEMO)
        self.assertIsNotNone(outcome.assessment.is_offer)


# --------------------------------------------------------------------------
# Recorrido completo: fixture -> pipeline -> IA -> SQLite -> interfaz
# --------------------------------------------------------------------------
class FullJourneyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "viaje.sqlite3"
        self.ai_store = make_store(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_pipeline(self, use_ai: bool):
        self.ai_store.update_provider_settings("demo_local", {"enabled": True})
        self.ai_store.update_routing(
            primary={"provider": "demo_local", "model": "demo-clasificador-1"})
        return pipeline.run(
            db_path=self.db,
            fixture_dir=BASE_DIR / "tests" / "fixtures",
            quiet=True,
            use_ai=use_ai,
            ai_store=self.ai_store,
        )

    def test_journey_with_ai_persists_assessments_and_keeps_evidence(self):
        report = self._run_pipeline(use_ai=True)
        self.assertGreater(report.candidates, 0)
        self.assertEqual(report.ai_classified, report.candidates)
        self.assertEqual(report.ai_blocked, 0)

        conn = store.connect(self.db, readonly=True)
        n_assess = conn.execute("SELECT COUNT(*) FROM ai_assessment WHERE error IS NULL").fetchone()[0]
        n_offers = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
        n_evidence = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        self.assertEqual(n_assess, n_offers)
        self.assertGreater(n_evidence, 0)

        # Evidencia original intacta: snippet y sha256 presentes, sin tocar por la IA.
        row = conn.execute(
            "SELECT snippet, content_sha256 FROM evidence LIMIT 1").fetchone()
        self.assertTrue(row["snippet"])
        # Las interpretaciones estan marcadas como demo y no alteran verification_level.
        a = conn.execute("SELECT * FROM ai_assessment WHERE error IS NULL LIMIT 1").fetchone()
        self.assertEqual(a["cost_status"], "demo_local")
        self.assertIn(a["confidence"], ("alta", "media", "baja"))
        self.assertIn(a["benefit_type"],
                      ("FREE_TIER", "TRIAL", "CREDITS", "DISCOUNT", "OFF_PEAK",
                       "STUDENT", "ANUNCIO", "OTRO"))
        lvls = {r[0] for r in conn.execute("SELECT DISTINCT verification_level FROM offer")}
        self.assertTrue(lvls <= {"FIXTURE", "NETWORK_VERIFIED", "CONTENT_VERIFIED", "UNVERIFIED"})
        conn.close()

    def test_journey_without_ai_keeps_hunter_working(self):
        """Sin IA: el cazador funciona igual y no hay assessments (requisito 8)."""
        report = self._run_pipeline(use_ai=False)
        self.assertGreater(report.candidates, 0)
        self.assertEqual(report.ai_classified, 0)
        self.assertEqual(report.ai_blocked, 0)
        conn = store.connect(self.db, readonly=True)
        n = conn.execute("SELECT COUNT(*) FROM ai_assessment").fetchone()[0]
        self.assertEqual(n, 0)
        conn.close()

    def test_ai_failure_does_not_break_run(self):
        def boom(url, headers=None, payload=None, timeout=30):
            from ach.ai_providers import ProviderError
            raise ProviderError("HTTP 500 simulado", status=500)

        self.ai_store.set_api_key("groq", "gsk_test_123456")
        self.ai_store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.ai_store.update_routing(primary={"provider": "groq", "model": "x"})
        report = pipeline.run(
            db_path=self.db,
            fixture_dir=BASE_DIR / "tests" / "fixtures",
            quiet=True,
            use_ai=True,
            ai_store=self.ai_store,
            ai_http_post=boom,
        )
        self.assertGreater(report.candidates, 0)          # la corrida NO se rompio
        self.assertEqual(report.ai_blocked, report.candidates)
        conn = store.connect(self.db, readonly=True)
        errs = conn.execute(
            "SELECT COUNT(*) FROM ai_assessment WHERE error IS NOT NULL").fetchone()[0]
        self.assertEqual(errs, report.candidates)
        conn.close()

    def test_is_offer_invalido_no_rompe_la_corrida(self):
        """Regresion P0.1: veredicto textual -> oferta sin clasificar positiva y corrida intacta."""
        contenido = GOOD_JSON.replace('"is_offer": true', '"is_offer": "false"')

        def http_veredicto_textual(url, headers=None, payload=None, timeout=30):
            return {"choices": [{"message": {"content": contenido}}],
                    "usage": {"total_tokens": 90}}

        self.ai_store.set_api_key("groq", "gsk_test_123456")
        self.ai_store.update_provider_settings("groq", {"allow_unverified_cost": True})
        self.ai_store.update_routing(primary={"provider": "groq", "model": "x"})
        report = pipeline.run(
            db_path=self.db,
            fixture_dir=BASE_DIR / "tests" / "fixtures",
            quiet=True,
            use_ai=True,
            ai_store=self.ai_store,
            ai_http_post=http_veredicto_textual,
        )
        self.assertGreater(report.candidates, 0)      # el motor NO se interrumpio
        self.assertEqual(report.ai_classified, 0)
        self.assertEqual(report.ai_blocked, report.candidates)

        conn = store.connect(self.db, readonly=True)
        positivas = conn.execute(
            "SELECT COUNT(*) FROM ai_assessment WHERE is_offer = 1").fetchone()[0]
        sin_error = conn.execute(
            "SELECT COUNT(*) FROM ai_assessment WHERE error IS NULL").fetchone()[0]
        n_offers = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
        n_evidence = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        conn.close()
        self.assertEqual(positivas, 0)
        self.assertEqual(sin_error, 0)
        self.assertGreater(n_offers, 0)               # la evidencia determinista se conserva
        self.assertGreater(n_evidence, 0)

    def test_web_views_expose_assessment(self):
        """La interfaz muestra la interpretacion IA marcada como NO oficial."""
        self._run_pipeline(use_ai=True)
        from ach import web
        from io import BytesIO

        web.Handler.db_path = self.db

        class FakeSocket:
            def __init__(self):
                self.data = BytesIO()

            def sendall(self, b):
                self.data.write(b)

            def makefile(self, mode, *a, **kw):
                return BytesIO()

        def render(path):
            handler = web.Handler.__new__(web.Handler)
            handler.path = path
            handler.headers = {}
            handler.rfile = BytesIO()
            out = BytesIO()
            handler.wfile = out
            handler.send_response = lambda code: None
            handler.send_header = lambda *a, **kw: None
            handler.end_headers = lambda: None
            handler.do_GET()
            return out.getvalue().decode("utf-8", errors="replace")

        index = render("/")
        self.assertIn("IA", index)  # columna/badge de interpretacion IA
        conn = store.connect(self.db, readonly=True)
        oid = conn.execute("SELECT offer_id FROM offer LIMIT 1").fetchone()[0]
        conn.close()
        detail = render(f"/oferta/{oid}")
        self.assertIn("NO es una verificaci", detail)
        self.assertIn("demo_local", detail)

    def test_web_panel_routes(self):
        """El panel /configuracion/ia y la API /api/ai/* responden en el MISMO servidor."""
        from ach import web, web_ai
        web_ai.reset_store_for_tests(self.ai_store)

        status, payload = web_ai.api_get("/api/ai/config")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("providers", payload["config"])
        self.assertNotIn("api_key", json.dumps(payload))

        status, payload = web_ai.api_put("/api/ai/routing", {
            "primary": {"provider": "demo_local", "model": "demo-clasificador-1"}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["routing"]["primary"]["provider"], "demo_local")

        html = web_ai.panel_html()
        self.assertIn("Windows Credential Manager", html)
        self.assertIn("costo", html.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
