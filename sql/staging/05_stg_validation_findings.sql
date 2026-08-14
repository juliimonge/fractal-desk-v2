-- ===========================================================================
-- MODEL:    stg_validation_findings
-- LAYER:    staging
-- GRAIN:    one row per finding (a document can produce many; a clean one none)
-- SOURCE:   raw_validation_findings  (written by src/fractal_desk/validation.py)
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- CONTRACT
--   rule_id    NOT NULL, matches a key in validation.RULES
--   severity   one of ERROR, WARNING, INFO
--   line_number NULL for document-level findings, populated for line-level ones
-- ===========================================================================

CREATE OR REPLACE VIEW stg_validation_findings AS
SELECT
    CAST(document_record_id AS BIGINT)                AS document_record_id,
    CAST(clave AS VARCHAR)                            AS clave,
    CAST(rule_id AS VARCHAR)                          AS rule_id,
    CAST(rule_name AS VARCHAR)                        AS rule_name,
    CAST(severity AS VARCHAR)                         AS severity,
    CAST(message AS VARCHAR)                          AS message,
    CAST(line_number AS INTEGER)                      AS line_number,
    CAST(expected AS VARCHAR)                         AS expected_value,
    CAST(actual AS VARCHAR)                           AS actual_value
FROM raw_validation_findings;
