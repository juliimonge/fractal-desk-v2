-- ===========================================================================
-- MODEL:    stg_document_lines
-- LAYER:    staging
-- GRAIN:    one row per line (LineaDetalle) per document record
-- SOURCE:   raw_document_lines
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- Joined to documents on document_record_id, not on clave. Duplicate claves
-- exist in this dataset by design, so a clave join would fan lines out across
-- both copies and silently double every rolled-up total.
--
-- CONTRACT
--   (document_record_id, line_number)  NOT NULL, unique together
--   tax_rate_percent                   NOT NULL, >= 0
-- ===========================================================================

CREATE OR REPLACE VIEW stg_document_lines AS
SELECT
    CAST(document_record_id AS BIGINT)                AS document_record_id,
    CAST(line_number AS INTEGER)                      AS line_number,
    CAST(cabys_code AS VARCHAR)                       AS cabys_code,
    TRIM(CAST(description AS VARCHAR))                AS line_description,
    CAST(quantity AS DECIMAL(18,5))                   AS quantity,
    CAST(unit_of_measure AS VARCHAR)                  AS unit_of_measure,
    CAST(unit_price AS DECIMAL(18,5))                 AS unit_price,
    CAST(line_gross AS DECIMAL(18,5))                 AS line_gross,
    CAST(discount AS DECIMAL(18,5))                   AS discount,
    CAST(line_subtotal AS DECIMAL(18,5))              AS line_subtotal,
    CAST(tax_rate_code AS VARCHAR)                    AS tax_rate_code,
    CAST(tax_rate_percent AS DECIMAL(9,5))            AS tax_rate_percent,
    CAST(tax_amount AS DECIMAL(18,5))                 AS tax_amount,
    CAST(line_total AS DECIMAL(18,5))                 AS line_total
FROM raw_document_lines;
