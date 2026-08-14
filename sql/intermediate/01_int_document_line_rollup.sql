-- ===========================================================================
-- MODEL:    int_document_line_rollup
-- LAYER:    intermediate
-- GRAIN:    one row per document record
-- SOURCES:  stg_document_lines
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- Rolls lines up to the document and, in doing so, produces the number the
-- header is supposed to agree with. Keeping recomputed_tax next to the stated
-- total in fct_document makes the IVA reconciliation defect visible as data
-- rather than only as a validation finding — you can sum the discrepancy in
-- colones, which is what makes it an argument rather than a complaint.
--
-- CONTRACT
--   document_record_id  NOT NULL, unique
--   line_count          >= 1
-- ===========================================================================

CREATE OR REPLACE VIEW int_document_line_rollup AS
SELECT
    document_record_id,
    COUNT(*)                                          AS line_count,
    SUM(line_gross)                                   AS recomputed_gross,
    SUM(discount)                                     AS recomputed_discount,
    SUM(line_subtotal)                                AS recomputed_net,
    SUM(tax_amount)                                   AS recomputed_tax,
    SUM(line_total)                                   AS recomputed_total,
    SUM(CASE WHEN tax_rate_percent > 0 THEN line_subtotal ELSE 0 END) AS recomputed_taxable,
    SUM(CASE WHEN tax_rate_percent = 0 THEN line_subtotal ELSE 0 END) AS recomputed_exempt,
    COUNT(DISTINCT tax_rate_code)                     AS distinct_rate_codes
FROM stg_document_lines
GROUP BY document_record_id;
