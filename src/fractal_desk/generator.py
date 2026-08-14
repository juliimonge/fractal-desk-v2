"""Synthetic document generator.

=============================================================================
EVERY DOCUMENT THIS MODULE PRODUCES IS FABRICATED. NOTHING HERE IS REAL.
=============================================================================
There is no input path into this module: it reads no files of invoices, connects
to nothing, and takes no identifiers from the caller. It manufactures documents
from a seeded pseudo-random stream and nothing else.

The safeguards that make that verifiable rather than merely claimed:

* **Identifiers.** Every synthetic taxpayer identifier begins ``999``. Costa
  Rica does not issue cédulas — física, jurídica, DIMEX or NITE — in that range,
  so no generated identifier can collide with a real taxpayer.
* **Names.** Every synthetic company name begins with the literal token ``SYN``.
  One grep separates fabricated names from real ones anywhere they end up.
* **Product codes.** CABYS codes are 13-digit placeholders in the ``9`` range;
  economic activity codes come from ``data/catalog_economic_activities.csv``,
  which is itself a placeholder file. Neither is a real Hacienda code.
* **The flag.** Every ``Document`` carries ``is_synthetic=True``. No code path in
  this repository sets it to anything else.
* **Exchange rates.** Plausible-looking but invented. They are not a rate
  anybody published on any date.

Determinism: given a seed, the output is byte-identical across runs. The numbers
quoted in the README come from a specific seed and can be reproduced.

HOW THE DEFECTS GET THERE
=========================
A dataset where every document is clean proves nothing about a validator. This
generator injects defects deliberately and records what it injected on the
document itself (``injected_defects``). The tests then assert the validator
found *that* defect — not merely that it found *a* defect, which a validator
that flags everything would also pass.

HOW THE STATUSES GET THERE
==========================
Deadline statuses are *not* planted. The generator simulates behaviour — when a
document arrived, whether anyone got to it, how long they took — and then the
deadline engine classifies the result. If the engine's arithmetic were wrong,
the status mix would be wrong too. Planting statuses would make the pipeline
agree with itself by construction and test nothing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from . import catalogs
from .business_calendar import BusinessCalendar
from .models import (
    Document,
    DocumentLine,
    build_clave,
    build_consecutivo,
)

# --------------------------------------------------------------------------
# Synthetic identity space. See the module docstring for why these ranges.
# --------------------------------------------------------------------------
SYNTHETIC_ID_PREFIX = "999"
SYNTHETIC_NAME_PREFIX = "SYN"

_GREEK = (
    "Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
    "Iota", "Kappa", "Lambda", "Omicron", "Sigma", "Tau", "Upsilon", "Omega",
)
_SUFFIX = ("S.A.", "S.R.L.", "Ltda.")

_SECTOR_NOUNS: dict[str, tuple[str, ...]] = {
    "real_estate": ("Inmobiliaria", "Propiedades", "Bienes Raíces"),
    "construction": ("Constructora", "Obras", "Materiales"),
    "hospitality": ("Hospedaje", "Gastronomía", "Turismo"),
    "professional_services": ("Consultores", "Asesores", "Servicios"),
    "other": ("Comercial", "Logística", "Suministros"),
}

_SECTOR_ITEMS: dict[str, tuple[str, ...]] = {
    "real_estate": (
        "Comisión por corretaje", "Administración mensual de propiedad",
        "Gestión de arrendamiento", "Avalúo de inmueble",
    ),
    "construction": (
        "Cemento gris", "Varilla de acero", "Mano de obra de albañilería",
        "Alquiler de encofrado", "Movimiento de tierra",
    ),
    "hospitality": (
        "Servicio de hospedaje", "Alimentos y bebidas", "Lavandería",
        "Tour guiado", "Transporte de huéspedes",
    ),
    "professional_services": (
        "Honorarios legales", "Servicios contables", "Consultoría de gestión",
        "Diseño arquitectónico", "Auditoría interna",
    ),
    "other": (
        "Suministros de oficina", "Servicio de transporte", "Mantenimiento general",
        "Producto de reventa",
    ),
}

_UNITS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "real_estate": ("Sp", "Unid", "Al", "Alc"),
    "construction": ("Unid", "kg", "m3", "m2", "h", "t"),
    "hospitality": ("d", "Unid", "Sp", "h"),
    "professional_services": ("Sp", "Spe", "h", "Unid"),
    "other": ("Unid", "kg", "km", "Sp"),
}

# Currency mix. Rates are invented; see module docstring.
_CURRENCIES = ("CRC", "CRC", "CRC", "CRC", "CRC", "CRC", "CRC", "USD", "USD", "EUR")
_SYNTHETIC_RATES: dict[str, tuple[float, float]] = {
    "CRC": (1.0, 1.0),
    "USD": (498.0, 532.0),
    "EUR": (545.0, 585.0),
}

# Document types that can arrive on the receiving side of a purchase ledger.
# Weighted: most received traffic is plain invoices.
_INBOUND_TYPES = ("01", "01", "01", "01", "01", "01", "01", "03", "02", "04")

DEFECT_LABELS = (
    "MISSING_ACTIVITY_CODE",
    "MALFORMED_ACTIVITY_CODE",
    "INVALID_UNIT_OF_MEASURE",
    "LINE_IVA_MISCALCULATED",
    "DOCUMENT_IVA_MISMATCH",
    "DOCUMENT_TOTAL_MISMATCH",
    "MALFORMED_CLAVE",
    "DUPLICATE_CLAVE",
    "MISSING_RECEIVER",
    "MISSING_EXCHANGE_RATE",
    "CLAVE_DATE_DISAGREEMENT",
    "CLAVE_TYPE_DISAGREEMENT",
    "LATE_ARRIVAL",
    "MONTH_BOUNDARY",
)


@dataclass(frozen=True)
class Contributor:
    """A synthetic taxpayer. Issuer or the receiving business."""

    contributor_id: str
    id_type: str  # 01 física, 02 jurídica
    name: str
    sector: str
    activity_code: str
    role: str  # issuer | receiver
    # Probability this supplier's documents get confirmed at all. Suppliers are
    # not uniform in practice: a landlord who sends one invoice a month gets
    # handled, a materials yard sending forty gets lost in the pile.
    handling_probability: float


@dataclass(frozen=True)
class GeneratorConfig:
    document_count: int = 2000
    issuer_count: int = 48
    seed: int = 42
    # TRIBU-CR went live on 2025-10-06; documents before that date would not have
    # travelled through the acceptance workflow this tool models. The end date
    # runs to just before the pinned as-of date so the dataset includes a
    # current, still-open month alongside ten closed ones.
    start_date: date = date(2025, 10, 6)
    end_date: date = date(2026, 8, 10)

    # Defect injection rates, as a share of generated documents.
    p_missing_activity_code: float = 0.030
    p_malformed_activity_code: float = 0.015
    p_invalid_unit: float = 0.040
    p_line_iva_miscalculated: float = 0.020
    p_document_iva_mismatch: float = 0.030
    p_document_total_mismatch: float = 0.020
    p_malformed_clave: float = 0.010
    # The clave carries a copy of the issue date and the document type. Badly
    # configured issuing software gets those out of step with the header it
    # built them from — a well-formed 50-digit clave that contradicts its own
    # document. Separate from p_malformed_clave because the failure is semantic,
    # not structural, and a length check will never catch it.
    p_clave_date_disagreement: float = 0.008
    p_clave_type_disagreement: float = 0.008
    p_duplicate_clave: float = 0.010
    p_missing_receiver: float = 0.010
    p_missing_exchange_rate: float = 0.010
    p_late_arrival: float = 0.120
    # Share of documents deliberately pushed onto the first or last two calendar
    # days of a month. Not a defect — a stress case for the deadline engine,
    # which is at its most fragile exactly at month boundaries.
    p_month_boundary: float = 0.080


class SyntheticDocumentGenerator:
    def __init__(self, config: GeneratorConfig, calendar: BusinessCalendar) -> None:
        self.config = config
        self.calendar = calendar
        self.rng = random.Random(config.seed)
        self.receiver = self._make_receiver()
        self.issuers = self._make_issuers()
        self._sequence = 0

    # ------------------------------------------------------------------
    # Synthetic parties
    # ------------------------------------------------------------------

    def _synthetic_id(self, ordinal: int) -> str:
        """A 10-digit identifier in the unissued ``999`` range."""
        return f"{SYNTHETIC_ID_PREFIX}{ordinal:07d}"

    def _make_receiver(self) -> Contributor:
        return Contributor(
            contributor_id=self._synthetic_id(1),
            id_type="02",
            name=f"{SYNTHETIC_NAME_PREFIX} Receptora Central S.R.L.",
            sector="professional_services",
            activity_code="940300",
            role="receiver",
            handling_probability=1.0,
        )

    def _make_issuers(self) -> list[Contributor]:
        issuers: list[Contributor] = []
        sectors = list(_SECTOR_NOUNS)
        for i in range(self.config.issuer_count):
            sector = sectors[i % len(sectors)]
            activity = self.rng.choice(catalogs.activities_by_sector(sector))
            name = (
                f"{SYNTHETIC_NAME_PREFIX} "
                f"{self.rng.choice(_GREEK)} "
                f"{self.rng.choice(_SECTOR_NOUNS[sector])} "
                f"{self.rng.choice(_SUFFIX)}"
            )
            issuers.append(
                Contributor(
                    contributor_id=self._synthetic_id(100 + i),
                    id_type="02" if self.rng.random() < 0.8 else "01",
                    name=name,
                    sector=sector,
                    activity_code=activity.activity_code,
                    role="issuer",
                    # Skewed high with a weak tail: most suppliers get handled
                    # most of the time, a few are chronically neglected. A
                    # uniform probability would produce a status mix with no
                    # structure for the dashboard to surface — and the point of
                    # dim_contributor is that the losses concentrate in a
                    # handful of suppliers rather than spreading evenly.
                    handling_probability=round(
                        min(0.995, max(0.60, self.rng.betavariate(16, 1.1))), 3
                    ),
                )
            )
        return issuers

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------

    def _random_issue_date(self) -> tuple[date, bool]:
        """Pick an issue date, sometimes forced onto a month boundary."""
        span = (self.config.end_date - self.config.start_date).days
        day = self.config.start_date + timedelta(days=self.rng.randint(0, span))

        if self.rng.random() >= self.config.p_month_boundary:
            return day, False

        # Force onto the first two or last two calendar days of that month.
        if self.rng.random() < 0.5:
            boundary = day.replace(day=1) + timedelta(days=self.rng.randint(0, 1))
        else:
            next_month = (
                date(day.year + 1, 1, 1)
                if day.month == 12
                else date(day.year, day.month + 1, 1)
            )
            boundary = next_month - timedelta(days=self.rng.randint(1, 2))

        if boundary < self.config.start_date or boundary > self.config.end_date:
            return day, False
        return boundary, True

    def _random_time(self) -> time:
        return time(self.rng.randint(7, 19), self.rng.randint(0, 59), self.rng.randint(0, 59))

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    def _make_lines(
        self,
        *,
        sector: str,
        currency: str,
        force_invalid_unit: bool,
        force_line_miscalc: bool,
    ) -> list[DocumentLine]:
        line_count = self.rng.choices([1, 2, 3, 4, 5, 6], weights=[30, 25, 18, 12, 9, 6])[0]
        bad_unit_line = self.rng.randrange(line_count) if force_invalid_unit else -1
        bad_math_line = self.rng.randrange(line_count) if force_line_miscalc else -1

        lines: list[DocumentLine] = []
        for i in range(line_count):
            unit = (
                self.rng.choice(("pcs", "box", "each", "UND", "m^2"))
                if i == bad_unit_line
                else self.rng.choice(_UNITS_BY_SECTOR[sector])
            )

            quantity = Decimal(self.rng.choice(("1", "1", "1", "2", "3", "4", "8", "12", "25")))
            if currency == "CRC":
                unit_price = Decimal(self.rng.randrange(5_000, 2_500_000, 500))
            else:
                unit_price = Decimal(self.rng.randrange(25, 9_000))

            gross = (quantity * unit_price).quantize(Decimal("0.01"))
            discount = (
                (gross * Decimal(self.rng.choice(("0.05", "0.10")))).quantize(Decimal("0.01"))
                if self.rng.random() < 0.15
                else Decimal("0.00")
            )
            subtotal = gross - discount

            # Most lines carry the 13% general rate; reduced and exempt rates
            # appear at realistic-ish minority weights.
            rate_code = self.rng.choices(
                ("08", "08", "08", "08", "08", "08", "04", "02", "01", "10"),
                weights=[40, 40, 40, 40, 40, 40, 8, 5, 4, 3],
            )[0]
            rate = catalogs.tax_rates()[rate_code].rate_percent
            tax = (subtotal * rate / Decimal(100)).quantize(Decimal("0.01"))

            if i == bad_math_line:
                # Wrong by a visible, non-rounding margin so the finding cannot
                # be confused with a quantisation artefact.
                tax = (tax + Decimal(self.rng.randrange(150, 9_000))).quantize(Decimal("0.01"))

            lines.append(
                DocumentLine(
                    line_number=i + 1,
                    cabys_code=f"9{self.rng.randrange(10**11, 10**12):012d}",
                    description=self.rng.choice(_SECTOR_ITEMS[sector]),
                    quantity=quantity,
                    unit_of_measure=unit,
                    unit_price=unit_price,
                    line_gross=gross,
                    discount=discount,
                    line_subtotal=subtotal,
                    tax_rate_code=rate_code,
                    tax_rate_percent=rate,
                    tax_amount=tax,
                    line_total=subtotal + tax,
                )
            )
        return lines

    # ------------------------------------------------------------------
    # Acceptance behaviour simulation
    # ------------------------------------------------------------------

    def _simulate_acceptance(
        self,
        *,
        issue_date: date,
        received_date: date,
        deadline_date: date,
        window_opens_on: date,
        handling_probability: float,
        has_errors: bool,
        as_of: date,
    ) -> datetime | None:
        """Decide if and when a confirmation was sent.

        Returns ``None`` for "no confirmation exists as of ``as_of``" — which
        covers both "nobody has got to it yet" and "nobody ever will". The
        deadline engine tells those apart from the dates; the generator does not
        need to.
        """
        # Documents with structural errors get chased rather than confirmed, so
        # they are both less likely to be handled and slower when they are.
        probability = handling_probability * (0.72 if has_errors else 1.0)
        if self.rng.random() > probability:
            return None

        # Work cannot start before the document arrives, and in practice the
        # confirmation goes out once the month's purchase ledger is being closed
        # — which is what the window opening represents.
        earliest = max(received_date, window_opens_on)

        # Most confirmations land inside the window; a tail runs past it. The
        # tail is what produces the late-acceptance case the engine has to treat
        # as a lost credit despite the source system saying "accepted".
        # Offsets 0..7 land inside the eight-business-day window; 9, 14 and 25
        # land outside it and produce the late-acceptance case — a confirmation
        # that exists but did not save the credit. Roughly one in twenty.
        offset = self.rng.choices(
            [0, 1, 2, 3, 4, 5, 6, 7, 9, 14, 25],
            weights=[18, 20, 17, 14, 11, 8, 6, 3, 2, 1, 1],
        )[0]
        try:
            accepted = self.calendar.add_business_days(earliest, offset)
        except Exception:  # calendar coverage exhausted at the tail
            return None

        # A confirmation cannot have happened in the future.
        if accepted > as_of:
            return None
        return datetime.combine(accepted, self._random_time())

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def generate(self, *, as_of: date) -> list[Document]:
        from .deadline import acceptance_deadline, acceptance_window_open

        cfg = self.config
        documents: list[Document] = []
        duplicate_pool: list[Document] = []

        for _ in range(cfg.document_count):
            issuer = self.rng.choice(self.issuers)
            issue_date, on_boundary = self._random_issue_date()
            issue_dt = datetime.combine(issue_date, self._random_time())

            type_code = self.rng.choice(_INBOUND_TYPES)
            doc_type = catalogs.document_types()[type_code]

            currency = self.rng.choice(_CURRENCIES)
            lo, hi = _SYNTHETIC_RATES[currency]
            exchange_rate = (
                Decimal("1")
                if currency == "CRC"
                else Decimal(str(round(self.rng.uniform(lo, hi), 5)))
            )

            defects: list[str] = []
            if on_boundary:
                defects.append("MONTH_BOUNDARY")

            force_invalid_unit = self.rng.random() < cfg.p_invalid_unit
            if force_invalid_unit:
                defects.append("INVALID_UNIT_OF_MEASURE")
            force_line_miscalc = self.rng.random() < cfg.p_line_iva_miscalculated
            if force_line_miscalc:
                defects.append("LINE_IVA_MISCALCULATED")

            lines = self._make_lines(
                sector=issuer.sector,
                currency=currency,
                force_invalid_unit=force_invalid_unit,
                force_line_miscalc=force_line_miscalc,
            )

            # --- totals, derived from the lines ---------------------------
            total_taxable = sum(
                (ln.line_subtotal for ln in lines if ln.tax_rate_percent > 0),
                Decimal("0"),
            )
            total_exempt = sum(
                (ln.line_subtotal for ln in lines if ln.tax_rate_percent == 0),
                Decimal("0"),
            )
            total_discount = sum((ln.discount for ln in lines), Decimal("0"))
            total_net = total_taxable + total_exempt
            total_tax = sum((ln.tax_amount for ln in lines), Decimal("0"))

            if self.rng.random() < cfg.p_document_iva_mismatch:
                # The stated document-level IVA disagrees with the sum of its
                # own lines. This is the defect that actually costs money in
                # practice: the number a bookkeeper keys into the return.
                total_tax += Decimal(self.rng.randrange(500, 45_000))
                defects.append("DOCUMENT_IVA_MISMATCH")

            total_document = total_net + total_tax
            if self.rng.random() < cfg.p_document_total_mismatch:
                total_document += Decimal(self.rng.randrange(100, 25_000))
                defects.append("DOCUMENT_TOTAL_MISMATCH")

            # --- activity code -------------------------------------------
            activity_code = issuer.activity_code
            if self.rng.random() < cfg.p_missing_activity_code:
                activity_code = ""
                defects.append("MISSING_ACTIVITY_CODE")
            elif self.rng.random() < cfg.p_malformed_activity_code:
                activity_code = activity_code[:4]  # four digits, not six
                defects.append("MALFORMED_ACTIVITY_CODE")

            # --- receiver -------------------------------------------------
            receiver_id: str | None = self.receiver.contributor_id
            receiver_name: str | None = self.receiver.name
            receiver_id_type: str | None = self.receiver.id_type
            if not doc_type.requires_receiver and self.rng.random() < 0.6:
                # Tiquetes legitimately have no receiver block.
                receiver_id = receiver_name = receiver_id_type = None
            elif doc_type.requires_receiver and self.rng.random() < cfg.p_missing_receiver:
                receiver_id = receiver_name = receiver_id_type = None
                defects.append("MISSING_RECEIVER")

            if currency != "CRC" and self.rng.random() < cfg.p_missing_exchange_rate:
                exchange_rate = Decimal("0")
                defects.append("MISSING_EXCHANGE_RATE")

            # --- clave ----------------------------------------------------
            self._sequence += 1
            consecutivo = build_consecutivo(
                branch="001",
                terminal="00001",
                type_code=type_code,
                sequence=self._sequence,
            )
            # Semantic corruptions: the clave stays 50 valid digits but stops
            # agreeing with the document it belongs to.
            clave_date = issue_date
            clave_consecutivo = consecutivo
            if self.rng.random() < cfg.p_clave_date_disagreement:
                clave_date = issue_date - timedelta(days=self.rng.randint(1, 5))
                defects.append("CLAVE_DATE_DISAGREEMENT")
            if self.rng.random() < cfg.p_clave_type_disagreement:
                wrong_type = self.rng.choice([t for t in ("01", "02", "03", "04") if t != type_code])
                clave_consecutivo = build_consecutivo(
                    branch="001", terminal="00001",
                    type_code=wrong_type, sequence=self._sequence,
                )
                defects.append("CLAVE_TYPE_DISAGREEMENT")

            clave = build_clave(
                issue_date=clave_date,
                issuer_id=issuer.contributor_id,
                consecutivo=clave_consecutivo,
                situation_code="1",
                security_code=f"{self.rng.randrange(10**7, 10**8)}",
            )
            if self.rng.random() < cfg.p_malformed_clave:
                # Truncate or corrupt. Both are seen in the wild from badly
                # configured issuing software.
                clave = clave[:48] if self.rng.random() < 0.5 else "X" + clave[1:]
                defects.append("MALFORMED_CLAVE")

            # --- arrival --------------------------------------------------
            if self.rng.random() < cfg.p_late_arrival:
                lag = self.rng.randint(20, 48)
                defects.append("LATE_ARRIVAL")
            else:
                lag = self.rng.randint(0, 3)
            received_dt = issue_dt + timedelta(days=lag)

            # --- acceptance -----------------------------------------------
            accepted_dt: datetime | None = None
            if doc_type.enters_acceptance_workflow:
                accepted_dt = self._simulate_acceptance(
                    issue_date=issue_date,
                    received_date=received_dt.date(),
                    deadline_date=acceptance_deadline(issue_date, self.calendar),
                    window_opens_on=acceptance_window_open(issue_date, self.calendar),
                    handling_probability=issuer.handling_probability,
                    has_errors=bool(
                        {"DOCUMENT_IVA_MISMATCH", "LINE_IVA_MISCALCULATED",
                         "MISSING_ACTIVITY_CODE", "MALFORMED_CLAVE"} & set(defects)
                    ),
                    as_of=as_of,
                )

            document = Document(
                clave=clave,
                consecutivo=consecutivo,
                document_type_code=type_code,
                issuer_id=issuer.contributor_id,
                issuer_id_type=issuer.id_type,
                issuer_name=issuer.name,
                receiver_id=receiver_id,
                receiver_id_type=receiver_id_type,
                receiver_name=receiver_name,
                issue_datetime=issue_dt,
                received_datetime=received_dt,
                economic_activity_code=activity_code,
                currency=currency,
                exchange_rate=exchange_rate,
                total_taxable=total_taxable,
                total_exempt=total_exempt,
                total_discount=total_discount,
                total_net=total_net,
                total_tax=total_tax,
                total_document=total_document,
                accepted_datetime=accepted_dt,
                lines=lines,
                injected_defects=sorted(set(defects)),
                is_synthetic=True,
            )
            documents.append(document)

            if self.rng.random() < cfg.p_duplicate_clave and len(documents) > 1:
                duplicate_pool.append(document)

        # --- duplicate claves ---------------------------------------------
        # Injected after the fact so the duplicate is a genuine second record
        # carrying an already-used clave, which is how it presents in reality: a
        # re-transmission or a double-import, not a generation collision.
        for original in duplicate_pool:
            twin = Document(**{**original.__dict__})
            twin.lines = list(original.lines)
            twin.injected_defects = sorted(set(original.injected_defects) | {"DUPLICATE_CLAVE"})
            documents.append(twin)
            # Mark the original too: uniqueness is a property of the pair, and a
            # report that flags only the second copy makes the first look clean.
            original.injected_defects = sorted(
                set(original.injected_defects) | {"DUPLICATE_CLAVE"}
            )

        self.rng.shuffle(documents)
        return documents


def generate_documents(
    *,
    calendar: BusinessCalendar,
    as_of: date,
    config: GeneratorConfig | None = None,
) -> tuple[list[Document], SyntheticDocumentGenerator]:
    generator = SyntheticDocumentGenerator(config or GeneratorConfig(), calendar)
    return generator.generate(as_of=as_of), generator
