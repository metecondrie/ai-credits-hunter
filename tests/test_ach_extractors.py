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
    def setUp(self):
        self.src = BY_ID["deepseek-pricing"]
        self.c = extract.extract(self.src, load(self.src.id))

    def test_three_price_lines(self):
        self.assertEqual(len(self.c), 3)
        units = " ".join(c.price_unit or "" for c in self.c)
        self.assertIn("cache hit", units)
        self.assertIn("cache miss", units)
        self.assertIn("salida", units)

    def test_discount_is_computed_not_claimed(self):
        for c in self.c:
            expected = round(100 * (1 - c.price_offer / c.price_baseline), 2)
            self.assertAlmostEqual(c.discount_pct, expected, places=2)
            self.assertAlmostEqual(c.discount_pct, 50.0, places=2)

    def test_time_window_converted_to_art(self):
        win = self.c[0].time_window_art or ""
        self.assertIn("22:00", win)
        self.assertIn("03:00", win)
        self.assertIn("ART", win)


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
