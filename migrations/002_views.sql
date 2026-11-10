-- AI Credits Hunter v4 - migracion 002
-- Vista de lectura para la interfaz y el reporte. Idempotente.

DROP VIEW IF EXISTS v_offer_public;
CREATE VIEW v_offer_public AS
SELECT
    o.offer_id,
    o.dedupe_key,
    o.provider_key,
    p.name                        AS provider_name,
    o.product,
    o.title,
    o.offer_type,
    o.benefit,
    o.price_baseline,
    o.price_offer,
    o.price_unit,
    o.currency,
    o.discount_pct,
    o.discount_band,
    o.eligibility,
    o.card_required,
    o.auto_renewal,
    o.argentina_status,
    o.official_url,
    o.terms_url,
    o.expires_at,
    o.published_at,
    o.time_window_art,
    o.confidence,
    o.verification_level,
    o.status,
    o.first_seen_utc,
    o.last_seen_utc,
    (SELECT COUNT(*) FROM evidence e WHERE e.offer_id = o.offer_id) AS evidence_count,
    (SELECT e.url FROM evidence e WHERE e.offer_id = o.offer_id
      ORDER BY e.evidence_id DESC LIMIT 1)                          AS last_evidence_url
FROM offer o
JOIN provider p ON p.provider_key = o.provider_key;
