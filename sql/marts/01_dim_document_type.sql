-- ===========================================================================
-- MODEL:    dim_document_type
-- LAYER:    marts
-- GRAIN:    one row per TipoDocumento code
-- SOURCES:  ref_document_types (loaded from data/catalog_document_types.csv)
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- A small dimension, but it carries the flag the whole deadline model hinges
-- on: enters_acceptance_workflow. A tiquete electrónico is issued to a final
-- consumer and generates no receiver obligation, so it must never appear in an
-- at-risk queue. Encoding that as a dimension attribute rather than as a
-- hardcoded `WHERE document_type_code <> '04'` in five places means the rule
-- changes in one row of a CSV if Hacienda changes it.
--
-- credit_sign lets IVA be summed directionally: a nota de crédito reduces the
-- credit position rather than adding to it, so summing raw IVA across mixed
-- document types overstates exposure.
--
-- CONTRACT
--   document_type_code  NOT NULL, unique
--   credit_sign         one of -1, 0, 1
-- ===========================================================================

CREATE OR REPLACE TABLE dim_document_type AS
SELECT
    CAST(type_code AS VARCHAR)                        AS document_type_code,
    CAST(name_es AS VARCHAR)                          AS document_type_name_es,
    CAST(name_en AS VARCHAR)                          AS document_type_name_en,
    CAST(requires_receiver AS BOOLEAN)                AS requires_receiver,
    CAST(enters_acceptance_workflow AS BOOLEAN)       AS enters_acceptance_workflow,
    CAST(credit_sign AS INTEGER)                      AS credit_sign
FROM ref_document_types;
