-- AI Credits Hunter v4 - migracion 004
-- Interpretaciones de IA sobre ofertas. Idempotente.
--
-- REGLA: esta tabla guarda INTERPRETACIONES de un modelo de IA, nunca
-- verificaciones oficiales. La tabla `evidence` (fragmento literal, sha256,
-- URL) NO se modifica por la IA: permanece como fuente de verdad.

CREATE TABLE IF NOT EXISTS ai_assessment (
    ai_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id              INTEGER NOT NULL REFERENCES offer(offer_id) ON DELETE CASCADE,
    run_id                INTEGER REFERENCES run(run_id),
    provider              TEXT NOT NULL,          -- proveedor usado (gemini, groq, ...)
    model                 TEXT NOT NULL,          -- identificador exacto del modelo
    is_offer              INTEGER CHECK (is_offer IN (0,1) OR is_offer IS NULL),
    benefit_type          TEXT,
    conditions            TEXT,
    restrictions          TEXT,
    argentina_eligibility TEXT,
    confidence            TEXT CHECK (confidence IN ('alta','media','baja') OR confidence IS NULL),
    justification         TEXT,
    cost_status           TEXT NOT NULL,          -- free_verified | authorized_unverified | demo_local
    raw_response          TEXT,                   -- respuesta cruda (transparencia, sin claves)
    error                 TEXT,                   -- bloqueo o fallo, si lo hubo
    created_at_utc        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_assessment_offer ON ai_assessment(offer_id);
CREATE INDEX IF NOT EXISTS idx_ai_assessment_run ON ai_assessment(run_id);
