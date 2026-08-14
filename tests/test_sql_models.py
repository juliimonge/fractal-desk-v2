"""SQL model contracts.

Builds a real warehouse from a small synthetic batch once per module, then
asserts the contracts each model's header block declares. These are the tests
that catch a join fanning out, a grain changing, or a metric double-counting —
the class of bug that produces a plausible-looking wrong number rather than an
error.
"""

from __future__ import annotations

from datetime import date

import pytest

from fractal_desk import catalogs
from fractal_desk.business_calendar import load_calendar
from fractal_desk.deadline import evaluate
from fractal_desk.generator import GeneratorConfig, SyntheticDocumentGenerator
from fractal_desk.validation import validate_all_indexed
from fractal_desk.warehouse import Warehouse

AS_OF = date(2026, 8, 11)


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    calendar = load_calendar()
    generator = SyntheticDocumentGenerator(
        GeneratorConfig(document_count=600, seed=11), calendar
    )
    documents = generator.generate(as_of=AS_OF)

    doc_types = catalogs.document_types()
    assessments = {
        i: evaluate(d.issue_date, calendar=calendar, as_of=AS_OF,
                    accepted_on=d.accepted_date)
        for i, d in enumerate(documents, start=1)
        if doc_types[d.document_type_code].enters_acceptance_workflow
    }

    db_path = tmp_path_factory.mktemp("warehouse") / "test.duckdb"
    wh = Warehouse(db_path=db_path)
    wh.load_raw(
        documents=documents,
        assessments=assessments,
        findings=validate_all_indexed(documents),
        contributors=[generator.receiver, *generator.issuers],
        calendar=calendar,
    )
    wh.run_models()
    yield wh
    wh.close()


class TestModelsBuild:
    def test_every_layer_produced_models(self, warehouse):
        layers = {run.layer for run in warehouse.model_runs}
        assert layers == {"staging", "intermediate", "marts"}

    def test_expected_marts_exist(self, warehouse):
        built = {run.name for run in warehouse.model_runs}
        assert {
            "dim_contributor", "dim_document_type",
            "fct_document", "fct_deadline_status", "fct_validation_finding",
        } <= built

    def test_no_model_is_empty(self, warehouse):
        for run in warehouse.model_runs:
            assert run.row_count > 0, f"{run.name} produced no rows"


class TestGrain:
    """Grain is the contract most likely to break silently under a bad join."""

    def test_fct_document_is_one_row_per_record(self, warehouse):
        total, distinct = warehouse.query(
            "SELECT COUNT(*), COUNT(DISTINCT document_record_id) FROM fct_document"
        )[0]
        assert total == distinct

    def test_fct_document_does_not_fan_out_on_lines(self, warehouse):
        """A join to lines without aggregation would multiply rows."""
        docs = warehouse.scalar("SELECT COUNT(*) FROM fct_document")
        staged = warehouse.scalar("SELECT COUNT(*) FROM stg_documents")
        assert docs == staged

    def test_fct_deadline_status_is_one_row_per_record(self, warehouse):
        total, distinct = warehouse.query(
            "SELECT COUNT(*), COUNT(DISTINCT document_record_id) FROM fct_deadline_status"
        )[0]
        assert total == distinct

    def test_deadline_table_is_smaller_than_the_document_table(self, warehouse):
        """Only types with an acceptance obligation appear."""
        docs = warehouse.scalar("SELECT COUNT(*) FROM fct_document")
        deadlines = warehouse.scalar("SELECT COUNT(*) FROM fct_deadline_status")
        assert deadlines < docs

    def test_only_workflow_types_have_a_deadline(self, warehouse):
        leaked = warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status s
            JOIN dim_document_type t USING (document_type_code)
            WHERE NOT t.enters_acceptance_workflow
            """
        )
        assert leaked == 0

    def test_tiquetes_never_appear_in_the_deadline_table(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_deadline_status WHERE document_type_code = '04'"
        ) == 0

    def test_dim_contributor_is_one_row_per_contributor(self, warehouse):
        total, distinct = warehouse.query(
            "SELECT COUNT(*), COUNT(DISTINCT contributor_id) FROM dim_contributor"
        )[0]
        assert total == distinct


class TestReferentialIntegrity:
    def test_every_document_has_a_known_type(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_document f
            LEFT JOIN dim_document_type t USING (document_type_code)
            WHERE t.document_type_code IS NULL
            """
        ) == 0

    def test_every_deadline_row_has_a_document(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status s
            LEFT JOIN fct_document f USING (document_record_id)
            WHERE f.document_record_id IS NULL
            """
        ) == 0

    def test_every_finding_has_a_document(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_validation_finding v
            LEFT JOIN fct_document f USING (document_record_id)
            WHERE f.document_record_id IS NULL
            """
        ) == 0

    def test_every_issuer_is_in_the_contributor_dimension(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_document f
            LEFT JOIN dim_contributor c ON c.contributor_id = f.issuer_id
            WHERE c.contributor_id IS NULL
            """
        ) == 0


class TestDeadlineFactContract:
    def test_status_domain_is_closed(self, warehouse):
        statuses = {
            row[0] for row in warehouse.query("SELECT DISTINCT status FROM fct_deadline_status")
        }
        assert statuses <= {
            "ACCEPTED", "PENDING_SAFE", "PENDING_AT_RISK", "EXPIRED_CREDIT_LOST",
        }

    def test_days_remaining_is_never_negative(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_deadline_status WHERE business_days_remaining < 0"
        ) == 0

    def test_terminal_statuses_have_zero_days_remaining(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE status IN ('ACCEPTED', 'EXPIRED_CREDIT_LOST')
              AND business_days_remaining <> 0
            """
        ) == 0

    def test_deadline_always_falls_after_the_issue_month(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_deadline_status WHERE deadline_date <= issue_date"
        ) == 0

    def test_one_deadline_per_issue_month(self, warehouse):
        """The engine's defining property, asserted against built data."""
        offenders = warehouse.query(
            """
            SELECT issue_month, COUNT(DISTINCT deadline_date) AS n
            FROM fct_deadline_status GROUP BY issue_month HAVING n > 1
            """
        )
        assert offenders == []

    def test_window_opens_before_it_closes(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_deadline_status WHERE window_opens_on > deadline_date"
        ) == 0

    def test_at_risk_rows_are_within_the_threshold(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE status = 'PENDING_AT_RISK' AND business_days_remaining > 3
            """
        ) == 0

    def test_accepted_late_is_never_reported_as_accepted(self, warehouse):
        """Outcome, not activity."""
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_deadline_status WHERE accepted_late AND status = 'ACCEPTED'"
        ) == 0

    def test_expired_rows_are_past_their_deadline_or_accepted_late(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE status = 'EXPIRED_CREDIT_LOST'
              AND deadline_date >= as_of AND NOT accepted_late
            """
        ) == 0


class TestMoneyContract:
    """The columns a person would put in front of an accountant."""

    def test_a_row_contributes_to_at_most_one_money_bucket(self, warehouse):
        """at-risk, lost and secured must never double-count the same IVA."""
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE (CASE WHEN iva_at_risk_crc <> 0 THEN 1 ELSE 0 END
                 + CASE WHEN iva_lost_crc   <> 0 THEN 1 ELSE 0 END
                 + CASE WHEN iva_secured_crc<> 0 THEN 1 ELSE 0 END) > 1
            """
        ) == 0

    def test_at_risk_money_only_attaches_to_pending_rows(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE iva_at_risk_crc <> 0 AND status NOT IN ('PENDING_SAFE', 'PENDING_AT_RISK')
            """
        ) == 0

    def test_lost_money_only_attaches_to_expired_rows(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE iva_lost_crc <> 0 AND status <> 'EXPIRED_CREDIT_LOST'
            """
        ) == 0

    def test_colon_conversion_is_applied(self, warehouse):
        """A USD document's colón IVA must exceed its face IVA."""
        offenders = warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_document
            WHERE currency = 'USD' AND exchange_rate > 1 AND total_tax > 0
              AND total_tax_crc <= total_tax
            """
        )
        assert offenders == 0

    def test_crc_documents_are_not_converted(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_document
            WHERE currency = 'CRC' AND ABS(total_tax_crc - total_tax) > 0.01
            """
        ) == 0

    def test_credit_notes_reduce_rather_than_add(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM dim_document_type WHERE document_type_code = '03' AND credit_sign <> -1"
        ) == 0
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM fct_deadline_status
            WHERE document_type_code = '03' AND iva_secured_crc > 0
            """
        ) == 0


class TestDuplicateHandling:
    def test_duplicates_are_kept_not_silently_deduplicated(self, warehouse):
        records = warehouse.scalar("SELECT COUNT(*) FROM fct_document")
        claves = warehouse.scalar("SELECT COUNT(DISTINCT clave) FROM fct_document")
        assert records > claves

    def test_duplicate_flag_agrees_with_the_count(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_document WHERE clave_is_duplicated <> (clave_record_count > 1)"
        ) == 0

    def test_occurrence_numbering_starts_at_one_per_clave(self, warehouse):
        assert warehouse.scalar(
            """
            SELECT COUNT(*) FROM (
                SELECT clave, MIN(clave_occurrence) AS lo FROM fct_document GROUP BY clave
            ) WHERE lo <> 1
            """
        ) == 0

    def test_first_occurrence_filter_yields_a_clean_key(self, warehouse):
        total, distinct = warehouse.query(
            "SELECT COUNT(*), COUNT(DISTINCT clave) FROM fct_document WHERE clave_occurrence = 1"
        )[0]
        assert total == distinct


class TestValidationFactContract:
    def test_severity_domain_is_closed(self, warehouse):
        severities = {
            row[0] for row in warehouse.query("SELECT DISTINCT severity FROM fct_validation_finding")
        }
        assert severities <= {"ERROR", "WARNING", "INFO"}

    def test_error_count_matches_the_findings(self, warehouse):
        assert warehouse.scalar(
            """
            WITH counted AS (
                SELECT document_record_id, COUNT(*) FILTER (WHERE severity='ERROR') AS n
                FROM fct_validation_finding GROUP BY document_record_id
            )
            SELECT COUNT(*) FROM fct_document f
            LEFT JOIN counted c USING (document_record_id)
            WHERE f.error_count <> COALESCE(c.n, 0)
            """
        ) == 0

    def test_blocking_error_flag_agrees_with_the_count(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM fct_document WHERE has_blocking_error <> (error_count > 0)"
        ) == 0

    def test_findings_are_not_duplicated_per_document(self, warehouse):
        """Regression: findings attributed by clave would double up on duplicates."""
        offenders = warehouse.query(
            """
            SELECT document_record_id, rule_id, COALESCE(line_number, -1) AS ln, COUNT(*) AS n
            FROM fct_validation_finding
            GROUP BY 1, 2, 3 HAVING n > 1
            """
        )
        assert offenders == []


class TestSyntheticFlags:
    def test_every_mart_row_is_flagged_synthetic(self, warehouse):
        for table in ("fct_document", "fct_deadline_status", "fct_validation_finding", "dim_contributor"):
            assert warehouse.scalar(f"SELECT COUNT(*) FROM {table} WHERE NOT is_synthetic") == 0

    def test_every_contributor_id_is_in_the_unissued_range(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM dim_contributor WHERE contributor_id NOT LIKE '999%'"
        ) == 0

    def test_every_contributor_name_is_prefixed(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM dim_contributor WHERE contributor_name NOT LIKE 'SYN %'"
        ) == 0


class TestReferenceTables:
    def test_holiday_table_is_loaded(self, warehouse):
        assert warehouse.scalar("SELECT COUNT(*) FROM ref_holidays") == 36

    def test_catalogues_travel_with_the_warehouse(self, warehouse):
        """The build artefact should be interpretable without the CSV files."""
        for table in ("ref_document_types", "ref_tax_rates", "ref_units_of_measure",
                      "ref_economic_activities", "ref_holidays"):
            assert warehouse.scalar(f"SELECT COUNT(*) FROM {table}") > 0

    def test_activity_catalogue_is_marked_placeholder(self, warehouse):
        assert warehouse.scalar(
            "SELECT COUNT(*) FROM ref_economic_activities WHERE NOT is_placeholder"
        ) == 0
