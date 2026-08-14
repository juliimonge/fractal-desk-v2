"""Validation layer.

Built on a known-good document that each test breaks in exactly one way, so a
failure points at one rule rather than at "something in validation". The
positive control (``test_clean_document_produces_no_findings``) matters as much
as the negative ones: a validator that flags everything catches every defect and
is useless.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from fractal_desk.models import (
    Document,
    DocumentLine,
    build_clave,
    build_consecutivo,
    parse_clave,
)
from fractal_desk.validation import (
    RULES,
    Severity,
    validate_all_indexed,
    validate_dataset,
    validate_document,
)


def make_line(**overrides) -> DocumentLine:
    defaults = dict(
        line_number=1,
        cabys_code="9123456789012",
        description="Servicios contables",
        quantity=Decimal("2"),
        unit_of_measure="Sp",
        unit_price=Decimal("100000"),
        line_gross=Decimal("200000"),
        discount=Decimal("0"),
        line_subtotal=Decimal("200000"),
        tax_rate_code="08",
        tax_rate_percent=Decimal("13.00"),
        tax_amount=Decimal("26000"),
        line_total=Decimal("226000"),
    )
    defaults.update(overrides)
    return DocumentLine(**defaults)


def make_document(**overrides) -> Document:
    issue = datetime(2026, 7, 15, 10, 30)
    consecutivo = build_consecutivo(
        branch="001", terminal="00001", type_code="01", sequence=1
    )
    defaults = dict(
        clave=build_clave(
            issue_date=issue.date(),
            issuer_id="9990000100",
            consecutivo=consecutivo,
            security_code="12345678",
        ),
        consecutivo=consecutivo,
        document_type_code="01",
        issuer_id="9990000100",
        issuer_id_type="02",
        issuer_name="SYN Alfa Consultores S.A.",
        receiver_id="9990000001",
        receiver_id_type="02",
        receiver_name="SYN Receptora Central S.R.L.",
        issue_datetime=issue,
        received_datetime=issue,
        economic_activity_code="940200",
        currency="CRC",
        exchange_rate=Decimal("1"),
        total_taxable=Decimal("200000"),
        total_exempt=Decimal("0"),
        total_discount=Decimal("0"),
        total_net=Decimal("200000"),
        total_tax=Decimal("26000"),
        total_document=Decimal("226000"),
        accepted_datetime=None,
        lines=[make_line()],
    )
    defaults.update(overrides)
    return Document(**defaults)


def rule_ids(findings) -> set[str]:
    return {f.rule_id for f in findings}


class TestPositiveControl:
    def test_clean_document_produces_no_findings(self):
        assert validate_document(make_document()) == []

    def test_every_registered_rule_has_metadata(self):
        for rule_id, (name, severity, description) in RULES.items():
            assert rule_id.startswith("V")
            assert name and description
            assert isinstance(severity, Severity)


class TestClaveRules:
    def test_short_clave_is_flagged(self):
        doc = make_document()
        doc.clave = doc.clave[:48]
        assert "V001" in rule_ids(validate_document(doc))

    def test_non_numeric_clave_is_flagged(self):
        doc = make_document()
        doc.clave = "X" + doc.clave[1:]
        assert "V002" in rule_ids(validate_document(doc))

    def test_wrong_country_code_is_flagged(self):
        doc = make_document()
        doc.clave = "507" + doc.clave[3:]
        assert "V003" in rule_ids(validate_document(doc))

    def test_clave_date_disagreeing_with_header_is_flagged(self):
        """A well-formed clave that contradicts its own document."""
        doc = make_document()
        doc.clave = build_clave(
            issue_date=doc.issue_datetime.date().replace(day=14),
            issuer_id=doc.issuer_id,
            consecutivo=doc.consecutivo,
            security_code="12345678",
        )
        findings = validate_document(doc)
        assert "V004" in rule_ids(findings)
        assert "V001" not in rule_ids(findings), "length must still be valid"

    def test_impossible_date_in_clave_is_flagged(self):
        doc = make_document()
        doc.clave = doc.clave[:3] + "3102" + doc.clave[7:]  # 31 February
        assert "V004" in rule_ids(validate_document(doc))

    def test_type_code_disagreeing_with_header_is_flagged(self):
        doc = make_document()
        wrong = build_consecutivo(branch="001", terminal="00001", type_code="03", sequence=1)
        doc.clave = build_clave(
            issue_date=doc.issue_datetime.date(),
            issuer_id=doc.issuer_id,
            consecutivo=wrong,
            security_code="12345678",
        )
        assert "V005" in rule_ids(validate_document(doc))


class TestClaveParsing:
    def test_roundtrip(self):
        doc = make_document()
        parsed = parse_clave(doc.clave)
        assert parsed is not None
        assert parsed.country_code == "506"
        assert parsed.issue_date == doc.issue_datetime.date()
        assert parsed.type_code == "01"
        assert parsed.issuer_id.lstrip("0") == doc.issuer_id

    @pytest.mark.parametrize("bad", ["", "506", "X" * 50, "1" * 49, "1" * 51])
    def test_unparseable_claves_return_none(self, bad):
        assert parse_clave(bad) is None

    def test_built_clave_is_fifty_digits(self):
        doc = make_document()
        assert len(doc.clave) == 50 and doc.clave.isdigit()


class TestUniqueness:
    def test_duplicate_clave_flags_every_copy(self):
        """Not just the second one — the first is equally untrustworthy."""
        doc_a = make_document()
        doc_b = make_document()
        findings = validate_dataset([doc_a, doc_b])
        assert len(findings) == 2
        assert all(f.rule_id == "V006" for f in findings)
        assert all(f.actual == "2" for f in findings)

    def test_distinct_claves_produce_nothing(self):
        doc_a = make_document()
        doc_b = make_document()
        doc_b.clave = doc_b.clave[:-1] + ("0" if doc_b.clave[-1] != "0" else "1")
        assert validate_dataset([doc_a, doc_b]) == []

    def test_findings_are_indexed_to_the_right_record(self):
        """Regression: findings must not be resolved back through the clave.

        Clave is not a key in this dataset. Attributing findings by clave gives
        each duplicate copy the other's findings too, inflating every count.
        """
        docs = [make_document(), make_document()]  # same clave
        indexed = validate_all_indexed(docs)
        v006 = [(i, f) for i, f in indexed if f.rule_id == "V006"]
        assert sorted(i for i, _ in v006) == [1, 2]
        assert len(indexed) == 2, "two clean documents should yield only the two V006 findings"


class TestActivityCode:
    def test_missing_activity_code(self):
        assert "V007" in rule_ids(validate_document(make_document(economic_activity_code="")))

    def test_four_digit_activity_code(self):
        assert "V008" in rule_ids(validate_document(make_document(economic_activity_code="9402")))

    def test_well_formed_but_unknown_code_is_a_warning_not_an_error(self):
        """The catalogue is a placeholder, so this cannot honestly be an ERROR."""
        findings = validate_document(make_document(economic_activity_code="123456"))
        v009 = [f for f in findings if f.rule_id == "V009"]
        assert len(v009) == 1
        assert v009[0].severity is Severity.WARNING


class TestReceiverAndCurrency:
    def test_invoice_without_receiver_is_an_error(self):
        doc = make_document(receiver_id=None, receiver_name=None, receiver_id_type=None)
        assert "V011" in rule_ids(validate_document(doc))

    def test_tiquete_without_receiver_is_fine(self):
        """Type 04 is issued to a final consumer and carries no receiver block."""
        consecutivo = build_consecutivo(
            branch="001", terminal="00001", type_code="04", sequence=1
        )
        doc = make_document(
            document_type_code="04",
            consecutivo=consecutivo,
            receiver_id=None, receiver_name=None, receiver_id_type=None,
            clave=build_clave(
                issue_date=datetime(2026, 7, 15).date(),
                issuer_id="9990000100",
                consecutivo=consecutivo,
                security_code="12345678",
            ),
        )
        assert "V011" not in rule_ids(validate_document(doc))

    def test_foreign_currency_without_a_rate(self):
        doc = make_document(currency="USD", exchange_rate=Decimal("0"))
        assert "V019" in rule_ids(validate_document(doc))

    def test_foreign_currency_with_a_rate_is_fine(self):
        doc = make_document(currency="USD", exchange_rate=Decimal("512.5"))
        assert "V019" not in rule_ids(validate_document(doc))


class TestLineRules:
    def test_unit_outside_the_catalogue(self):
        doc = make_document(lines=[make_line(unit_of_measure="pcs")])
        findings = validate_document(doc)
        assert "V012" in rule_ids(findings)
        assert next(f for f in findings if f.rule_id == "V012").line_number == 1

    def test_unknown_rate_code(self):
        doc = make_document(lines=[make_line(tax_rate_code="99")])
        assert "V013" in rule_ids(validate_document(doc))

    def test_rate_percent_disagreeing_with_its_code(self):
        doc = make_document(lines=[make_line(tax_rate_percent=Decimal("4.00"))])
        assert "V014" in rule_ids(validate_document(doc))

    def test_line_subtotal_not_reconciling(self):
        doc = make_document(lines=[make_line(line_subtotal=Decimal("199000"))])
        assert "V015" in rule_ids(validate_document(doc))

    def test_line_iva_not_reconciling(self):
        doc = make_document(lines=[make_line(tax_amount=Decimal("30000"))])
        assert "V016" in rule_ids(validate_document(doc))

    def test_short_cabys_code_is_a_warning(self):
        doc = make_document(lines=[make_line(cabys_code="123")])
        findings = [f for f in validate_document(doc) if f.rule_id == "V020"]
        assert findings and findings[0].severity is Severity.WARNING


class TestIvaReconciliation:
    """The rule with money attached, so it gets its own class."""

    def test_document_iva_must_equal_the_sum_of_its_lines(self):
        doc = make_document(total_tax=Decimal("30000"), total_document=Decimal("230000"))
        findings = validate_document(doc)
        assert "V017" in rule_ids(findings)
        v017 = next(f for f in findings if f.rule_id == "V017")
        assert v017.expected == "26000" and v017.actual == "30000"

    def test_reconciles_across_multiple_lines(self):
        lines = [
            make_line(line_number=1),
            make_line(line_number=2, line_subtotal=Decimal("100000"),
                      line_gross=Decimal("100000"), quantity=Decimal("1"),
                      unit_price=Decimal("100000"), tax_amount=Decimal("13000"),
                      line_total=Decimal("113000")),
        ]
        doc = make_document(
            lines=lines,
            total_taxable=Decimal("300000"), total_net=Decimal("300000"),
            total_tax=Decimal("39000"), total_document=Decimal("339000"),
        )
        assert validate_document(doc) == []

    def test_mixed_rates_reconcile(self):
        lines = [
            make_line(line_number=1),  # 13% on 200000 -> 26000
            make_line(line_number=2, tax_rate_code="04",
                      tax_rate_percent=Decimal("4.00"),
                      line_subtotal=Decimal("50000"), line_gross=Decimal("50000"),
                      quantity=Decimal("1"), unit_price=Decimal("50000"),
                      tax_amount=Decimal("2000"), line_total=Decimal("52000")),
            make_line(line_number=3, tax_rate_code="01",
                      tax_rate_percent=Decimal("0.00"),
                      line_subtotal=Decimal("10000"), line_gross=Decimal("10000"),
                      quantity=Decimal("1"), unit_price=Decimal("10000"),
                      tax_amount=Decimal("0"), line_total=Decimal("10000")),
        ]
        doc = make_document(
            lines=lines,
            total_taxable=Decimal("250000"), total_exempt=Decimal("10000"),
            total_net=Decimal("260000"), total_tax=Decimal("28000"),
            total_document=Decimal("288000"),
        )
        assert validate_document(doc) == []

    def test_sub_tolerance_rounding_does_not_trigger_a_finding(self):
        """Guards against a validator that fails on quantisation noise."""
        doc = make_document(total_tax=Decimal("26000.005"),
                            total_document=Decimal("226000.005"))
        assert "V017" not in rule_ids(validate_document(doc))

    def test_above_tolerance_does_trigger(self):
        doc = make_document(total_tax=Decimal("26000.50"),
                            total_document=Decimal("226000.50"))
        assert "V017" in rule_ids(validate_document(doc))

    def test_document_total_not_reconciling(self):
        assert "V018" in rule_ids(validate_document(make_document(total_document=Decimal("999999"))))

    def test_discount_is_applied_before_iva(self):
        line = make_line(
            discount=Decimal("20000"),
            line_subtotal=Decimal("180000"),
            tax_amount=Decimal("23400"),
            line_total=Decimal("203400"),
        )
        doc = make_document(
            lines=[line], total_taxable=Decimal("180000"), total_net=Decimal("180000"),
            total_discount=Decimal("20000"), total_tax=Decimal("23400"),
            total_document=Decimal("203400"),
        )
        assert validate_document(doc) == []


class TestFindingShape:
    def test_findings_carry_expected_and_actual(self):
        doc = make_document(total_tax=Decimal("30000"))
        finding = next(f for f in validate_document(doc) if f.rule_id == "V017")
        assert finding.expected and finding.actual
        assert finding.clave == doc.clave
        assert finding.severity is Severity.ERROR

    def test_line_findings_identify_the_line(self):
        doc = make_document(lines=[make_line(line_number=1), make_line(line_number=2, unit_of_measure="pcs")])
        finding = next(f for f in validate_document(doc) if f.rule_id == "V012")
        assert finding.line_number == 2
