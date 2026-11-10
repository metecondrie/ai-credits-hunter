"""Pruebas unitarias del nucleo (sin red)."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ach import classify, config, store
from ach.models import Candidate
from ach.sources import PROVIDERS, SOURCES


def make_candidate(**kw) -> Candidate:
    base = dict(
        source_id="test-src",
        provider_key="deepseek",
        product="Producto X",
        title="Titulo",
        offer_type="FREE_TIER",
        benefit="Beneficio",
        official_url="https://example.com/x",
        evidence_url="https://example.com/x",
        evidence_snippet="texto literal",
        extraction_rule="test",
    )
    base.update(kw)
    return Candidate(**base)


class TestGuards(unittest.TestCase):
    def test_rejects_production_db(self):
        with self.assertRaises(SystemExit):
            config.resolve_db("data/promotions.sqlite3")
        with self.assertRaises(SystemExit):
            config.resolve_db("C:/tmp/hunter.db")

    def test_default_db_is_not_production(self):
        self.assertNotIn(config.DEFAULT_DB.name, config.PROTECTED_DB_NAMES)


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ach_mig_"))
        self.db = self.tmp / "t.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_idempotent(self):
        conn = store.connect(self.db)
        first = store.migrate(conn)
        second = store.migrate(conn)
        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertGreaterEqual(store.schema_version(conn), 3)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        conn.close()

    def test_checksum_tamper_detected(self):
        mdir = self.tmp / "mig"
        shutil.copytree(config.MIGRATIONS_DIR, mdir)
        conn = store.connect(self.db)
        store.migrate(conn, mdir)
        target = sorted(mdir.glob("*.sql"))[0]
        target.write_text(target.read_text(encoding="utf-8") + "\n-- cambio\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            store.migrate(conn, mdir)
        conn.close()

    def test_foreign_keys_enforced(self):
        conn = store.connect(self.db)
        store.migrate(conn)
        store.seed(conn, PROVIDERS, SOURCES)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO offer (dedupe_key, provider_key, product, title, offer_type,"
                " discount_band, argentina_status, official_url, confidence,"
                " verification_level, first_seen_utc, last_seen_utc, created_utc, updated_utc)"
                " VALUES ('k','no-existe','p','t','FREE_TIER','X','Y','u','alta',"
                "'NETWORK_VERIFIED','n','n','n','n')")
        conn.close()


class TestDedupeAndStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ach_store_"))
        self.conn = store.connect(self.tmp / "s.sqlite3")
        store.migrate(self.conn)
        store.seed(self.conn, PROVIDERS, SOURCES)
        self.run_id = store.start_run(self.conn, "fixtures", 1)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_key_stable_and_sensitive(self):
        a = make_candidate()
        b = make_candidate(title="Otro titulo")
        c = make_candidate(product="Otro producto")
        self.assertEqual(a.dedupe_key(), b.dedupe_key())
        self.assertNotEqual(a.dedupe_key(), c.dedupe_key())
        self.assertEqual(len(a.dedupe_key()), 32)

    def test_events_new_seen_changed(self):
        c = make_candidate()
        oid, ev, _ = store.upsert_offer(self.conn, c, self.run_id, "FIXTURE", "deepseek-pricing")
        self.assertEqual(ev, "NUEVA")
        oid2, ev2, _ = store.upsert_offer(self.conn, c, self.run_id, "FIXTURE", "deepseek-pricing")
        self.assertEqual((oid, ev2), (oid2, "VISTA"))
        c2 = make_candidate(benefit="Beneficio cambiado")
        _, ev3, changed = store.upsert_offer(self.conn, c2, self.run_id, "FIXTURE", "deepseek-pricing")
        self.assertEqual(ev3, "CAMBIADA")
        self.assertIn("benefit", changed)

    def test_expire_by_date(self):
        c = make_candidate(expires_at="2020-01-01")
        oid, _, _ = store.upsert_offer(self.conn, c, self.run_id, "FIXTURE", "deepseek-pricing")
        n = store.expire_offers(self.conn, self.run_id)
        self.assertGreaterEqual(n, 1)
        row = self.conn.execute("SELECT status FROM offer WHERE offer_id=?", (oid,)).fetchone()
        self.assertEqual(row["status"], "EXPIRADA")


class TestClassify(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(classify.discount_band(None), "SIN_BASE_VERIFICADA")
        self.assertEqual(classify.discount_band(100), "GRATIS_100")
        self.assertEqual(classify.discount_band(95), "DESCUENTO_90_PLUS")
        self.assertEqual(classify.discount_band(80), "DESCUENTO_70_89")
        self.assertEqual(classify.discount_band(50), "DESCUENTO_50_69")
        self.assertEqual(classify.discount_band(31), "DESCUENTO_30_49")
        self.assertEqual(classify.discount_band(10), "SIN_DESCUENTO")

    def test_argentina_never_invented(self):
        c = make_candidate()
        self.assertEqual(classify.argentina_status(c), "ARGENTINA_NO_CONFIRMADA")
        c2 = make_candidate(benefit="Available worldwide, no restrictions")
        self.assertEqual(classify.argentina_status(c2), "DISPONIBLE_POR_DECLARACION")

    def test_verification_levels(self):
        c = make_candidate(price_baseline=10.0, price_offer=5.0, discount_pct=50.0)
        self.assertEqual(classify.verification_level(c, 200, False), "NETWORK_VERIFIED")
        self.assertEqual(classify.verification_level(c, 200, True), "FIXTURE")
        self.assertEqual(classify.verification_level(c, 500, False), "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
