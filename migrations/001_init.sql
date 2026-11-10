-- AI Credits Hunter v4 - migracion 001
-- Esquema base del motor de recoleccion. Idempotente.

CREATE TABLE IF NOT EXISTS schema_version (
    version        INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    description    TEXT
);

CREATE TABLE IF NOT EXISTS provider (
    provider_key     TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    company          TEXT,
    category         TEXT,
    official_domains TEXT,
    identity_status  TEXT NOT NULL DEFAULT 'CONFIRMED'
                     CHECK (identity_status IN ('CONFIRMED','HISTORICAL','RETIRED')),
    created_utc      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source (
    source_id         TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    provider_key      TEXT NOT NULL REFERENCES provider(provider_key) ON DELETE RESTRICT,
    url               TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('json','html','rss')),
    extractor         TEXT NOT NULL,
    priority          TEXT,
    cadence_hours     INTEGER,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    last_run_utc      TEXT,
    last_http_status  INTEGER,
    last_etag         TEXT,
    last_modified     TEXT,
    last_sha256       TEXT,
    last_error        TEXT,
    last_candidates   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_utc     TEXT NOT NULL,
    finished_utc    TEXT,
    mode            TEXT NOT NULL CHECK (mode IN ('live','fixtures')),
    sources_total   INTEGER NOT NULL DEFAULT 0,
    sources_ok      INTEGER NOT NULL DEFAULT 0,
    sources_failed  INTEGER NOT NULL DEFAULT 0,
    sources_skipped INTEGER NOT NULL DEFAULT 0,
    candidates      INTEGER NOT NULL DEFAULT 0,
    offers_new      INTEGER NOT NULL DEFAULT 0,
    offers_seen     INTEGER NOT NULL DEFAULT 0,
    offers_changed  INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS offer (
    offer_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key         TEXT NOT NULL UNIQUE,
    provider_key       TEXT NOT NULL REFERENCES provider(provider_key) ON DELETE RESTRICT,
    source_id          TEXT REFERENCES source(source_id) ON DELETE SET NULL,
    product            TEXT NOT NULL,
    title              TEXT NOT NULL,
    offer_type         TEXT NOT NULL,
    benefit            TEXT,
    price_baseline     REAL,
    price_offer        REAL,
    price_unit         TEXT,
    currency           TEXT,
    discount_pct       REAL,
    discount_band      TEXT NOT NULL,
    eligibility        TEXT,
    card_required      TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (card_required IN ('yes','no','unknown')),
    auto_renewal       TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (auto_renewal IN ('yes','no','unknown')),
    student_required   TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (student_required IN ('yes','no','unknown')),
    argentina_status   TEXT NOT NULL,
    official_url       TEXT NOT NULL,
    terms_url          TEXT,
    starts_at          TEXT,
    expires_at         TEXT,
    published_at       TEXT,
    time_window_art    TEXT,
    confidence         TEXT NOT NULL CHECK (confidence IN ('alta','media','baja')),
    verification_level TEXT NOT NULL
                       CHECK (verification_level IN
                              ('NETWORK_VERIFIED','CONTENT_VERIFIED','UNVERIFIED','FIXTURE')),
    status             TEXT NOT NULL DEFAULT 'NUEVA'
                       CHECK (status IN ('NUEVA','VISTA','CAMBIADA','EXPIRADA','RETIRADA')),
    notes              TEXT,
    first_seen_utc     TEXT NOT NULL,
    last_seen_utc      TEXT NOT NULL,
    created_utc        TEXT NOT NULL,
    updated_utc        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_offer_provider ON offer(provider_key);
CREATE INDEX IF NOT EXISTS ix_offer_band ON offer(discount_band);
CREATE INDEX IF NOT EXISTS ix_offer_status ON offer(status);
CREATE INDEX IF NOT EXISTS ix_offer_last_seen ON offer(last_seen_utc);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id           INTEGER NOT NULL REFERENCES offer(offer_id) ON DELETE CASCADE,
    run_id             INTEGER REFERENCES run(run_id) ON DELETE SET NULL,
    source_id          TEXT REFERENCES source(source_id) ON DELETE SET NULL,
    url                TEXT NOT NULL,
    http_status        INTEGER NOT NULL,
    content_sha256     TEXT,
    etag               TEXT,
    last_modified      TEXT,
    snippet            TEXT,
    extraction_rule    TEXT,
    observed_at_utc    TEXT NOT NULL,
    verification_level TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_evidence_offer ON evidence(offer_id);
CREATE INDEX IF NOT EXISTS ix_evidence_run ON evidence(run_id);

CREATE TABLE IF NOT EXISTS offer_event (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id       INTEGER NOT NULL REFERENCES offer(offer_id) ON DELETE CASCADE,
    run_id         INTEGER REFERENCES run(run_id) ON DELETE SET NULL,
    event_type     TEXT NOT NULL
                   CHECK (event_type IN ('NUEVA','VISTA','CAMBIADA','EXPIRADA','RETIRADA')),
    changed_fields TEXT,
    at_utc         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_event_offer ON offer_event(offer_id);
CREATE INDEX IF NOT EXISTS ix_event_run ON offer_event(run_id);

CREATE TABLE IF NOT EXISTS source_run (
    source_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    source_id     TEXT NOT NULL REFERENCES source(source_id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    http_status   INTEGER,
    bytes         INTEGER,
    elapsed_ms    INTEGER,
    candidates    INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    at_utc        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_source_run_run ON source_run(run_id);
