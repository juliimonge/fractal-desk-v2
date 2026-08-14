"""Document model on the v4.4 shape, plus clave numérica construction/parsing.

The model is a flattened, Python-native view of the fields the deadline engine
and the validation layer actually need. It is not a full v4.4 XML binding — this
project never parses or emits a real document, so a faithful binding of every
optional element would be weight without purpose. Fields that carry a validation
rule or feed a mart are here; the rest are not.

CLAVE NUMÉRICA
==============
The clave is the 50-digit identifier every Costa Rican electronic document
carries. Its layout is positional:

    ┌────────────┬────────┬──────────────────────────────────────────────┐
    │ positions  │ digits │ meaning                                       │
    ├────────────┼────────┼──────────────────────────────────────────────┤
    │  1 –  3    │   3    │ country code, always 506                      │
    │  4 –  5    │   2    │ issue day                                     │
    │  6 –  7    │   2    │ issue month                                   │
    │  8 –  9    │   2    │ issue year, two digits                        │
    │ 10 – 21    │  12    │ issuer identification, zero-padded            │
    │ 22 – 41    │  20    │ consecutivo numérico                          │
    │ 42         │   1    │ situación (1 normal, 2 contingencia, 3 sin    │
    │            │        │ internet)                                     │
    │ 43 – 50    │   8    │ security code                                 │
    └────────────┴────────┴──────────────────────────────────────────────┘

and the 20-digit consecutivo is itself positional:

    ┌────────────┬────────┬──────────────────────────────────────────────┐
    │  1 –  3    │   3    │ casa matriz / sucursal                        │
    │  4 –  8    │   5    │ terminal                                      │
    │  9 – 10    │   2    │ document type code                            │
    │ 11 – 20    │  10    │ sequence number                               │
    └────────────┴────────┴──────────────────────────────────────────────┘

This structure is what makes the clave worth validating rather than treating as
an opaque string: the issue date and the document type are encoded inside it, so
a document whose clave disagrees with its own header is detectably malformed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

COUNTRY_CODE = "506"
CLAVE_LENGTH = 50
CONSECUTIVO_LENGTH = 20

# Money is Decimal everywhere. Costa Rican amounts are colones with satangs that
# nobody uses, but IVA at 13% on an odd base produces long tails, and the
# validation layer compares a stated total against a recomputed one. Doing that
# in float means the reconciliation rule fails on rounding noise and passes on
# real errors — the exact opposite of useful.
MONEY_QUANTUM = Decimal("0.00001")  # v4.4 permits five decimal places
RECONCILIATION_TOLERANCE = Decimal("0.01")  # one céntimo of slack per comparison


def build_consecutivo(
    *,
    branch: str,
    terminal: str,
    type_code: str,
    sequence: int,
) -> str:
    """Assemble the 20-digit consecutivo numérico."""
    return f"{branch:>03}{terminal:>05}{type_code:>02}{sequence:010d}"


def build_clave(
    *,
    issue_date: date,
    issuer_id: str,
    consecutivo: str,
    situation_code: str = "1",
    security_code: str = "00000000",
) -> str:
    """Assemble a 50-digit clave numérica from its parts."""
    return (
        f"{COUNTRY_CODE}"
        f"{issue_date.day:02d}{issue_date.month:02d}{issue_date.year % 100:02d}"
        f"{issuer_id:0>12}"
        f"{consecutivo:0>20}"
        f"{situation_code:1}"
        f"{security_code:0>8}"
    )


@dataclass(frozen=True)
class ParsedClave:
    """The fields recoverable from a well-formed clave.

    ``issue_date`` is ``None`` when the embedded day/month/year do not form a
    real calendar date (e.g. the 31st of a 30-day month), which is itself a
    finding rather than an exception.
    """

    country_code: str
    issue_date: date | None
    issuer_id: str
    consecutivo: str
    situation_code: str
    security_code: str
    branch: str
    terminal: str
    type_code: str
    sequence: str


def parse_clave(clave: str) -> ParsedClave | None:
    """Split a clave into its positional fields, or ``None`` if unparseable.

    Returns ``None`` only for the two structural failures that make every other
    field meaningless: wrong length, or a non-digit character. Semantic problems
    (wrong country code, a date that does not exist, a type code that disagrees
    with the header) are returned as parsed values for the validation layer to
    judge — parsing and validating are different jobs.
    """
    if len(clave) != CLAVE_LENGTH or not clave.isdigit():
        return None

    day, month, year = int(clave[3:5]), int(clave[5:7]), int(clave[7:9])
    try:
        # Two-digit years in the clave are unambiguous in practice: the format
        # postdates 2018 and this project's window is 2025-2027.
        issue_date: date | None = date(2000 + year, month, day)
    except ValueError:
        issue_date = None

    consecutivo = clave[21:41]
    return ParsedClave(
        country_code=clave[0:3],
        issue_date=issue_date,
        issuer_id=clave[9:21],
        consecutivo=consecutivo,
        situation_code=clave[41],
        security_code=clave[42:50],
        branch=consecutivo[0:3],
        terminal=consecutivo[3:8],
        type_code=consecutivo[8:10],
        sequence=consecutivo[10:20],
    )


@dataclass
class DocumentLine:
    """One LineaDetalle."""

    line_number: int
    cabys_code: str
    description: str
    quantity: Decimal
    unit_of_measure: str
    unit_price: Decimal
    line_gross: Decimal  # cantidad * precioUnitario
    discount: Decimal
    line_subtotal: Decimal  # base for IVA: gross - discount
    tax_rate_code: str
    tax_rate_percent: Decimal
    tax_amount: Decimal
    line_total: Decimal  # subtotal + tax


@dataclass
class Document:
    """One received electronic document, flattened.

    ``is_synthetic`` is carried on the record itself rather than assumed from
    context. It is written into the warehouse, surfaced in the dashboard, and
    asserted in the tests. There is no code path in this repo that can produce a
    Document with ``is_synthetic=False``.
    """

    clave: str
    consecutivo: str
    document_type_code: str

    issuer_id: str
    issuer_id_type: str
    issuer_name: str
    receiver_id: str | None
    receiver_id_type: str | None
    receiver_name: str | None

    issue_datetime: datetime
    received_datetime: datetime
    economic_activity_code: str

    currency: str
    exchange_rate: Decimal

    total_taxable: Decimal
    total_exempt: Decimal
    total_discount: Decimal
    total_net: Decimal
    total_tax: Decimal
    total_document: Decimal

    accepted_datetime: datetime | None
    lines: list[DocumentLine] = field(default_factory=list)

    # Populated by the generator; the label the defect was injected under. Kept
    # on the record so tests can assert that an injected defect is actually
    # caught, rather than assuming the validator found it for the right reason.
    injected_defects: list[str] = field(default_factory=list)

    is_synthetic: bool = True

    @property
    def issue_date(self) -> date:
        return self.issue_datetime.date()

    @property
    def received_date(self) -> date:
        return self.received_datetime.date()

    @property
    def accepted_date(self) -> date | None:
        return self.accepted_datetime.date() if self.accepted_datetime else None

    @property
    def total_tax_crc(self) -> Decimal:
        """IVA restated in colones, for summing across currencies.

        Every at-risk figure in the dashboard is a colón amount, so a USD
        invoice has to be converted before it can join the total. The exchange
        rate travels on the document (v4.4 carries TipoCambio per document), so
        this is the rate that applied on the issue date, not today's.
        """
        return self.total_tax * self.exchange_rate
