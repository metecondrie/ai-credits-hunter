"""Pruebas de integracion con fuentes reales (HTTP), interfaz y aislamiento.

Se pueden omitir con ACH_OFFLINE=1, pero por defecto corren contra las fuentes
publicas reales: son la prueba de que el producto no vive de fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

from ach import config, pipeline, sources as src_mod, store

LIVE_SOURCES = ["openrouter-free-models", "deepseek-pricing", "cloudflare-workers-ai-pricing"]
# Base productiva historica: no forma parte de este repositorio. Solo se usa
# para comprobar que las pruebas no la modifican. Si no existe, se omite.
PROD_DB = (
    Path(os.environ["ACH_PROD_DB"])
    if os.environ.get("ACH_PROD_DB")
    else Path(__file__).resolve().parent.parent / "data" / "promotions.sqlite3"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class LiveRunBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("ACH_OFFLINE") == "1":
            raise unittest.SkipTest("ACH_OFFLINE=1")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ach_live_"))
        cls.db = cls.tmp / "live.sqlite3"
        cls.prod_hash = sha256_file(PROD_DB) if PROD_DB.exists() else None
        cls.report = pipeline.run(db_path=cls.db, source_ids=LIVE_SOURCES, quiet=True)

    @classmethod
    def tearDownClass(cls):
        if cls.prod_hash:
            assert sha256_file(PROD_DB) == cls.prod_hash, "la base productiva cambio durante las pruebas"
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestLiveCollection(LiveRunBase):
    def test_run_completed_without_errors(self):
        self.assertEqual(self.report.errors, 0)
        self.assertGreaterEqual(self.report.candidates, 5)
        self.assertGreaterEqual(self.report.sources_ok, 3)

    def test_offers_persisted_with_evidence(self):
        conn = store.connect(self.db, readonly=True)
        try:
            offers = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            ev = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            self.assertGreaterEqual(offers, 5)
            self.assertGreaterEqual(ev, offers)
            rows = conn.execute(
                "SELECT o.offer_id, o.official_url, o.verification_level, e.snippet, e.http_status "
                "FROM offer o JOIN evidence e ON e.offer_id=o.offer_id").fetchall()
            for r in rows:
                self.assertTrue(r["official_url"].startswith("https://"))
                self.assertTrue(r["snippet"])
                self.assertEqual(r["http_status"], 200)
        finally:
            conn.close()

    def test_at_least_three_sources_verified(self):
        conn = store.connect(self.db, readonly=True)
        try:
            rows = conn.execute(
                "SELECT DISTINCT o.provider_key FROM offer o "
                "WHERE o.verification_level='NETWORK_VERIFIED'").fetchall()
            providers = {r[0] for r in rows}
            self.assertGreaterEqual(len(providers), 3, providers)
            fixture = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE verification_level='FIXTURE'").fetchone()[0]
            self.assertEqual(fixture, 0)
        finally:
            conn.close()

    def test_prices_come_from_pages(self):
        conn = store.connect(self.db, readonly=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM offer WHERE provider_key='deepseek' "
                "AND discount_pct=50.0 AND price_baseline>0").fetchone()
            self.assertGreaterEqual(row[0], 1)
            cf = conn.execute(
                "SELECT price_baseline FROM offer WHERE provider_key='cloudflare'").fetchone()
            self.assertIsNotNone(cf)
            self.assertAlmostEqual(cf[0], 0.011, places=4)
        finally:
            conn.close()

    def test_integrity_and_foreign_keys(self):
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_second_run_deduplicates(self):
        rep2 = pipeline.run(db_path=self.db, source_ids=LIVE_SOURCES, quiet=True)
        self.assertEqual(rep2.offers_new, 0)
        self.assertGreater(rep2.offers_seen + rep2.sources_skipped, 0)
        conn = store.connect(self.db, readonly=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0]
            distinct = conn.execute("SELECT COUNT(DISTINCT dedupe_key) FROM offer").fetchone()[0]
            self.assertEqual(total, distinct)
        finally:
            conn.close()


class TestFailureHandling(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ach_fail_"))
        self.db = self.tmp / "f.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unreachable_source_reports_error_and_keeps_going(self):
        bad = replace(src_mod.BY_ID["deepseek-pricing"],
                      id="bogus-source",
                      provider_key="deepseek",
                      url="https://no-existe.invalid/pricing",
                      extractor="deepseek_offpeak")
        src_mod.SOURCES.append(bad)
        src_mod.BY_ID["bogus-source"] = bad
        try:
            rep = pipeline.run(db_path=self.db, source_ids=["bogus-source"], quiet=True)
        finally:
            src_mod.SOURCES.remove(bad)
            src_mod.BY_ID.pop("bogus-source", None)
        self.assertEqual(rep.candidates, 0)
        self.assertGreaterEqual(rep.errors, 1)
        conn = store.connect(self.db, readonly=True)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM offer").fetchone()[0], 0)
            err = conn.execute("SELECT error FROM source_run ORDER BY source_run_id DESC").fetchone()[0]
            self.assertTrue(err)
        finally:
            conn.close()

    def test_production_db_is_refused(self):
        with self.assertRaises(SystemExit):
            pipeline.run(db_path=PROD_DB, source_ids=LIVE_SOURCES, quiet=True)


class TestWebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ach_ui_"))
        cls.db = cls.tmp / "ui.sqlite3"
        # Base minima: una oferta real tomada de un fixture, marcada FIXTURE.
        from ach import classify
        from ach.extract import extract
        from ach.fetch import FetchResult, utcnow

        conn = store.connect(cls.db)
        store.migrate(conn)
        store.seed(conn, src_mod.PROVIDERS, src_mod.SOURCES)
        run_id = store.start_run(conn, "fixtures", 1)
        src = src_mod.BY_ID["cloudflare-workers-ai-pricing"]
        raw = (Path(__file__).parent / "fixtures" / "cloudflare-workers-ai-pricing.html").read_text(encoding="utf-8")
        res = FetchResult(url=src.url, status=200, text=raw, fetched_at_utc=utcnow())
        for c in extract(src, res):
            c = classify.assess(c, 200, fixture=True)
            oid, _, _ = store.upsert_offer(conn, c, run_id, "FIXTURE", src.id)
            store.add_evidence(conn, oid, run_id, src.id, c.evidence_url, 200, "x",
                               None, None, c.evidence_snippet, c.extraction_rule, "FIXTURE")
        conn.close()

        from ach.web import Handler
        Handler.db_path = cls.db
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path: str) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            self.assertEqual(r.status, 200)
            return r.read().decode("utf-8")

    def test_index_lists_offer(self):
        body = self.get("/")
        self.assertIn("Workers AI", body)
        self.assertIn("CREDITS HUNTER", body)

    def test_detail_and_api(self):
        body = self.get("/oferta/1")
        self.assertIn("Evidencias", body)
        payload = json.loads(self.get("/api/ofertas"))
        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(payload["offers"][0]["official_url"].startswith("https://"))

    def test_sources_and_runs_pages(self):
        self.assertIn("cloudflare", self.get("/fuentes"))
        self.assertIn("Corridas", self.get("/corridas"))


if __name__ == "__main__":
    unittest.main()
