-- ===========================================================================
-- MODEL:    stg_documents
-- LAYER:    staging
-- GRAIN:    one row per generated document record
-- SOURCE:   raw_documents
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- NOTE ON GRAIN: the grain is "document RECORD", not "document". The synthetic
-- data deliberately contains duplicate claves, so clave is NOT a key here. It
-- becomes a key only in fct_document, where duplicates are resolved explicitly
-- and the resolution is visible. Staging that silently deduplicated would hide
-- the exact defect the validation layer exists to find.
--
-- MONEY: amounts are DECIMAL(18,5), matching the five decimal places v4.4
-- permits. Not DOUBLE. A reconciliation rule expressed in floating point fails
-- on rounding noise and passes on real errors.
--
-- CONTRACT
--   document_record_id  NOT NULL, unique (surrogate; survives duplicate claves)
--   clave               NOT NULL (may be malformed; may repeat)
--   issue_date          NOT NULL
--   total_tax           NOT NULL
-- ===========================================================================

CREATE OR REPLACE VIEW stg_documents AS
SELECT
    CAST(document_record_id AS BIGINT)                AS document_record_id,
    CAST(clave AS VARCHAR)                            AS clave,
    CAST(consecutivo AS VARCHAR)                      AS consecutivo,
    CAST(document_type_code AS VARCHAR)               AS document_type_code,

    CAST(issuer_id AS VARCHAR)                        AS issuer_id,
    CAST(issuer_id_type AS VARCHAR)                   AS issuer_id_type,
    TRIM(CAST(issuer_name AS VARCHAR))                AS issuer_name,
    CAST(receiver_id AS VARCHAR)                      AS receiver_id,
    CAST(receiver_id_type AS VARCHAR)                 AS receiver_id_type,
    TRIM(CAST(receiver_name AS VARCHAR))              AS receiver_name,

    CAST(issue_datetime AS TIMESTAMP)                 AS issue_datetime,
    CAST(issue_datetime AS DATE)                      AS issue_date,
    CAST(received_datetime AS TIMESTAMP)              AS received_datetime,
    CAST(received_datetime AS DATE)                   AS received_date,
    CAST(accepted_datetime AS TIMESTAMP)              AS accepted_datetime,
    CAST(accepted_datetime AS DATE)                   AS accepted_date,

    -- The month the acceptance obligation attaches to. Every document issued in
    -- the same month shares one deadline, so this is the natural reporting
    -- period for anything deadline-related.
    CAST(DATE_TRUNC('month', CAST(issue_datetime AS DATE)) AS DATE) AS issue_month,

    NULLIF(TRIM(CAST(economic_activity_code AS VARCHAR)), '') AS economic_activity_code,
    CAST(currency AS VARCHAR)                         AS currency,
    CAST(exchange_rate AS DECIMAL(18,5))              AS exchange_rate,

    CAST(total_taxable AS DECIMAL(18,5))              AS total_taxable,
    CAST(total_exempt AS DECIMAL(18,5))               AS total_exempt,
    CAST(total_discount AS DECIMAL(18,5))             AS total_discount,
    CAST(total_net AS DECIMAL(18,5))                  AS total_net,
    CAST(total_tax AS DECIMAL(18,5))                  AS total_tax,
    CAST(total_document AS DECIMAL(18,5))             AS total_document,

    -- Colón-denominated IVA. Cross-currency sums are meaningless without this,
    -- and the dashboard's headline "credit at risk" figure is a single number in
    -- colones. Uses the rate carried on the document (the rate that applied on
    -- the issue date), not a current rate.
    CAST(total_tax AS DECIMAL(18,5))
        * CAST(NULLIF(exchange_rate, 0) AS DECIMAL(18,5))  AS total_tax_crc,

    CAST(injected_defects AS VARCHAR)                 AS injected_defects,
    TRUE                                              AS is_synthetic
FROM raw_documents;
