-- ===========================================================================
-- MODEL:    dim_contributor
-- LAYER:    marts
-- GRAIN:    one row per synthetic taxpayer
-- SOURCES:  stg_contributors, stg_documents, stg_deadline_status
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- A dimension with a few pre-aggregated behavioural attributes attached. That
-- is a deliberate departure from a pure dimension: the question "which of my
-- suppliers keeps costing me credit" is asked constantly and answering it from
-- the fact table every time is both slower and easier to get wrong.
--
-- expired_document_count and credit_lost_crc are the columns that turn this
-- from a lookup table into something worth opening. They are what supports a
-- conversation with a supplier, which is the only durable fix for a document
-- that arrives too late to accept.
--
-- SYNTHETIC DATA: every contributor_id begins '999', a range Costa Rica does
-- not issue, and every contributor_name begins 'SYN'. The is_synthetic column
-- restates it so a consumer of this table cannot miss it.
--
-- CONTRACT
--   contributor_id  NOT NULL, unique, LIKE '999%'
--   is_synthetic    always TRUE
-- ===========================================================================

CREATE OR REPLACE TABLE dim_contributor AS
WITH issued AS (
    SELECT
        d.issuer_id                                   AS contributor_id,
        COUNT(*)                                      AS document_count,
        SUM(d.total_tax_crc)                          AS total_iva_crc,
        MIN(d.issue_date)                             AS first_document_date,
        MAX(d.issue_date)                             AS last_document_date,
        -- Average calendar days between issue and arrival. The single best
        -- predictor of whether a supplier is going to cost you credit: a
        -- document that shows up after its own window has closed cannot be
        -- saved by any amount of internal diligence.
        AVG(DATE_DIFF('day', d.issue_date, d.received_date)) AS avg_arrival_lag_days
    FROM stg_documents d
    GROUP BY d.issuer_id
),
outcomes AS (
    SELECT
        d.issuer_id                                   AS contributor_id,
        COUNT(*) FILTER (WHERE s.status = 'EXPIRED_CREDIT_LOST')      AS expired_document_count,
        COUNT(*) FILTER (WHERE s.status = 'ACCEPTED')                 AS accepted_document_count,
        COUNT(*) FILTER (WHERE s.status LIKE 'PENDING%')              AS pending_document_count,
        SUM(CASE WHEN s.status = 'EXPIRED_CREDIT_LOST'
                 THEN d.total_tax_crc ELSE 0 END)                     AS credit_lost_crc
    FROM stg_documents d
    JOIN stg_deadline_status s USING (document_record_id)
    GROUP BY d.issuer_id
)
SELECT
    c.contributor_id,
    c.contributor_name,
    c.id_type,
    CASE c.id_type
        WHEN '01' THEN 'Física'
        WHEN '02' THEN 'Jurídica'
        ELSE 'Desconocido'
    END                                               AS id_type_name,
    c.sector,
    c.activity_code,
    c.role,
    COALESCE(i.document_count, 0)                     AS document_count,
    COALESCE(i.total_iva_crc, 0)                      AS total_iva_crc,
    i.first_document_date,
    i.last_document_date,
    ROUND(COALESCE(i.avg_arrival_lag_days, 0), 2)     AS avg_arrival_lag_days,
    COALESCE(o.accepted_document_count, 0)            AS accepted_document_count,
    COALESCE(o.pending_document_count, 0)             AS pending_document_count,
    COALESCE(o.expired_document_count, 0)             AS expired_document_count,
    COALESCE(o.credit_lost_crc, 0)                    AS credit_lost_crc,
    c.is_synthetic
FROM stg_contributors c
LEFT JOIN issued i   USING (contributor_id)
LEFT JOIN outcomes o USING (contributor_id);
