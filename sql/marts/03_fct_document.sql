-- ===========================================================================
-- MODEL:    fct_document
-- LAYER:    marts
-- GRAIN:    one row per document record
-- SOURCES:  stg_documents, int_document_line_rollup,
--           int_document_validation_summary, dim_document_type
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- The document fact. One row per RECORD, so duplicate claves are two rows.
--
-- WHY DUPLICATES ARE KEPT
-- Deduplicating here would make the table tidier and the analysis wrong.
-- A duplicate clave is not noise to be cleaned; it is a defect with a money
-- consequence, because two records claiming the same IVA credit will either
-- double-count the credit or, when someone notices, cost the time to work out
-- which copy is real. The columns clave_occurrence and clave_is_duplicated make
-- the duplication addressable: filter to clave_occurrence = 1 for a deduplicated
-- view, or to clave_is_duplicated for the remediation queue. Both are one
-- predicate away, and neither is the silent default.
--
-- RECOMPUTED VS STATED
-- recomputed_tax comes from the lines; total_tax is what the document header
-- claims. iva_discrepancy_crc is the gap, in colones. It is a column rather
-- than a validation finding because the aggregate matters: "142 documents fail
-- IVA reconciliation" is a bug report, "₡2.1M of stated IVA does not match the
-- lines it came from" is a business case.
--
-- CONTRACT
--   document_record_id  NOT NULL, unique
--   line_count          >= 1
--   has_blocking_error  TRUE iff error_count > 0
-- ===========================================================================

CREATE OR REPLACE TABLE fct_document AS
WITH clave_occurrences AS (
    SELECT
        document_record_id,
        clave,
        ROW_NUMBER() OVER (PARTITION BY clave ORDER BY document_record_id) AS clave_occurrence,
        COUNT(*)    OVER (PARTITION BY clave)                              AS clave_record_count
    FROM stg_documents
)
SELECT
    d.document_record_id,
    d.clave,
    o.clave_occurrence,
    o.clave_record_count,
    (o.clave_record_count > 1)                        AS clave_is_duplicated,
    d.consecutivo,

    d.document_type_code,
    t.document_type_name_es,
    t.enters_acceptance_workflow,
    t.credit_sign,

    d.issuer_id,
    d.issuer_name,
    d.receiver_id,
    d.receiver_name,

    d.issue_date,
    d.issue_month,
    d.received_date,
    d.accepted_date,
    -- Calendar days between issue and arrival. A large value here is the
    -- upstream cause of most lost credit, and it is not something the receiving
    -- business can fix internally.
    DATE_DIFF('day', d.issue_date, d.received_date)   AS arrival_lag_days,

    d.economic_activity_code,
    d.currency,
    d.exchange_rate,

    d.total_net,
    d.total_tax,
    d.total_document,
    d.total_tax_crc,

    r.line_count,
    r.recomputed_net,
    r.recomputed_tax,
    -- Signed gap between the header's IVA and the sum of its own lines,
    -- restated in colones so it can be summed across currencies.
    ROUND(
        (d.total_tax - r.recomputed_tax) * COALESCE(NULLIF(d.exchange_rate, 0), 1),
        2
    )                                                 AS iva_discrepancy_crc,

    COALESCE(v.finding_count, 0)                      AS finding_count,
    COALESCE(v.error_count, 0)                        AS error_count,
    COALESCE(v.warning_count, 0)                      AS warning_count,
    (COALESCE(v.error_count, 0) > 0)                  AS has_blocking_error,
    v.triggered_rule_ids,

    d.injected_defects,
    d.is_synthetic
FROM stg_documents d
JOIN clave_occurrences o                     USING (document_record_id)
JOIN int_document_line_rollup r              USING (document_record_id)
LEFT JOIN int_document_validation_summary v  USING (document_record_id)
LEFT JOIN dim_document_type t                USING (document_type_code);
