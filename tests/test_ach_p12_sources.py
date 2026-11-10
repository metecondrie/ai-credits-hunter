"""Pruebas P1.2: ocho fuentes oficiales nuevas.

Sin red, con fixtures capturados de las paginas oficiales el 2026-11-10 y bases
SQLite temporales. Cubre evidencia literal, importes publicados, clasificacion,
condiciones de tarjeta/elegibilidad, guardas y deduplicacion.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ach import classify, extract, sources, store
from ach.fetch import FetchResult, utcnow

FIX = Path(__file__).parent / "fixtures"
NUEVAS = {
    "alibaba-model-studio-free-quota": ("PRUEBA_GRATUITA", "alibaba"),
    "cerebras-promo-credit": ("CREDITO", "cerebras"),
    "modal-free-credits": ("CREDITO", "modal"),
    "azure-for-students": ("BENEFICIO_ESTUDIANTIL", "azure"),
    "gcp-free-trial": ("CREDITO", "google"),
    "aws-educate": ("BENEFICIO_ESTUDIANTIL", "aws"),
    "azure-free-account": ("CREDITO", "azure"),
    "fireworks-free-model": ("PRUEBA_GRATUITA", "fireworks"),
}


def raw(sid: str) -> str:
    return (FIX / f"{sid}.html").read_text(encoding="utf-8", errors="replace")


def extraer(sid: str, texto: str | None = None):
    src = sources.BY_ID[sid]
    t = raw(sid) if texto is None else texto
    return extract.extract(src, FetchResult(url=src.url, status=200, text=t,
                                            sha256="fixture", fetched_at_utc=utcnow(),
                                            bytes_read=len(t)))


class CatalogoP12TestCase(unittest.TestCase):
    def test_catalogo_tras_p13(self):
        # P1.3 corrigio el emparejamiento de comodines de robots.txt, reactivo
        # Alibaba y AWS Educate, y sumo GitHub Pack, AWS Activate y Google Skills.
        self.assertEqual(len(sources.SOURCES), 22)
        self.assertEqual(len(sources.enabled_sources()), 22)
        for sid in ("alibaba-model-studio-free-quota", "aws-educate"):
            self.assertTrue(sources.BY_ID[sid].enabled)
            self.assertIn("Reactivada en P1.3", sources.BY_ID[sid].notes)

    def test_fuentes_nuevas_registradas_con_url_oficial(self):
        for sid, (kind, provider) in NUEVAS.items():
            with self.subTest(fuente=sid):
                src = sources.BY_ID[sid]
                self.assertTrue(src.url.startswith("https://"))
                self.assertIn(src.official_domain, src.url)
                self.assertIn(src.extractor, extract.EXTRACTORS)
                self.assertEqual(src.provider_key, provider)
                self.assertEqual(sources.PROVIDERS[provider]["identity_status"], "CONFIRMED")
                self.assertIn(kind, classify.BENEFIT_KINDS)
                self.assertIn(kind, classify.KIND_LABELS)

    def test_inventario_canonico_versionado(self):
        doc = (BASE_DIR / "docs" / "fuentes_pendientes.md").read_text(encoding="utf-8")
        for estado in ("PENDIENTE", "VALIDADA", "INTEGRADA", "BLOQUEADA", "DESCARTADA"):
            self.assertIn(estado, doc)
        self.assertIn("**23**", doc)
        # Las fuentes no implementadas se conservan, no se eliminan.
        for nombre in ("Gemini", "SambaNova", "NVIDIA", "OpenAI API", "Together",
                       "GitHub Student Developer Pack", "AWS Activate",
                       "Google Cloud para estudiantes"):
            self.assertIn(nombre, doc)


class BeneficiosP12TestCase(unittest.TestCase):
    def test_un_candidato_por_fuente_y_clasificacion_correcta(self):
        for sid, (kind, _) in NUEVAS.items():
            with self.subTest(fuente=sid):
                cs = extraer(sid)
                self.assertEqual(len(cs), 1)
                c = classify.assess(cs[0], 200, fixture=True)
                self.assertEqual(classify.benefit_kind(c), kind)
                self.assertEqual(classify.band_of(c), kind)
                self.assertIsNone(c.discount_pct)          # nunca 100% artificial
                self.assertIsNone(c.price_baseline)
                self.assertEqual(c.argentina_status, "ARGENTINA_NO_CONFIRMADA")

    def test_importes_y_plazos_publicados(self):
        casos = [
            ("alibaba-model-studio-free-quota", "90 dias"),
            ("cerebras-promo-credit", "USD 5"),
            ("cerebras-promo-credit", "30 dias"),
            ("modal-free-credits", "USD 30"),
            ("azure-for-students", "USD 100"),
            ("azure-for-students", "12 meses"),
            ("gcp-free-trial", "USD 300"),
            ("gcp-free-trial", "90 dias"),
            ("aws-educate", "13 anos"),
            ("azure-free-account", "USD 200"),
            ("azure-free-account", "30 dias"),
            ("fireworks-free-model", "November 30"),
        ]
        for sid, fragmento in casos:
            with self.subTest(fuente=sid, dato=fragmento):
                c = extraer(sid)[0]
                self.assertIn(fragmento, f"{c.title} {c.benefit}")

    def test_evidencia_literal_y_trazabilidad(self):
        for sid in NUEVAS:
            with self.subTest(fuente=sid):
                c = extraer(sid)[0]
                self.assertTrue(c.evidence_snippet)
                self.assertEqual(c.official_url, sources.BY_ID[sid].url)
                self.assertEqual(c.evidence_url, c.official_url)
                self.assertTrue(c.extraction_rule)
                self.assertTrue(c.terms_url.startswith("https://"))

    def test_condiciones_de_tarjeta_segun_lo_publicado(self):
        published_yes = ["cerebras-promo-credit", "gcp-free-trial", "azure-free-account"]
        published_no = ["azure-for-students", "aws-educate", "fireworks-free-model"]
        for sid in published_yes:
            with self.subTest(fuente=sid):
                self.assertEqual(extraer(sid)[0].card_required, "yes")
        for sid in published_no:
            with self.subTest(fuente=sid):
                self.assertEqual(extraer(sid)[0].card_required, "no")
        for sid in ("alibaba-model-studio-free-quota", "modal-free-credits"):
            with self.subTest(fuente=sid):
                self.assertEqual(extraer(sid)[0].card_required, "unknown")
                self.assertIn("No confirmado", extraer(sid)[0].notes)

    def test_beneficios_estudiantiles_marcan_elegibilidad(self):
        for sid in ("azure-for-students", "aws-educate"):
            with self.subTest(fuente=sid):
                c = extraer(sid)[0]
                self.assertEqual(c.student_required, "yes")
                self.assertEqual(c.offer_type, "STUDENT")
        self.assertIn("18", extraer("azure-for-students")[0].eligibility)
        self.assertIn("acreditada", extraer("azure-for-students")[0].eligibility)

    def test_alibaba_advierte_riesgo_de_cargo_y_proteccion(self):
        c = extraer("alibaba-model-studio-free-quota")[0]
        self.assertIn("Free Quota Only", c.notes)
        self.assertIn("DESACTIVADO", c.notes)
        self.assertIn("RIESGO DE CARGO", c.notes)
        self.assertIn("pay-as-you-go", c.benefit)

    def test_alibaba_sin_advertencia_de_cargo_no_publica(self):
        """Guarda: si la pagina oculta el riesgo, no se publica el beneficio."""
        t = raw("alibaba-model-studio-free-quota").replace(
            "you are automatically billed on a pay-as-you-go basis", "se factura de otro modo")
        self.assertEqual(extraer("alibaba-model-studio-free-quota", t), [])

    def test_aws_educate_no_inventa_creditos_de_ia(self):
        c = extraer("aws-educate")[0]
        self.assertIn("NO creditos para APIs de IA", c.notes)
        self.assertIn("laboratorios", c.benefit.lower())

    def test_fireworks_no_inventa_el_anio_de_vencimiento(self):
        c = extraer("fireworks-free-model")[0]
        self.assertIsNone(c.expires_at)
        self.assertIn("no explicita el ano", c.notes)
        self.assertIn("November 30", c.title)

    def test_azure_free_y_azure_students_no_se_confunden(self):
        a = extraer("azure-free-account")[0]
        s = extraer("azure-for-students")[0]
        self.assertNotEqual(a.dedupe_key(), s.dedupe_key())
        self.assertNotEqual(a.product, s.product)
        self.assertIn("USD 200", a.title)
        self.assertIn("USD 100", s.title)
        self.assertEqual(s.student_required, "yes")
        self.assertEqual(a.student_required, "no")

    def test_modal_distingue_credito_de_descuento(self):
        c = extraer("modal-free-credits")[0]
        self.assertIn("no un descuento", c.notes)
        self.assertIn("facturables", c.notes)

    def test_cerebras_no_es_para_produccion(self):
        c = extraer("cerebras-promo-credit")[0]
        self.assertIn("produccion", c.benefit)
        self.assertIn("metodo de pago", c.eligibility)


class GuardasP12TestCase(unittest.TestCase):
    def test_sin_el_patron_no_se_inventa(self):
        mutaciones = {
            "alibaba-model-studio-free-quota": ("The free quota is valid for", "La cuota dura"),
            "cerebras-promo-credit": ("promotional credit", "bono"),
            "modal-free-credits": ("month free credits", "mes de creditos"),
            "azure-for-students": ("Azure for Students gets you started with", "Azure empieza con"),
            "gcp-free-trial": ("in free Welcome credit", "en credito"),
            "aws-educate": ("No credit card needed", "Se pide tarjeta"),
            "azure-free-account": ("Get free services and a", "Obtiene servicios y un"),
            "fireworks-free-model": ("is free through", "es gratuito hasta"),
        }
        for sid, (viejo, nuevo) in mutaciones.items():
            with self.subTest(fuente=sid):
                t = raw(sid)
                self.assertIn(viejo, t)
                self.assertEqual(extraer(sid, t.replace(viejo, nuevo)), [])

    def test_html_vacio_devuelve_cero(self):
        for sid in NUEVAS:
            with self.subTest(fuente=sid):
                self.assertEqual(extraer(sid, "<html></html>"), [])

    def test_claves_unicas_entre_las_diecinueve_fuentes(self):
        previas = ["openrouter-free-models", "deepseek-pricing",
                   "cloudflare-workers-ai-pricing", "kiro-pricing",
                   "vercel-ai-gateway-pricing", "groq-free-plan",
                   "stability-welcome-credits", "cohere-trial-key"]
        ext = {"json": ".json", "html": ".html", "rss": ".xml"}
        vistas = {}
        for sid in previas + list(NUEVAS):
            src = sources.BY_ID[sid]
            t = (FIX / f"{sid}{ext[src.kind]}").read_text(encoding="utf-8", errors="replace")
            for c in extract.extract(src, FetchResult(url=src.url, status=200, text=t,
                                                      sha256="f", fetched_at_utc=utcnow(),
                                                      bytes_read=len(t))):
                k = c.dedupe_key()
                self.assertNotIn(k, vistas, f"{sid} colisiona con {vistas.get(k)}")
                vistas[k] = sid
        self.assertGreater(len(vistas), 40)


class FuncionalP12TestCase(unittest.TestCase):
    """Comprobacion funcional breve: pipeline completo en modo fixtures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach_p12_")
        self.db = Path(self.tmp.name) / "p12.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrida_funcional_de_las_ocho_fuentes_nuevas(self):
        from ach import pipeline
        # ids explicitos: ejercita tambien las dos deshabilitadas por robots,
        # cuyo extractor y fixture siguen siendo validos.
        rep = pipeline.run(db_path=self.db, source_ids=list(NUEVAS),
                           fixture_dir=FIX, quiet=True)
        self.assertEqual(rep.errors, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            nuevos = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key IN "
                "('alibaba','cerebras','modal','azure','aws','fireworks') "
                "OR (provider_key='google' AND source_id='gcp-free-trial')").fetchone()[0]
            self.assertEqual(nuevos, 8)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key IN "
                "('alibaba','cerebras','modal','azure','aws','fireworks') "
                "AND discount_pct IS NOT NULL").fetchone()[0], 0)
            bandas = {r[0] for r in conn.execute(
                "SELECT DISTINCT discount_band FROM offer WHERE source_id IN "
                "('azure-for-students','aws-educate')")}
            self.assertEqual(bandas, {"BENEFICIO_ESTUDIANTIL"})
            ev = conn.execute(
                "SELECT COUNT(*) FROM evidence e JOIN offer o ON o.offer_id=e.offer_id "
                "WHERE o.source_id IN ({}) AND e.snippet != '' "
                "AND e.http_status=200".format(",".join("?" * len(NUEVAS))),
                tuple(NUEVAS)).fetchone()[0]
            self.assertEqual(ev, 8)
        finally:
            conn.close()

        rep2 = pipeline.run(db_path=self.db, source_ids=list(NUEVAS),
                            fixture_dir=FIX, quiet=True)
        self.assertEqual(rep2.offers_new, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            self.assertEqual(total, conn.execute(
                "SELECT COUNT(DISTINCT dedupe_key) FROM offer").fetchone()[0])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
