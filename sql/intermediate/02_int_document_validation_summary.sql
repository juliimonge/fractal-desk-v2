-- ===========================================================================
-- MODEL:    int_document_validation_summary
-- LAYER:    intermediate
-- GRAIN:    one row per document record that produced at least one finding
-- SOURCES:  stg_validation_findings
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- Collapses the finding list to one row per document so fct_document can carry
-- a validation verdict without fanning out. Documents with no findings are
-- absent here, so downstream joins are LEFT and treat NULL as zero — a clean
-- document should not need a row to prove it is clean.
--
-- CONTRACT
--   document_record_id  NOT NULL, unique
--   error_count + warning_count + info_count = finding_count
-- ===========================================================================

CREATE OR REPLACE VIEW int_document_validation_summary AS
SELECT
    document_record_id,
    COUNT(*)                                                        AS finding_count,
    COUNT(*) FILTER (WHERE severity = 'ERROR')                      AS error_count,
    COUNT(*) FILTER (WHERE severity = 'WARNING')                    AS warning_count,
    COUNT(*) FILTER (WHERE severity = 'INFO')                       AS info_count,
    -- Sorted so the string is stable across runs and can be compared directly
    -- between two builds of the warehouse.
    STRING_AGG(DISTINCT rule_id, ',' ORDER BY rule_id)              AS triggered_rule_ids
FROM stg_validation_findings
GROUP BY document_record_id;
