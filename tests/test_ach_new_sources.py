"""Pruebas P1.1: fuentes oficiales nuevas (Groq, Stability AI, Cohere).

Sin red, con fixtures capturados de las paginas oficiales y bases SQLite
temporales. Verifica evidencia literal, cantidades publicadas, clasificacion
segun la taxonomia vigente, guardas de extraccion y ausencia de duplicados.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ach import classify, extract, sources, store, web
from ach.fetch import FetchResult, utcnow

FIX = Path(__file__).parent / "fixtures"
EXT = {"json": ".json", "html": ".html", "rss": ".xml"}
NUEVAS = ["groq-free-plan", "stability-welcome-credits", "cohere-trial-key"]
EXISTENTES = ["openrouter-free-models", "deepseek-pricing",
              "cloudflare-workers-ai-pricing", "kiro-pricing",
              "vercel-ai-gateway-pricing"]


def load(sid: str, raw: str | None = None) -> FetchResult:
    src = sources.BY_ID[sid]
    texto = raw if raw is not None else (FIX / f"{sid}{EXT[src.kind]}").read_text(
        encoding="utf-8", errors="replace")
    return FetchResult(url=src.url, status=200, text=texto, sha256="fixture",
                       fetched_at_utc=utcnow(), bytes_read=len(texto))


def extraer(sid: str, raw: str | None = None):
    return extract.extract(sources.BY_ID[sid], load(sid, raw))


class CatalogoTestCase(unittest.TestCase):
    def test_once_fuentes_operativas(self):
        self.assertEqual(len(sources.SOURCES), 11)
        self.assertEqual(len(sources.enabled_sources()), 11)
        for sid in NUEVAS:
            self.assertIn(sid, sources.BY_ID)

    def test_proveedores_nuevos_confirmados(self):
        for key, dominio in [("groq", "console.groq.com"),
                             ("stability", "platform.stability.ai"),
                             ("cohere", "docs.cohere.com")]:
            with self.subTest(proveedor=key):
                p = sources.PROVIDERS[key]
                self.assertEqual(p["identity_status"], "CONFIRMED")
                self.assertIn(dominio, p["official_domains"])

    def test_urls_oficiales_y_extractores_registrados(self):
        esperado = {
            "groq-free-plan": ("https://console.groq.com/docs/rate-limits", "groq_free_plan"),
            "stability-welcome-credits": ("https://platform.stability.ai/pricing",
                                          "stability_welcome_credits"),
            "cohere-trial-key": ("https://docs.cohere.com/docs/rate-limits", "cohere_trial_key"),
        }
        for sid, (url, ext) in esperado.items():
            with self.subTest(fuente=sid):
                src = sources.BY_ID[sid]
                self.assertEqual(src.url, url)
                self.assertEqual(src.extractor, ext)
                self.assertIn(ext, extract.EXTRACTORS)
                self.assertTrue(src.terms_url.startswith("https://"))


class GroqTestCase(unittest.TestCase):
    def setUp(self):
        self.c = extraer("groq-free-plan")

    def test_un_candidato_por_modelo_del_plan_free(self):
        self.assertEqual(len(self.c), 10)
        self.assertEqual(len({x.dedupe_key() for x in self.c}), 10)
        self.assertIn("GroqCloud (openai/gpt-oss-120b)", {x.product for x in self.c})
        self.assertIn("GroqCloud (whisper-large-v3)", {x.product for x in self.c})

    def test_cuotas_exactas_publicadas(self):
        por_modelo = {x.product: x for x in self.c}
        gpt = por_modelo["GroqCloud (openai/gpt-oss-120b)"]
        self.assertIn("RPM=30", gpt.benefit)
        self.assertIn("RPD=1K", gpt.benefit)
        self.assertIn("TPM=8K", gpt.benefit)
        self.assertIn("TPD=200K", gpt.benefit)
        whisper = por_modelo["GroqCloud (whisper-large-v3)"]
        self.assertIn("ASH=7.2K", whisper.benefit)
        self.assertIn("ASD=28.8K", whisper.benefit)

    def test_solo_free_rows_no_mezcla_plan_developer(self):
        """La extraccion depende de freeRows; devRows (Developer) no se usa."""
        raw = (FIX / "groq-free-plan.html").read_text(encoding="utf-8", errors="replace")
        self.assertIn("devRows", raw)
        sin_free = raw.replace("freeRows", "otrasRows")
        self.assertEqual(extraer("groq-free-plan", sin_free), [])
        for c in self.c:
            self.assertIn("no se mezclan", c.notes)

    def test_clasificacion_plan_gratuito_sin_porcentaje(self):
        for c in self.c:
            classify.assess(c, 200, fixture=True)
            self.assertEqual(classify.benefit_kind(c), "PLAN_GRATUITO")
            self.assertEqual(classify.band_of(c), "PLAN_GRATUITO")
            self.assertIsNone(c.discount_pct)
            self.assertIsNone(c.price_baseline)
            self.assertEqual(c.price_offer, 0.0)

    def test_evidencia_literal_con_modelo_y_cuotas(self):
        for c in self.c:
            modelo = c.product[len("GroqCloud ("):-1]
            self.assertTrue(c.evidence_snippet)
            self.assertIn(modelo, c.evidence_snippet)
            self.assertEqual(c.official_url, sources.BY_ID["groq-free-plan"].url)
            self.assertEqual(c.evidence_url, c.official_url)

    def test_condiciones_no_confirmadas_declaradas(self):
        for c in self.c:
            self.assertEqual(c.card_required, "unknown")
            self.assertEqual(c.argentina_status, "ARGENTINA_NO_CONFIRMADA")
            self.assertIn("No confirmado", c.notes)

    def test_pagina_sin_la_seccion_free_no_produce_nada(self):
        raw = (FIX / "groq-free-plan.html").read_text(encoding="utf-8", errors="replace")
        self.assertEqual(extraer("groq-free-plan", raw.replace("Free Plan Limits", "X")), [])


class StabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.c = extraer("stability-welcome-credits")

    def test_creditos_y_equivalencia_en_usd(self):
        self.assertEqual(len(self.c), 1)
        c = self.c[0]
        self.assertIn("25", c.title)
        self.assertIn("USD 0.25", c.title)          # 25 x 0.01, calculado de la pagina
        self.assertIn("Get started with 25 free credits", c.benefit)
        self.assertIn("USD 0.01", c.benefit)

    def test_clasificacion_credito_sin_porcentaje(self):
        c = classify.assess(self.c[0], 200, fixture=True)
        self.assertEqual(classify.benefit_kind(c), "CREDITO")
        self.assertEqual(classify.band_of(c), "CREDITO")
        self.assertIsNone(c.discount_pct)
        self.assertIsNone(c.price_baseline)
        self.assertIsNone(c.price_offer)

    def test_evidencia_y_condiciones(self):
        c = self.c[0]
        self.assertIn("free credits", c.evidence_snippet)
        self.assertEqual(c.card_required, "unknown")
        self.assertEqual(c.argentina_status, "ARGENTINA_NO_CONFIRMADA")
        self.assertIn("No confirmado", c.notes)
        self.assertIn("cuenta", c.eligibility.lower())

    def test_sin_declaracion_de_creditos_no_inventa(self):
        raw = (FIX / "stability-welcome-credits.html").read_text(
            encoding="utf-8", errors="replace")
        sin = raw.replace("Get started with", "Comienza con")
        self.assertEqual(extraer("stability-welcome-credits", sin), [])


class CohereTestCase(unittest.TestCase):
    def setUp(self):
        self.c = extraer("cohere-trial-key")

    def test_tope_mensual_publicado(self):
        self.assertEqual(len(self.c), 1)
        c = self.c[0]
        self.assertIn("1,000", c.title)
        self.assertIn("1,000 API calls a month", c.benefit)
        self.assertIn("evaluation keys (free but limited in usage)", c.benefit)

    def test_no_se_presenta_como_produccion_ilimitada(self):
        c = self.c[0]
        self.assertIn("no es acceso", c.notes.lower())
        self.assertIn("ilimitado", c.notes.lower())
        self.assertIn("produccion", c.eligibility.lower())
        self.assertIn("production", c.benefit)

    def test_clasificacion_prueba_gratuita(self):
        c = classify.assess(self.c[0], 200, fixture=True)
        self.assertEqual(classify.benefit_kind(c), "PRUEBA_GRATUITA")
        self.assertEqual(classify.band_of(c), "PRUEBA_GRATUITA")
        self.assertIsNone(c.discount_pct)
        self.assertIsNone(c.price_baseline)

    def test_sin_tope_mensual_no_inventa(self):
        raw = (FIX / "cohere-trial-key.html").read_text(encoding="utf-8", errors="replace")
        sin = raw.replace("API calls a month", "consultas mensuales")
        self.assertEqual(extraer("cohere-trial-key", sin), [])


class NoDuplicacionTestCase(unittest.TestCase):
    def test_claves_unicas_entre_todas_las_fuentes(self):
        claves = {}
        for sid in EXISTENTES + NUEVAS:
            for c in extraer(sid):
                k = c.dedupe_key()
                self.assertNotIn(k, claves, f"{sid} colisiona con {claves.get(k)}")
                claves[k] = sid
        self.assertGreater(len(claves), 25)

    def test_fuentes_existentes_conservan_su_extraccion(self):
        esperado = {"openrouter-free-models": 16, "deepseek-pricing": 6,
                    "cloudflare-workers-ai-pricing": 1, "kiro-pricing": 1,
                    "vercel-ai-gateway-pricing": 1}
        for sid, n in esperado.items():
            with self.subTest(fuente=sid):
                self.assertEqual(len(extraer(sid)), n)


class FuncionalTestCase(unittest.TestCase):
    """Corrida completa del cazador con las 11 fuentes, en modo fixtures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach_p11_")
        self.db = Path(self.tmp.name) / "p11.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        from ach import pipeline
        return pipeline.run(db_path=self.db, fixture_dir=FIX, quiet=True)

    def test_corrida_completa_con_fuentes_nuevas(self):
        rep = self._run()
        self.assertEqual(rep.errors, 0)
        self.assertGreater(rep.candidates, 25)
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            proveedores = {r[0] for r in conn.execute(
                "SELECT DISTINCT provider_key FROM offer")}
            self.assertTrue({"groq", "stability", "cohere"} <= proveedores, proveedores)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key='groq'").fetchone()[0], 10)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key='stability'").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key='cohere'").fetchone()[0], 1)
            # Ningun porcentaje artificial en las fuentes nuevas.
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key IN ('groq','stability','cohere') "
                "AND discount_pct IS NOT NULL").fetchone()[0], 0)
            bandas = {r[0] for r in conn.execute(
                "SELECT DISTINCT discount_band FROM offer "
                "WHERE provider_key IN ('groq','stability','cohere')")}
            self.assertEqual(bandas, {"PLAN_GRATUITO", "CREDITO", "PRUEBA_GRATUITA"})
            # Evidencia literal y trazabilidad para cada oferta nueva.
            filas = conn.execute(
                "SELECT o.official_url, e.snippet, e.http_status, e.content_sha256 "
                "FROM offer o JOIN evidence e ON e.offer_id=o.offer_id "
                "WHERE o.provider_key IN ('groq','stability','cohere')").fetchall()
            self.assertGreaterEqual(len(filas), 12)
            for f in filas:
                self.assertTrue(f["official_url"].startswith("https://"))
                self.assertTrue(f["snippet"])
                self.assertEqual(f["http_status"], 200)
                self.assertTrue(f["content_sha256"])
            self.assertEqual({r[0] for r in conn.execute(
                "SELECT DISTINCT verification_level FROM offer")}, {"FIXTURE"})
        finally:
            conn.close()

    def test_segunda_corrida_no_duplica(self):
        self._run()
        rep2 = self._run()
        self.assertEqual(rep2.offers_new, 0)
        self.assertGreater(rep2.offers_seen, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            distintos = conn.execute("SELECT COUNT(DISTINCT dedupe_key) FROM offer").fetchone()[0]
            self.assertEqual(total, distintos)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()

    def test_interfaz_muestra_nuevas_oportunidades_y_no_confirmado(self):
        self._run()
        web.Handler.db_path = self.db
        from io import BytesIO

        def render(path):
            h = web.Handler.__new__(web.Handler)
            h.path, h.headers, h.rfile = path, {}, BytesIO()
            out = BytesIO()
            h.wfile = out
            h.send_response = lambda code: None
            h.send_header = lambda *a, **kw: None
            h.end_headers = lambda: None
            h.do_GET()
            return out.getvalue().decode("utf-8", errors="replace")

        index = render("/")
        self.assertIn("GroqCloud", index)
        self.assertIn("Stability AI", index)
        self.assertIn("Cohere", index)
        self.assertIn("Plan gratuito", index)
        self.assertIn("Prueba gratuita", index)

        conn = store.connect(self.db, readonly=True)
        oid = conn.execute(
            "SELECT offer_id FROM offer WHERE provider_key='cohere'").fetchone()[0]
        conn.close()
        detalle = render(f"/oferta/{oid}")
        self.assertIn("No confirmado", detalle)
        self.assertIn("1,000", detalle)
        self.assertNotIn("GRATIS_100", detalle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
