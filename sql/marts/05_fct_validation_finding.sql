-- ===========================================================================
-- MODEL:    fct_validation_finding
-- LAYER:    marts
-- GRAIN:    one row per finding
-- SOURCES:  stg_validation_findings, fct_document
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- Findings joined back to document context so a defect can be grouped by issuer
-- and priced. "Rule V012 fired 84 times" is a QA metric; "these six suppliers
-- account for 71% of V012, on ₡X of IVA" is something you can act on.
--
-- iva_exposed_crc attaches the document's whole IVA to each of its findings.
-- That is intentional and must not be summed across a document's findings: a
-- document with three findings would count its IVA three times. Sum it only
-- within a single rule_id, which is how the dashboard uses it.
--
-- CONTRACT
--   (document_record_id, rule_id, line_number)  unique together
--   severity  one of ERROR, WARNING, INFO
-- ===========================================================================

CREATE OR REPLACE TABLE fct_validation_finding AS
SELECT
    v.document_record_id,
    v.clave,
    v.rule_id,
    v.rule_name,
    v.severity,
    v.message,
    v.line_number,
    v.expected_value,
    v.actual_value,

    f.document_type_code,
    f.document_type_name_es,
    f.issuer_id,
    f.issuer_name,
    f.issue_date,
    f.issue_month,
    f.currency,

    -- See the header note: do NOT sum this across a document's findings.
    f.total_tax_crc                                   AS iva_exposed_crc,
    f.is_synthetic
FROM stg_validation_findings v
JOIN fct_document f USING (document_record_id);
