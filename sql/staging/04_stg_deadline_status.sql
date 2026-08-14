-- ===========================================================================
-- MODEL:    stg_deadline_status
-- LAYER:    staging
-- GRAIN:    one row per document record that entered the acceptance workflow
-- SOURCE:   raw_deadline_status  (written by src/fractal_desk/deadline.py)
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- WHY THIS IS AN IMPORT, NOT A CALCULATION
--
-- The deadline is computed in Python and lands here as data. This model does
-- not re-derive it, and it must never start to. The reasons:
--
--   1. Business-day arithmetic against a holiday file is awkward in SQL and
--      easy to get subtly wrong at month boundaries — which is precisely where
--      this rule lives.
--   2. It has to be exhaustively unit-tested. Pytest against a Python function
--      is a better instrument for that than a SQL assertion suite.
--   3. Two implementations of a money-losing rule is one more than is
--      defensible. If the Python and the SQL ever disagreed, no one downstream
--      would know which had been used to build a number they were reading.
--
-- Note the row count here is LOWER than stg_documents: tiquetes electrónicos
-- carry no receiver confirmation obligation and so generate no deadline. Any
-- join to this model must be a LEFT JOIN.
--
-- CONTRACT
--   document_record_id       NOT NULL, unique
--   deadline_date            NOT NULL, always the 8th business day of the month
--                            after issue_month
--   status                   one of ACCEPTED, PENDING_SAFE, PENDING_AT_RISK,
--                            EXPIRED_CREDIT_LOST
--   business_days_remaining  >= 0
-- ===========================================================================

CREATE OR REPLACE VIEW stg_deadline_status AS
SELECT
    CAST(document_record_id AS BIGINT)                AS document_record_id,
    CAST(clave AS VARCHAR)                            AS clave,
    CAST(issue_date AS DATE)                          AS issue_date,
    CAST(window_opens_on AS DATE)                     AS window_opens_on,
    CAST(deadline_date AS DATE)                       AS deadline_date,
    CAST(status AS VARCHAR)                           AS status,
    CAST(business_days_remaining AS INTEGER)          AS business_days_remaining,
    CAST(accepted_on AS DATE)                         AS accepted_on,
    CAST(accepted_late AS BOOLEAN)                    AS accepted_late,
    CAST(as_of AS DATE)                               AS as_of
FROM raw_deadline_status;
