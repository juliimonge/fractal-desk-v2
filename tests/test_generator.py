"""Synthetic generator.

Two things under test here. First, that the safety properties hold on every
document — synthetic identifiers, synthetic names, the flag — because those are
claims the README makes and a claim nobody checks is a claim that rots. Second,
that the injected defects are actually present and actually caught, so the
validation numbers in the run report mean what they say.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fractal_desk.generator import (
    SYNTHETIC_ID_PREFIX,
    SYNTHETIC_NAME_PREFIX,
    GeneratorConfig,
    SyntheticDocumentGenerator,
)
from fractal_desk.validation import validate_all

AS_OF = date(2026, 8, 11)


@pytest.fixture(scope="module")
def small_batch(request):
    from fractal_desk.business_calendar import load_calendar

    calendar = load_calendar()
    generator = SyntheticDocumentGenerator(
        GeneratorConfig(document_count=400, seed=7), calendar
    )
    return generator.generate(as_of=AS_OF), generator


class TestSyntheticSafety:
    """The properties that make "synthetic data only" verifiable rather than asserted."""

    def test_every_document_is_flagged_synthetic(self, small_batch):
        documents, _ = small_batch
        assert all(d.is_synthetic for d in documents)

    def test_every_identifier_is_in_the_unissued_999_range(self, small_batch):
        documents, _ = small_batch
        for document in documents:
            assert document.issuer_id.startswith(SYNTHETIC_ID_PREFIX)
            if document.receiver_id:
                assert document.receiver_id.startswith(SYNTHETIC_ID_PREFIX)

    def test_every_company_name_is_prefixed(self, small_batch):
        documents, _ = small_batch
        for document in documents:
            assert document.issuer_name.startswith(SYNTHETIC_NAME_PREFIX)
            if document.receiver_name:
                assert document.receiver_name.startswith(SYNTHETIC_NAME_PREFIX)

    def test_activity_codes_come_from_the_placeholder_catalogue(self, small_batch):
        from fractal_desk import catalogs

        documents, _ = small_batch
        placeholders = set(catalogs.economic_activities())
        for document in documents:
            code = document.economic_activity_code
            if code and len(code) == 6:
                assert code in placeholders
                assert catalogs.economic_activities()[code].is_placeholder


class TestDeterminism:
    def test_same_seed_produces_identical_output(self):
        from fractal_desk.business_calendar import load_calendar

        calendar = load_calendar()
        config = GeneratorConfig(document_count=120, seed=99)
        a = SyntheticDocumentGenerator(config, calendar).generate(as_of=AS_OF)
        b = SyntheticDocumentGenerator(config, calendar).generate(as_of=AS_OF)
        assert [d.clave for d in a] == [d.clave for d in b]
        assert [d.total_tax for d in a] == [d.total_tax for d in b]
        assert [d.accepted_datetime for d in a] == [d.accepted_datetime for d in b]

    def test_different_seeds_produce_different_output(self):
        from fractal_desk.business_calendar import load_calendar

        calendar = load_calendar()
        a = SyntheticDocumentGenerator(
            GeneratorConfig(document_count=120, seed=1), calendar
        ).generate(as_of=AS_OF)
        b = SyntheticDocumentGenerator(
            GeneratorConfig(document_count=120, seed=2), calendar
        ).generate(as_of=AS_OF)
        assert [d.clave for d in a] != [d.clave for d in b]


class TestShape:
    def test_requested_count_is_the_floor_not_the_ceiling(self, small_batch):
        """Duplicate-clave injection adds records after the main loop."""
        documents, _ = small_batch
        assert len(documents) >= 400

    def test_every_document_has_at_least_one_line(self, small_batch):
        documents, _ = small_batch
        assert all(len(d.lines) >= 1 for d in documents)

    def test_issue_dates_stay_inside_the_configured_window(self, small_batch):
        documents, generator = small_batch
        for document in documents:
            assert generator.config.start_date <= document.issue_date <= generator.config.end_date

    def test_no_acceptance_is_dated_in_the_future(self, small_batch):
        """A confirmation cannot have happened after the as-of date."""
        documents, _ = small_batch
        for document in documents:
            if document.accepted_date:
                assert document.accepted_date <= AS_OF

    def test_documents_always_arrive_on_or_after_issue(self, small_batch):
        documents, _ = small_batch
        assert all(d.received_date >= d.issue_date for d in documents)

    def test_tiquetes_never_get_an_acceptance(self, small_batch):
        """Type 04 carries no receiver confirmation obligation."""
        documents, _ = small_batch
        for document in documents:
            if document.document_type_code == "04":
                assert document.accepted_datetime is None

    def test_money_is_decimal_not_float(self, small_batch):
        documents, _ = small_batch
        document = documents[0]
        assert isinstance(document.total_tax, Decimal)
        assert isinstance(document.lines[0].tax_amount, Decimal)


class TestDefectInjection:
    """Injected defects must be present, and the validator must catch them."""

    def test_all_expected_defect_types_appear(self, small_batch):
        documents, _ = small_batch
        seen = {d for doc in documents for d in doc.injected_defects}
        expected = {
            "MISSING_ACTIVITY_CODE", "MALFORMED_ACTIVITY_CODE",
            "INVALID_UNIT_OF_MEASURE", "LINE_IVA_MISCALCULATED",
            "DOCUMENT_IVA_MISMATCH", "DOCUMENT_TOTAL_MISMATCH",
            "MALFORMED_CLAVE", "DUPLICATE_CLAVE", "MISSING_RECEIVER",
            "LATE_ARRIVAL", "MONTH_BOUNDARY",
        }
        assert expected <= seen, f"missing: {expected - seen}"

    def test_clean_documents_still_dominate(self, small_batch):
        """A dataset that is mostly broken tests nothing about a validator."""
        documents, _ = small_batch
        clean = [d for d in documents if not d.injected_defects]
        assert len(clean) / len(documents) > 0.5

    @pytest.mark.parametrize(
        "defect,rule_id",
        [
            ("MISSING_ACTIVITY_CODE", "V007"),
            ("MALFORMED_ACTIVITY_CODE", "V008"),
            ("INVALID_UNIT_OF_MEASURE", "V012"),
            ("LINE_IVA_MISCALCULATED", "V016"),
            ("DOCUMENT_IVA_MISMATCH", "V017"),
            ("DOCUMENT_TOTAL_MISMATCH", "V018"),
            ("MISSING_RECEIVER", "V011"),
            ("DUPLICATE_CLAVE", "V006"),
        ],
    )
    def test_each_injected_defect_is_caught_by_its_rule(self, small_batch, defect, rule_id):
        """Asserts the validator found THAT defect, not merely A defect."""
        documents, _ = small_batch
        affected = [d for d in documents if defect in d.injected_defects]
        assert affected, f"generator produced no {defect} in this batch"

        findings = validate_all(documents)
        flagged = {f.clave for f in findings if f.rule_id == rule_id}
        for document in affected:
            assert document.clave in flagged, (
                f"{defect} on {document.clave} was not caught by {rule_id}"
            )

    def test_month_boundary_documents_land_on_a_boundary(self, small_batch):
        import calendar as stdlib_calendar

        documents, _ = small_batch
        for document in documents:
            if "MONTH_BOUNDARY" not in document.injected_defects:
                continue
            day = document.issue_date.day
            last = stdlib_calendar.monthrange(document.issue_date.year, document.issue_date.month)[1]
            assert day <= 2 or day >= last - 1

    def test_late_arrivals_arrive_late(self, small_batch):
        documents, _ = small_batch
        late = [d for d in documents if "LATE_ARRIVAL" in d.injected_defects]
        assert late
        assert all((d.received_date - d.issue_date).days >= 20 for d in late)

    def test_duplicate_claves_are_flagged_on_both_copies(self, small_batch):
        documents, _ = small_batch
        duplicated = [d for d in documents if "DUPLICATE_CLAVE" in d.injected_defects]
        assert duplicated
        from collections import Counter

        counts = Counter(d.clave for d in documents)
        for document in duplicated:
            assert counts[document.clave] >= 2


class TestContributors:
    def test_exactly_one_receiver(self, small_batch):
        _, generator = small_batch
        assert generator.receiver.role == "receiver"
        assert all(i.role == "issuer" for i in generator.issuers)

    def test_handling_probability_is_a_probability(self, small_batch):
        _, generator = small_batch
        assert all(0.0 <= i.handling_probability <= 1.0 for i in generator.issuers)

    def test_issuers_span_every_sector(self, small_batch):
        _, generator = small_batch
        sectors = {i.sector for i in generator.issuers}
        assert len(sectors) >= 4
