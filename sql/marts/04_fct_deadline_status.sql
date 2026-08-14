-- ===========================================================================
-- MODEL:    fct_deadline_status
-- LAYER:    marts
-- GRAIN:    one row per document record subject to an acceptance obligation
-- SOURCES:  stg_deadline_status, fct_document, dim_document_type
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- The table the dashboard is built on. Everything here answers one question:
-- what has to be accepted before credit is lost, and how much is on the line.
--
-- GRAIN WARNING: fewer rows than fct_document. Only document types with
-- enters_acceptance_workflow = TRUE generate an acceptance obligation, so
-- tiquetes are absent. Joining fct_document to this model must be a LEFT JOIN,
-- and a NULL status means "no obligation", not "not yet assessed".
--
-- iva_at_risk_crc is the number the tool exists to produce. Definitions:
--   * populated only for PENDING_AT_RISK and PENDING_SAFE — money that can
--     still be saved
--   * zero for ACCEPTED (secured) and for EXPIRED_CREDIT_LOST (gone; counted
--     separately as iva_lost_crc, because mixing recoverable and unrecoverable
--     money into one headline is how a dashboard stops being trusted)
--   * signed by credit_sign, so a nota de crédito subtracts
--   * denominated in colones at the document's own exchange rate
--
-- CONTRACT
--   document_record_id  NOT NULL, unique
--   status              one of ACCEPTED, PENDING_SAFE, PENDING_AT_RISK,
--                       EXPIRED_CREDIT_LOST
--   deadline_date       always the 8th business day of the month following
--                       issue_month
--   business_days_remaining >= 0; 0 for every terminal status
--   iva_at_risk_crc + iva_lost_crc is never double-counted: a row contributes
--   to at most one of them
-- ===========================================================================

CREATE OR REPLACE TABLE fct_deadline_status AS
SELECT
    s.document_record_id,
    s.clave,
    f.clave_is_duplicated,

    f.document_type_code,
    f.document_type_name_es,
    f.issuer_id,
    f.issuer_name,

    s.issue_date,
    f.issue_month,
    f.received_date,
    f.arrival_lag_days,

    -- The three dates that define the obligation. window_opens_on is carried so
    -- a status can be explained without re-running the engine.
    s.window_opens_on,
    s.deadline_date,
    s.as_of,

    s.status,
    s.business_days_remaining,
    s.accepted_on,
    s.accepted_late,

    -- Derived groupings the dashboard filters on. Expressed here rather than in
    -- the app so the definition of "due this week" lives in the warehouse and
    -- not in a chart.
    (s.status = 'PENDING_AT_RISK' AND s.business_days_remaining <= 1) AS due_today_or_next,
    (s.status IN ('PENDING_AT_RISK', 'PENDING_SAFE')
        AND s.business_days_remaining <= 5)                           AS due_within_five_business_days,

    f.currency,
    f.exchange_rate,
    f.total_tax,
    f.total_tax_crc,

    -- Recoverable exposure: still actionable.
    CASE
        WHEN s.status IN ('PENDING_AT_RISK', 'PENDING_SAFE')
        THEN ROUND(f.total_tax_crc * COALESCE(f.credit_sign, 1), 2)
        ELSE 0
    END                                               AS iva_at_risk_crc,

    -- Unrecoverable: already gone. Kept apart from at-risk on purpose.
    CASE
        WHEN s.status = 'EXPIRED_CREDIT_LOST'
        THEN ROUND(f.total_tax_crc * COALESCE(f.credit_sign, 1), 2)
        ELSE 0
    END                                               AS iva_lost_crc,

    CASE
        WHEN s.status = 'ACCEPTED'
        THEN ROUND(f.total_tax_crc * COALESCE(f.credit_sign, 1), 2)
        ELSE 0
    END                                               AS iva_secured_crc,

    f.error_count,
    f.has_blocking_error,
    f.is_synthetic
FROM stg_deadline_status s
JOIN fct_document f USING (document_record_id);
