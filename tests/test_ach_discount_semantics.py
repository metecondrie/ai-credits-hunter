"""Regresion P0.3: descuentos enganosos vs gratuidad real.

Sin red, sin APIs y con bases SQLite temporales. Cubre la taxonomia de
beneficios, la guarda central de comparabilidad de precios, la preservacion de
DeepSeek (P0.2), la ausencia de duplicados, la evidencia original intacta y las
etiquetas de la interfaz.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ach import classify, extract, report, sources, store, web
from ach.fetch import FetchResult, utcnow
from ach.models import Candidate

FIX = Path(__file__).parent / "fixtures"
EXT = {"json": ".json", "html": ".html", "rss": ".xml"}
PRICING = ["openrouter-free-models", "deepseek-pricing",
           "cloudflare-workers-ai-pricing", "kiro-pricing",
           "vercel-ai-gateway-pricing"]


def load(source_id: str) -> FetchResult:
    src = sources.BY_ID[source_id]
    raw = (FIX / f"{source_id}{EXT[src.kind]}").read_text(encoding="utf-8")
    return FetchResult(url=src.url, status=200, text=raw, sha256="fixture",
                       fetched_at_utc=utcnow(), bytes_read=len(raw))


def candidate(**kw) -> Candidate:
    base = dict(
        source_id="s", provider_key="p", product="Producto", title="T",
        offer_type="DISCOUNT", benefit="B", official_url="https://example.com/",
        evidence_url="https://example.com/", evidence_snippet="fragmento literal",
        extraction_rule="regla",
    )
    base.update(kw)
    return Candidate(**base)


class TaxonomiaTestCase(unittest.TestCase):
    def test_cada_clase_gratuita_tiene_banda_propia_sin_porcentaje(self):
        esperadas = {
            "PLAN_GRATUITO": "PLAN_GRATUITO",
            "CUOTA_GRATUITA": "CUOTA_GRATUITA",
            "CREDITO": "CREDITO",
            "PRUEBA_GRATUITA": "PRUEBA_GRATUITA",
            "MODELO_GRATUITO": "MODELO_GRATUITO",
        }
        for kind, banda in esperadas.items():
            with self.subTest(kind=kind):
                c = candidate(benefit_kind=kind, price_offer=0.0)
                self.assertIsNone(c.discount_pct)
                self.assertEqual(classify.band_of(c), banda)
                self.assertIn(kind, classify.BENEFIT_KINDS)

    def test_descuento_real_conserva_banda_porcentual(self):
        c = candidate(benefit_kind="DESCUENTO", price_baseline=100.0,
                      price_offer=40.0, price_unit="USD / mes", currency="USD",
                      discount_pct=60.0)
        self.assertTrue(classify.precios_comparables(c))
        self.assertEqual(classify.band_of(c), "DESCUENTO_50_69")

    def test_tarifa_horaria_conserva_banda_porcentual(self):
        c = candidate(offer_type="OFF_PEAK_DISCOUNT", benefit_kind="TARIFA_HORARIA",
                      price_baseline=0.006, price_offer=0.003,
                      price_unit="USD / 1M tokens (salida)", currency="USD",
                      discount_pct=50.0)
        self.assertTrue(classify.precios_comparables(c))
        self.assertEqual(classify.band_of(c), "DESCUENTO_50_69")

    def test_cien_por_ciento_solo_con_base_comparable(self):
        legitimo = candidate(benefit_kind="DESCUENTO", price_baseline=20.0,
                             price_offer=0.0, price_unit="USD / mes",
                             currency="USD", discount_pct=100.0)
        self.assertEqual(classify.band_of(legitimo), "GRATIS_100")
        plan_free = candidate(benefit_kind="PLAN_GRATUITO", price_baseline=20.0,
                              price_offer=0.0, price_unit="USD / mes",
                              currency="USD", discount_pct=100.0)
        self.assertNotEqual(classify.band_of(plan_free), "GRATIS_100")

    def test_sin_clase_ni_base_devuelve_sin_base_verificada(self):
        c = candidate(offer_type="ANUNCIO", benefit_kind="")
        self.assertEqual(classify.band_of(c), "SIN_BASE_VERIFICADA")

    def test_clase_se_infiere_del_tipo_si_no_fue_declarada(self):
        casos = {"FREE_TIER": "PLAN_GRATUITO", "FREE_MODEL": "MODELO_GRATUITO",
                 "CREDITS": "CREDITO", "TRIAL": "PRUEBA_GRATUITA",
                 "OFF_PEAK_DISCOUNT": "TARIFA_HORARIA"}
        for tipo, kind in casos.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(classify.benefit_kind(candidate(offer_type=tipo)), kind)


class ComparabilidadTestCase(unittest.TestCase):
    """Un porcentaje exige mismo producto, modalidad, unidad y periodo."""

    def comparabile(self, **kw):
        args = dict(benefit_kind="TARIFA_HORARIA", price_baseline=10.0,
                    price_offer=5.0, price_unit="USD / 1M tokens", currency="USD")
        args.update(kw)
        return candidate(**args)

    def test_requisitos_de_comparabilidad(self):
        self.assertTrue(classify.precios_comparables(self.comparabile()))
        invalidos = [
            {"price_baseline": None}, {"price_baseline": 0.0},
            {"price_baseline": -1.0}, {"price_offer": None},
            {"price_unit": ""}, {"price_unit": None}, {"currency": ""},
            {"benefit_kind": "PLAN_GRATUITO"}, {"benefit_kind": "CUOTA_GRATUITA"},
            {"benefit_kind": "CREDITO"}, {"benefit_kind": "MODELO_GRATUITO"},
            # Sin clase declarada ni tipo del que inferirla: no hay comparacion.
            {"benefit_kind": "", "offer_type": "ANUNCIO"},
        ]
        for kw in invalidos:
            with self.subTest(**kw):
                self.assertFalse(classify.precios_comparables(self.comparabile(**kw)))

    def test_assess_descarta_porcentaje_sin_precios_comparables(self):
        """Guarda central: ningun extractor puede fabricar un porcentaje."""
        c = candidate(benefit_kind="PLAN_GRATUITO", price_baseline=20.0,
                      price_offer=0.0, price_unit="USD / mes", currency="USD",
                      discount_pct=100.0)
        classify.assess(c, 200, fixture=True)
        self.assertIsNone(c.discount_pct)
        self.assertIn("porcentaje descartado", c.notes)
        self.assertEqual(classify.band_of(c), "PLAN_GRATUITO")

    def test_assess_descarta_porcentaje_sin_unidad_ni_moneda(self):
        c = candidate(benefit_kind="DESCUENTO", price_baseline=20.0,
                      price_offer=0.0, price_unit="", currency="",
                      discount_pct=100.0)
        classify.assess(c, 200, fixture=True)
        self.assertIsNone(c.discount_pct)
        self.assertEqual(classify.band_of(c), "SIN_BASE_VERIFICADA")

    def test_assess_conserva_porcentaje_legitimo(self):
        c = candidate(benefit_kind="TARIFA_HORARIA", price_baseline=0.006,
                      price_offer=0.003, price_unit="USD / 1M tokens",
                      currency="USD", discount_pct=50.0)
        classify.assess(c, 200, fixture=True)
        self.assertAlmostEqual(c.discount_pct, 50.0)
        self.assertNotIn("porcentaje descartado", c.notes)


class FuentesTestCase(unittest.TestCase):
    """Las cuatro fuentes con gratuidad y la tarifa horaria de DeepSeek."""

    def test_gratuidad_sin_porcentaje_en_las_cuatro_fuentes(self):
        esperado = {
            "openrouter-free-models": "MODELO_GRATUITO",
            "cloudflare-workers-ai-pricing": "CUOTA_GRATUITA",
            "kiro-pricing": "PLAN_GRATUITO",
            "vercel-ai-gateway-pricing": "CREDITO",
        }
        for sid, kind in esperado.items():
            with self.subTest(fuente=sid):
                cs = extract.extract(sources.BY_ID[sid], load(sid))
                self.assertGreater(len(cs), 0)
                for c in cs:
                    classify.assess(c, 200, fixture=True)
                    self.assertIsNone(c.discount_pct)
                    self.assertIsNone(c.price_baseline)
                    self.assertEqual(classify.benefit_kind(c), kind)
                    self.assertEqual(classify.band_of(c), kind)
                    self.assertTrue(c.evidence_snippet)

    def test_deepseek_p02_intacto(self):
        cs = extract.extract(sources.BY_ID["deepseek-pricing"], load("deepseek-pricing"))
        self.assertEqual(len(cs), 6)
        for c in cs:
            classify.assess(c, 200, fixture=True)
            self.assertAlmostEqual(c.discount_pct, 50.0, places=2)
            self.assertEqual(classify.band_of(c), "DESCUENTO_50_69")
            self.assertEqual(classify.benefit_kind(c), "TARIFA_HORARIA")
            self.assertAlmostEqual(
                c.discount_pct, round(100 * (1 - c.price_offer / c.price_baseline), 2))

    def test_componentes_de_dedupe_inalterados(self):
        """Cambiar la semantica no debe crear ofertas duplicadas.

        dedupe_key() se arma con provider, product, offer_type, price_unit y
        dedupe_extra. Estos son los valores previos al P0.3: deben seguir igual.
        """
        legacy = {
            "cloudflare-workers-ai-pricing": ("cloudflare", "Workers AI", "FREE_TIER",
                                              "USD / 1000 Neurons",
                                              "cloudflare-workers-ai-pricing"),
            "kiro-pricing": ("kiro", "Kiro IDE / CLI", "FREE_TIER", "USD / mes",
                             "kiro-pricing"),
            "vercel-ai-gateway-pricing": ("vercel", "Vercel AI Gateway", "CREDITS",
                                        "USD / mes", "vercel-ai-gateway-pricing"),
        }
        for sid, valores in legacy.items():
            with self.subTest(fuente=sid):
                c = extract.extract(sources.BY_ID[sid], load(sid))[0]
                self.assertEqual(
                    (c.provider_key, c.product, c.offer_type, c.price_unit, c.dedupe_extra),
                    valores)

    def test_datos_publicados_conservados_como_texto(self):
        """Quitar el porcentaje no borra el dato oficial: sigue en la evidencia."""
        cloudflare = extract.extract(sources.BY_ID["cloudflare-workers-ai-pricing"],
                                     load("cloudflare-workers-ai-pricing"))[0]
        self.assertIn("10,000", cloudflare.benefit)
        self.assertIn("0.011", cloudflare.benefit)
        kiro = extract.extract(sources.BY_ID["kiro-pricing"], load("kiro-pricing"))[0]
        self.assertIn("20", kiro.benefit)
        vercel = extract.extract(sources.BY_ID["vercel-ai-gateway-pricing"],
                                 load("vercel-ai-gateway-pricing"))[0]
        self.assertIn("5", vercel.title)


class PersistenciaTestCase(unittest.TestCase):
    """Pipeline con fixtures, base temporal, sin duplicados ni evidencia alterada."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach_p03_")
        self.db = Path(self.tmp.name) / "p03.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        from ach import pipeline
        return pipeline.run(db_path=self.db, source_ids=PRICING,
                            fixture_dir=FIX, quiet=True)

    def test_bandas_gratuitas_persistidas_sin_porcentaje(self):
        rep = self._run()
        self.assertEqual(rep.errors, 0)
        self.assertGreater(rep.candidates, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            artificiales = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE discount_pct IS NOT NULL "
                "AND discount_band NOT LIKE 'DESCUENTO_%' "
                "AND discount_band != 'GRATIS_100'").fetchone()[0]
            self.assertEqual(artificiales, 0)
            gratis100 = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE discount_band='GRATIS_100'").fetchone()[0]
            self.assertEqual(gratis100, 0)
            bandas = {r[0] for r in conn.execute("SELECT DISTINCT discount_band FROM offer")}
            self.assertTrue({"MODELO_GRATUITO", "CUOTA_GRATUITA", "PLAN_GRATUITO",
                             "CREDITO", "DESCUENTO_50_69"} <= bandas, bandas)
            deepseek = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key='deepseek' "
                "AND discount_pct=50.0").fetchone()[0]
            self.assertEqual(deepseek, 6)
            # Un fixture nunca es verificacion real.
            niveles = {r[0] for r in conn.execute("SELECT DISTINCT verification_level FROM offer")}
            self.assertEqual(niveles, {"FIXTURE"})
        finally:
            conn.close()

    def test_segunda_corrida_no_duplica_ni_altera_evidencia(self):
        self._run()
        conn = store.connect(self.db, readonly=True)
        try:
            antes = {r["dedupe_key"]: r["offer_id"]
                     for r in conn.execute("SELECT dedupe_key, offer_id FROM offer")}
            ev_antes = {r["offer_id"]: (r["snippet"], r["content_sha256"])
                        for r in conn.execute(
                            "SELECT offer_id, snippet, content_sha256 FROM evidence "
                            "ORDER BY evidence_id")}
        finally:
            conn.close()

        rep2 = self._run()
        self.assertEqual(rep2.offers_new, 0)
        self.assertGreater(rep2.offers_seen, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            despues = {r["dedupe_key"]: r["offer_id"]
                       for r in conn.execute("SELECT dedupe_key, offer_id FROM offer")}
            self.assertEqual(antes, despues)          # mismas ofertas, mismos ids
            total = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            distintos = conn.execute("SELECT COUNT(DISTINCT dedupe_key) FROM offer").fetchone()[0]
            self.assertEqual(total, distintos)
            self.assertEqual(total, len(antes))
            for r in conn.execute("SELECT offer_id, snippet, content_sha256 FROM evidence"):
                original = ev_antes.get(r["offer_id"])
                if original is not None:
                    self.assertEqual((r["snippet"], r["content_sha256"]), original)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()


class InterfazTestCase(unittest.TestCase):
    def test_badge_nombra_la_gratuidad_y_no_inventa_porcentaje(self):
        for banda, etiqueta in [("PLAN_GRATUITO", "Plan gratuito"),
                                ("CUOTA_GRATUITA", "Cuota incluida"),
                                ("CREDITO", "Credito"),
                                ("MODELO_GRATUITO", "Modelo gratuito"),
                                ("PRUEBA_GRATUITA", "Prueba gratuita")]:
            with self.subTest(banda=banda):
                html_out = web._badge({"discount_band": banda, "discount_pct": None})
                self.assertIn(etiqueta, html_out)
                self.assertNotIn("%", html_out)

    def test_badge_muestra_porcentaje_solo_si_es_real(self):
        out = web._badge({"discount_band": "DESCUENTO_50_69", "discount_pct": 50.0})
        self.assertIn("50%", out)

    def test_precio_no_sugiere_rebaja_sin_descuento_real(self):
        gratis = {"price_offer": 0.0, "price_baseline": 20.0,
                  "price_unit": "USD / mes", "discount_pct": None}
        self.assertNotIn("de 20", web._price(gratis))
        real = dict(gratis, discount_pct=50.0)
        self.assertIn("de 20", web._price(real))

    def test_reporte_y_cli_usan_la_etiqueta_de_clase(self):
        o = {"discount_pct": None, "discount_band": "CUOTA_GRATUITA"}
        self.assertEqual(report._fmt_disc(o), "Cuota incluida")
        self.assertEqual(classify.kind_label("PLAN_GRATUITO"), "Plan gratuito")

    def test_filtros_separan_gratuidad_de_descuento(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach_p03_ui_")
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "ui.sqlite3"
        from ach import pipeline
        pipeline.run(db_path=db, source_ids=PRICING, fixture_dir=FIX, quiet=True)
        web.Handler.db_path = db

        from io import BytesIO

        def render(path):
            h = web.Handler.__new__(web.Handler)
            h.path = path
            h.headers = {}
            h.rfile = BytesIO()
            out = BytesIO()
            h.wfile = out
            h.send_response = lambda code: None
            h.send_header = lambda *a, **kw: None
            h.end_headers = lambda: None
            h.do_GET()
            return out.getvalue().decode("utf-8", errors="replace")

        index = render("/")
        self.assertIn("Gratuidad (sin porcentaje)", index)
        self.assertIn("Descuento porcentual real", index)
        self.assertIn("Plan gratuito permanente", index)
        self.assertIn("Cuota gratuita incluida", index)
        self.assertNotIn("100% gratis", index)
        self.assertIn("Plan gratuito", index)
        self.assertIn("Cuota incluida", index)

        conn = store.connect(db, readonly=True)
        oid = conn.execute("SELECT offer_id FROM offer WHERE provider_key='kiro'").fetchone()[0]
        conn.close()
        detalle = render(f"/oferta/{oid}")
        self.assertIn("Beneficio", detalle)
        self.assertIn("Plan gratuito", detalle)
        self.assertNotIn("GRATIS_100", detalle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
