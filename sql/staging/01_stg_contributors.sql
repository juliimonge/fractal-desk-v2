-- ===========================================================================
-- MODEL:    stg_contributors
-- LAYER:    staging
-- GRAIN:    one row per synthetic taxpayer (issuer or receiver)
-- SOURCE:   raw_contributors
-- VERSION:  1.0.0
-- ---------------------------------------------------------------------------
-- CHANGELOG
--   1.0.0  Initial model.
-- ---------------------------------------------------------------------------
-- Staging does three things and nothing else: rename to the project's
-- conventions, cast to the intended types, and trim. No joins, no business
-- logic, no filtering. Anything that needs a decision belongs downstream, so
-- that "the number is wrong" always has one obvious place to start looking.
--
-- CONTRACT
--   contributor_id  NOT NULL, unique, always begins '999' (synthetic range)
--   role            one of 'issuer', 'receiver'
-- ===========================================================================

CREATE OR REPLACE VIEW stg_contributors AS
SELECT
    CAST(contributor_id AS VARCHAR)                   AS contributor_id,
    CAST(id_type AS VARCHAR)                          AS id_type,
    TRIM(CAST(name AS VARCHAR))                       AS contributor_name,
    CAST(sector AS VARCHAR)                           AS sector,
    CAST(activity_code AS VARCHAR)                    AS activity_code,
    CAST(role AS VARCHAR)                             AS role,
    CAST(handling_probability AS DOUBLE)              AS handling_probability,
    -- Carried explicitly rather than inferred. Every row in this project is
    -- synthetic and the warehouse should say so in its own columns, not rely on
    -- a reader knowing which database they opened.
    TRUE                                              AS is_synthetic
FROM raw_contributors;
