"""Pruebas de extraccion contra capturas reales guardadas en tests/fixtures/.

Los fixtures son respuestas HTTP reales de las fuentes oficiales, guardadas el
2026-11-09. No se editaron a mano.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ach import extract
from ach.fetch import FetchResult, utcnow
from ach.sources import BY_ID

FIX = Path(__file__).parent / "fixtures"
EXT = {"json": ".json", "html": ".html", "rss": ".xml"}


def load(source_id: str) -> FetchResult:
    src = BY_ID[source_id]
    raw = (FIX / f"{source_id}{EXT[src.kind]}").read_text(encoding="utf-8")
    return FetchResult(url=src.url, status=200, text=raw, sha256="fixture",
                       fetched_at_utc=utcnow(), bytes_read=len(raw))


class TestOpenRouter(unittest.TestCase):
    def setUp(self):
        self.src = BY_ID["openrouter-free-models"]
        self.c = extract.extract(self.src, load(self.src.id))

    def test_finds_free_models(self):
        self.assertGreaterEqual(len(self.c), 5)

    def test_all_zero_price_and_evidence(self):
        for c in self.c:
            self.assertEqual(c.price_offer, 0.0)
            self.assertIsNone(c.price_baseline)  # no se inventa precio de lista
            self.assertTrue(c.evidence_snippet)
            self.assertTrue(c.official_url.startswith("https://openrouter.ai/"))
            self.assertIn("prompt", c.evidence_snippet.lower())

    def test_keys_unique(self):
        keys = {c.dedupe_key() for c in self.c}
        self.assertEqual(len(keys), len(self.c))


class TestDeepSeek(unittest.TestCase):
    """Regresion P0.2: tabla oficial con una columna de precios por modelo.

    Valores contrastados contra https://api-docs.deepseek.com/quick_start/pricing/
    el 2026-11-10 (HTTP 200). El fixture deepseek-pricing.html es byte a byte
    idéntico a esa respuesta (sha256 af667969...ece5).
    """

    # (modelo, categoria, off-peak, peak) en USD por 1M tokens
    OFICIAL = [
        ("deepseek-flash", "entrada con cache hit", 0.003, 0.006),
        ("deepseek-v4-pro", "entrada con cache hit", 0.022, 0.044),
        ("deepseek-flash", "entrada con cache miss", 0.15, 0.3),
        ("deepseek-v4-pro", "entrada con cache miss", 0.66, 1.32),
        ("deepseek-flash", "salida", 0.6, 1.2),
        ("deepseek-v4-pro", "salida", 1.98, 3.96),
    ]

    def setUp(self):
        self.src = BY_ID["deepseek-pricing"]
        self.c = extract.extract(self.src, load(self.src.id))

    def test_source_url_requires_trailing_slash(self):
        """Sin barra final el host devuelve HTTP 200 con 'Your First API Call'."""
        self.assertTrue(self.src.url.endswith("/quick_start/pricing/"))

    def test_one_candidate_per_model_and_category(self):
        self.assertEqual(len(self.c), 6)
        units = " ".join(c.price_unit or "" for c in self.c)
        self.assertIn("cache hit", units)
        self.assertIn("cache miss", units)
        self.assertIn("salida", units)
        products = {c.product for c in self.c}
        self.assertEqual(products, {"DeepSeek API (deepseek-flash)",
                                    "DeepSeek API (deepseek-v4-pro)"})

    def test_prices_match_official_table(self):
        got = sorted((c.product, c.price_unit, c.price_offer, c.price_baseline)
                     for c in self.c)
        esperado = sorted(
            (f"DeepSeek API ({modelo})", f"USD / 1M tokens ({cat})", off, peak)
            for modelo, cat, off, peak in self.OFICIAL)
        self.assertEqual(got, esperado)

    def test_discount_is_computed_not_claimed(self):
        for c in self.c:
            expected = round(100 * (1 - c.price_offer / c.price_baseline), 2)
            self.assertAlmostEqual(c.discount_pct, expected, places=2)
            self.assertAlmostEqual(c.discount_pct, 50.0, places=2)

    def test_same_unit_and_modality_on_both_prices(self):
        for c in self.c:
            self.assertEqual(c.currency, "USD")
            self.assertTrue(c.price_unit.startswith("USD / 1M tokens"))
            self.assertEqual(c.offer_type, "OFF_PEAK_DISCOUNT")
            self.assertGreater(c.price_baseline, 0)
            self.assertLess(c.price_offer, c.price_baseline)

    def test_time_window_converted_to_art(self):
        win = self.c[0].time_window_art or ""
        self.assertIn("22:00", win)
        self.assertIn("03:00", win)
        self.assertIn("ART", win)

    def test_time_window_utc_is_taken_from_the_page(self):
        """No hardcodeada: sale del texto oficial y incluye la exclusion de feriados."""
        for c in self.c:
            win = c.time_window_utc or ""
            self.assertIn("01:00 - 04:00", win)
            self.assertIn("06:00 - 10:00", win)
            self.assertIn("UTC", win)
            self.assertIn("Monday through Friday", win)
            self.assertIn("excluding Chinese public holidays", win)

    def test_offpeak_complement_recorded(self):
        for c in self.c:
            self.assertIn("All other hours are off-peak", c.notes)
            self.assertIn("weekends", c.notes)

    def test_search_and_fetch_tariff_is_not_an_offer(self):
        """$0.75 cada 1000 requests es tarifa normal, no promocion: no se emite."""
        for c in self.c:
            blob = f"{c.title} {c.benefit} {c.price_unit}"
            self.assertNotIn("Search", blob)
            self.assertNotIn("Fetch", blob)
            self.assertNotIn("1,000", blob)
            self.assertNotEqual(c.price_offer, 0.75)

    def test_dedupe_keys_unique(self):
        keys = {c.dedupe_key() for c in self.c}
        self.assertEqual(len(keys), len(self.c))

    def test_evidence_is_literal_and_present(self):
        for c in self.c:
            self.assertTrue(c.evidence_snippet)
            self.assertIn("OFF-PEAK", c.evidence_snippet)
            self.assertIn("PEAK", c.evidence_snippet)
            self.assertEqual(c.official_url, self.src.url)
            self.assertEqual(c.argentina_status, "ARGENTINA_NO_CONFIRMADA")

    def test_wrong_document_with_http_200_yields_nothing(self):
        """Regresion P0.2: captura real de la URL sin barra final (HTTP 200)."""
        raw = (FIX / "deepseek-pricing-wrong-document.html").read_text(encoding="utf-8")
        self.assertIn("Your First API Call", raw)
        res = FetchResult(url=self.src.url, status=200, text=raw, sha256="fixture",
                          fetched_at_utc=utcnow(), bytes_read=len(raw))
        self.assertEqual(extract.extract(self.src, res), [])

    def test_table_without_claim_yields_nothing(self):
        """Sin la declaracion explicita de mitad de precio no se inventa descuento."""
        raw = (FIX / "deepseek-pricing.html").read_text(encoding="utf-8")
        sin_claim = raw.replace("Off-peak rates are half of the peak rates",
                                "Off-peak rates are listed below")
        self.assertNotIn("Off-peak rates are half of the peak rates", sin_claim)
        res = FetchResult(url=self.src.url, status=200, text=sin_claim, sha256="fixture",
                          fetched_at_utc=utcnow(), bytes_read=len(sin_claim))
        self.assertEqual(extract.extract(self.src, res), [])

    def test_unidentifiable_model_column_is_not_attributed(self):
        """Sin nombres de modelo en el encabezado no se atribuye ninguna columna."""
        raw = (FIX / "deepseek-pricing.html").read_text(encoding="utf-8")
        header = "<td>deepseek-flash<sup>(1)</sup></td><td>deepseek-v4-pro</td>"
        self.assertIn(header, raw)
        sin_header = raw.replace(header, '<td colspan="2">N/D</td>')
        self.assertNotIn(header, sin_header)
        res = FetchResult(url=self.src.url, status=200, text=sin_header, sha256="fixture",
                          fetched_at_utc=utcnow(), bytes_read=len(sin_header))
        self.assertEqual(extract.extract(self.src, res), [])


class TestDeepSeekPersistence(unittest.TestCase):
    """Recorrido determinista fixture -> pipeline -> SQLite, con base temporal."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="ach_p02_")
        self.db = Path(self.tmp.name) / "p02.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        from ach import pipeline
        return pipeline.run(db_path=self.db, source_ids=["deepseek-pricing"],
                            fixture_dir=FIX, quiet=True)

    def test_offers_persisted_as_fixture_with_integrity(self):
        from ach import store
        rep = self._run()
        self.assertEqual(rep.candidates, 6)
        self.assertEqual(rep.errors, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            rows = conn.execute(
                "SELECT product, price_baseline, price_offer, discount_pct, "
                "verification_level, discount_band FROM offer "
                "WHERE provider_key='deepseek'").fetchall()
            self.assertEqual(len(rows), 6)
            for r in rows:
                self.assertAlmostEqual(r["discount_pct"], 50.0, places=2)
                self.assertGreater(r["price_baseline"], 0)
                # Un fixture nunca cuenta como verificacion real.
                self.assertEqual(r["verification_level"], "FIXTURE")
                self.assertEqual(r["discount_band"], "DESCUENTO_50_69")
            ev = conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE snippet IS NOT NULL "
                "AND snippet != '' AND http_status=200").fetchone()[0]
            self.assertGreaterEqual(ev, 6)
            last = conn.execute(
                "SELECT last_candidates, last_http_status FROM source "
                "WHERE source_id='deepseek-pricing'").fetchone()
            self.assertEqual(last["last_candidates"], 6)
            self.assertEqual(last["last_http_status"], 200)
        finally:
            conn.close()

    def test_second_run_deduplicates(self):
        from ach import store
        self._run()
        rep2 = self._run()
        self.assertEqual(rep2.offers_new, 0)
        self.assertGreater(rep2.offers_seen, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            distinct = conn.execute("SELECT COUNT(DISTINCT dedupe_key) FROM offer").fetchone()[0]
            self.assertEqual(total, distinct)
            self.assertEqual(total, 6)
        finally:
            conn.close()


class TestHtmlSources(unittest.TestCase):
    def test_cloudflare_free_allocation(self):
        src = BY_ID["cloudflare-workers-ai-pricing"]
        c = extract.extract(src, load(src.id))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].discount_pct, 100.0)
        self.assertIn("10,000", c[0].benefit)
        self.assertEqual(c[0].price_baseline, 0.011)

    def test_kiro_free_plan(self):
        src = BY_ID["kiro-pricing"]
        c = extract.extract(src, load(src.id))
        self.assertEqual(len(c), 1)
        self.assertIn("50", c[0].title)
        self.assertEqual(c[0].price_baseline, 20.0)
        self.assertEqual(c[0].price_offer, 0.0)

    def test_vercel_monthly_credit(self):
        src = BY_ID["vercel-ai-gateway-pricing"]
        c = extract.extract(src, load(src.id))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].price_baseline, 5.0)
        self.assertIn("5", c[0].title)


class TestRss(unittest.TestCase):
    def test_no_institutional_noise(self):
        """Un anuncio institucional que dice 'free' al pasar no es una oferta."""
        src = BY_ID["openai-news-rss"]
        c = extract.extract(src, load(src.id))
        self.assertLessEqual(len(c), 10)
        titles = " ".join(x.title for x in c)
        self.assertNotIn("Australian universities", titles)
        self.assertNotIn("Credit Saison", titles)

    def test_every_item_has_two_signals(self):
        for sid in ("openai-news-rss", "google-ai-blog-rss", "huggingface-blog-rss"):
            src = BY_ID[sid]
            for c in extract.extract(src, load(src.id)):
                blob = f"{c.title} {c.benefit}"
                self.assertTrue(extract.PROMO_TERMS.search(blob), c.title)
                self.assertTrue(extract.PROMO_QUALIFIER.search(blob), c.title)
                self.assertEqual(c.confidence, "baja")


class TestRobustness(unittest.TestCase):
    def test_malformed_input_returns_empty(self):
        src = BY_ID["deepseek-pricing"]
        res = FetchResult(url=src.url, status=200, text="<html></html>",
                          fetched_at_utc=utcnow())
        self.assertEqual(extract.extract(src, res), [])

    def test_truncated_json_returns_empty(self):
        src = BY_ID["openrouter-free-models"]
        res = FetchResult(url=src.url, status=200, text='{"data":[', fetched_at_utc=utcnow())
        self.assertEqual(extract.extract(src, res), [])

    def test_unknown_extractor_returns_empty(self):
        from dataclasses import replace
        src = replace(BY_ID["deepseek-pricing"], extractor="no-existe")
        res = FetchResult(url=src.url, status=200, text="<p>x</p>", fetched_at_utc=utcnow())
        self.assertEqual(extract.extract(src, res), [])


if __name__ == "__main__":
    unittest.main()
