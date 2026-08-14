"""Structural validation against v4.4 expectations.

SCOPE, STATED HONESTLY
======================
This validates the *structure and internal consistency* of a document. It does
not and cannot validate whether a document is legally correct. It has no view on
whether the rate applied to a line is the rate that product is entitled to,
whether the issuer is registered for the activity claimed, or whether the
transaction happened. Those questions need Hacienda's catalogues and Hacienda's
registry; this repo has placeholders for both, on purpose.

What it does answer: given a document, are the fields that must be present
present, do they have the right shape, and does the arithmetic close?

SEVERITY
========
``ERROR``    The document is structurally wrong. In a real workflow this is the
             set you rechazar or send back to the supplier.
``WARNING``  Suspicious, or checked against a catalogue this repo only ships a
             placeholder for. A WARNING never means "ignore me" — it means the
             finding is real but the reference data behind it is not
             authoritative here.
``INFO``     Recorded for context, not a defect.

Rule V007 (activity code in catalogue) is a WARNING rather than an ERROR for
exactly that reason: ``data/catalog_economic_activities.csv`` is a placeholder
file. Making it an ERROR would produce a validator that is loudly confident on
the strength of data it invented.

ARITHMETIC
==========
Every monetary comparison is Decimal with an explicit tolerance
(``RECONCILIATION_TOLERANCE``, one céntimo). Two amounts that differ by less
than that are treated as equal, because v4.4 permits five decimal places and
different issuing systems quantise at different points. Two amounts that differ
by more are a finding, and the finding carries both numbers so the person
reading it does not have to take the validator's word for it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from . import catalogs
from .models import (
    CLAVE_LENGTH,
    COUNTRY_CODE,
    RECONCILIATION_TOLERANCE,
    Document,
    parse_clave,
)

ACTIVITY_CODE_LENGTH = 6
CABYS_CODE_LENGTH = 13


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    rule_name: str
    severity: Severity
    clave: str
    message: str
    line_number: int | None = None
    expected: str | None = None
    actual: str | None = None


# Registry of rule metadata, kept separate from the checks so it can be dumped
# into the data dictionary and the dashboard without importing the logic.
RULES: dict[str, tuple[str, Severity, str]] = {
    "V001": ("CLAVE_LENGTH", Severity.ERROR, "Clave numérica must be exactly 50 digits"),
    "V002": ("CLAVE_NUMERIC", Severity.ERROR, "Clave numérica must contain digits only"),
    "V003": ("CLAVE_COUNTRY_CODE", Severity.ERROR, "Clave must begin with country code 506"),
    "V004": ("CLAVE_DATE_AGREEMENT", Severity.ERROR, "Date embedded in clave must match FechaEmision"),
    "V005": ("CLAVE_TYPE_AGREEMENT", Severity.ERROR, "Type code in consecutivo must match TipoDocumento"),
    "V006": ("CLAVE_UNIQUE", Severity.ERROR, "Clave numérica must be unique across the dataset"),
    "V007": ("ACTIVITY_CODE_PRESENT", Severity.ERROR, "CodigoActividad is required"),
    "V008": ("ACTIVITY_CODE_FORMAT", Severity.ERROR, "CodigoActividad must be 6 digits"),
    "V009": ("ACTIVITY_CODE_IN_CATALOG", Severity.WARNING, "CodigoActividad should exist in the activity catalogue"),
    "V010": ("DOCUMENT_TYPE_KNOWN", Severity.ERROR, "TipoDocumento must exist in the document type catalogue"),
    "V011": ("RECEIVER_PRESENT", Severity.ERROR, "Receptor is required for this document type"),
    "V012": ("UNIT_OF_MEASURE_IN_CATALOG", Severity.ERROR, "UnidadMedida must exist in the units catalogue"),
    "V013": ("TAX_RATE_CODE_KNOWN", Severity.ERROR, "CodigoTarifa must exist in the rate catalogue"),
    "V014": ("TAX_RATE_MATCHES_CODE", Severity.ERROR, "Stated tarifa must match the percentage its code represents"),
    "V015": ("LINE_SUBTOTAL_ARITHMETIC", Severity.ERROR, "Line subtotal must equal quantity x unit price - discount"),
    "V016": ("LINE_IVA_ARITHMETIC", Severity.ERROR, "Line IVA must equal subtotal x rate"),
    "V017": ("DOCUMENT_IVA_RECONCILES", Severity.ERROR, "TotalImpuesto must equal the sum of line IVA"),
    "V018": ("DOCUMENT_TOTAL_RECONCILES", Severity.ERROR, "TotalComprobante must equal net total plus IVA"),
    "V019": ("EXCHANGE_RATE_PRESENT", Severity.ERROR, "Non-CRC documents require a positive TipoCambio"),
    "V020": ("CABYS_CODE_FORMAT", Severity.WARNING, "CABYS code should be 13 digits"),
}


def _finding(rule_id: str, clave: str, message: str, **kwargs) -> Finding:
    name, severity, _ = RULES[rule_id]
    return Finding(
        rule_id=rule_id,
        rule_name=name,
        severity=severity,
        clave=clave,
        message=message,
        **kwargs,
    )


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= RECONCILIATION_TOLERANCE


# ---------------------------------------------------------------------------
# Per-document rules
# ---------------------------------------------------------------------------


def validate_document(document: Document) -> list[Finding]:
    """Run every per-document rule. Dataset-wide rules live in :func:`validate_dataset`."""
    findings: list[Finding] = []
    clave = document.clave

    # --- clave structure ------------------------------------------------
    if len(clave) != CLAVE_LENGTH:
        findings.append(
            _finding("V001", clave, f"Clave is {len(clave)} characters, expected {CLAVE_LENGTH}",
                     expected=str(CLAVE_LENGTH), actual=str(len(clave)))
        )
    if not clave.isdigit():
        findings.append(_finding("V002", clave, "Clave contains non-digit characters"))

    parsed = parse_clave(clave)
    if parsed is not None:
        if parsed.country_code != COUNTRY_CODE:
            findings.append(
                _finding("V003", clave, f"Country code is {parsed.country_code}",
                         expected=COUNTRY_CODE, actual=parsed.country_code)
            )
        # The clave carries its own issue date. If it disagrees with the header,
        # one of the two is wrong and the document cannot be trusted — this is a
        # cheap, high-signal check that catches issuing software building the
        # clave from the wrong clock.
        if parsed.issue_date is None:
            findings.append(_finding("V004", clave, "Date embedded in clave is not a real date"))
        elif parsed.issue_date != document.issue_date:
            findings.append(
                _finding("V004", clave,
                         "Date in clave disagrees with FechaEmision",
                         expected=document.issue_date.isoformat(),
                         actual=parsed.issue_date.isoformat())
            )
        if parsed.type_code != document.document_type_code:
            findings.append(
                _finding("V005", clave, "Type code in consecutivo disagrees with TipoDocumento",
                         expected=document.document_type_code, actual=parsed.type_code)
            )

    # --- header fields ---------------------------------------------------
    activity = document.economic_activity_code
    if not activity.strip():
        findings.append(_finding("V007", clave, "CodigoActividad is empty"))
    else:
        if len(activity) != ACTIVITY_CODE_LENGTH or not activity.isdigit():
            findings.append(
                _finding("V008", clave, f"CodigoActividad '{activity}' is not 6 digits",
                         expected=f"{ACTIVITY_CODE_LENGTH} digits", actual=activity)
            )
        elif activity not in catalogs.economic_activities():
            findings.append(
                _finding("V009", clave, f"CodigoActividad '{activity}' is not in the catalogue",
                         actual=activity)
            )

    doc_types = catalogs.document_types()
    if document.document_type_code not in doc_types:
        findings.append(
            _finding("V010", clave, f"Unknown TipoDocumento '{document.document_type_code}'",
                     actual=document.document_type_code)
        )
    elif doc_types[document.document_type_code].requires_receiver and not document.receiver_id:
        findings.append(
            _finding("V011", clave,
                     f"Receptor missing on a {doc_types[document.document_type_code].name_es}")
        )

    if document.currency != "CRC" and document.exchange_rate <= 0:
        findings.append(
            _finding("V019", clave,
                     f"Currency is {document.currency} but TipoCambio is {document.exchange_rate}",
                     actual=str(document.exchange_rate))
        )

    # --- line rules ------------------------------------------------------
    units = catalogs.units_of_measure()
    rates = catalogs.tax_rates()
    line_tax_total = Decimal("0")

    for line in document.lines:
        line_tax_total += line.tax_amount

        if line.unit_of_measure not in units:
            findings.append(
                _finding("V012", clave, f"Unit '{line.unit_of_measure}' is not in the catalogue",
                         line_number=line.line_number, actual=line.unit_of_measure)
            )

        if line.tax_rate_code not in rates:
            findings.append(
                _finding("V013", clave, f"Unknown CodigoTarifa '{line.tax_rate_code}'",
                         line_number=line.line_number, actual=line.tax_rate_code)
            )
        elif rates[line.tax_rate_code].rate_percent != line.tax_rate_percent:
            findings.append(
                _finding("V014", clave,
                         f"Tarifa {line.tax_rate_percent}% does not match code {line.tax_rate_code}",
                         line_number=line.line_number,
                         expected=str(rates[line.tax_rate_code].rate_percent),
                         actual=str(line.tax_rate_percent))
            )

        expected_subtotal = line.quantity * line.unit_price - line.discount
        if not _close(expected_subtotal, line.line_subtotal):
            findings.append(
                _finding("V015", clave, "Line subtotal does not reconcile",
                         line_number=line.line_number,
                         expected=str(expected_subtotal), actual=str(line.line_subtotal))
            )

        expected_tax = (line.line_subtotal * line.tax_rate_percent / Decimal(100))
        if not _close(expected_tax, line.tax_amount):
            findings.append(
                _finding("V016", clave, "Line IVA does not reconcile against the stated rate",
                         line_number=line.line_number,
                         expected=str(expected_tax.quantize(Decimal("0.01"))),
                         actual=str(line.tax_amount))
            )

        if len(line.cabys_code) != CABYS_CODE_LENGTH or not line.cabys_code.isdigit():
            findings.append(
                _finding("V020", clave, f"CABYS code '{line.cabys_code}' is not 13 digits",
                         line_number=line.line_number, actual=line.cabys_code)
            )

    # --- document totals -------------------------------------------------
    # The document-level IVA is the number that ends up in the return. If it
    # disagrees with the lines it was supposedly computed from, the return is
    # wrong regardless of which of the two is right.
    if not _close(line_tax_total, document.total_tax):
        findings.append(
            _finding("V017", clave, "TotalImpuesto disagrees with the sum of line IVA",
                     expected=str(line_tax_total), actual=str(document.total_tax))
        )

    expected_total = document.total_net + document.total_tax
    if not _close(expected_total, document.total_document):
        findings.append(
            _finding("V018", clave, "TotalComprobante does not equal net total plus IVA",
                     expected=str(expected_total), actual=str(document.total_document))
        )

    return findings


# ---------------------------------------------------------------------------
# Dataset-wide rules
# ---------------------------------------------------------------------------


def validate_dataset_indexed(
    documents: list[Document],
) -> list[tuple[int, Finding]]:
    """Rules that can only be evaluated across the whole set.

    Uniqueness is the only one today. It is flagged on *every* copy, not just
    the second: a duplicate clave means neither record can be trusted on its own,
    and reporting only the later arrival makes the earlier one look clean.

    Findings are paired with their 1-based record index rather than looked up by
    clave downstream. Clave is not a key in this dataset — that is the whole
    point of the rule — so resolving a finding back to a record through it would
    fan every duplicate's findings across both copies and inflate the counts.
    """
    findings: list[tuple[int, Finding]] = []
    counts = Counter(d.clave for d in documents)

    for index, document in enumerate(documents, start=1):
        if counts[document.clave] > 1:
            findings.append(
                (
                    index,
                    _finding("V006", document.clave,
                             f"Clave appears {counts[document.clave]} times in the dataset",
                             expected="1", actual=str(counts[document.clave])),
                )
            )
    return findings


def validate_all_indexed(documents: list[Document]) -> list[tuple[int, Finding]]:
    """Every finding, paired with the 1-based index of the record it belongs to."""
    findings: list[tuple[int, Finding]] = []
    for index, document in enumerate(documents, start=1):
        for finding in validate_document(document):
            findings.append((index, finding))
    findings.extend(validate_dataset_indexed(documents))
    return findings


def validate_dataset(documents: list[Document]) -> list[Finding]:
    return [finding for _, finding in validate_dataset_indexed(documents)]


def validate_all(documents: list[Document]) -> list[Finding]:
    return [finding for _, finding in validate_all_indexed(documents)]


def summarise(findings: list[Finding]) -> dict[str, int]:
    """Counts by rule id, for the run report."""
    return dict(Counter(f.rule_id for f in findings))
