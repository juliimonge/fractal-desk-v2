"""Loaders for the versioned reference-data catalogues in ``data/``.

Every catalogue is a comment-headed CSV: lines starting with ``#`` carry
provenance and maintenance warnings and are stripped before parsing. Keeping the
provenance in the data file rather than in a wiki means the warning travels with
the data.

All loaders are cached, so a pipeline run reads each file once.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from . import paths


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a comment-headed CSV into a list of dicts.

    Blank lines and lines whose first non-whitespace character is ``#`` are
    dropped before the header is located, so the provenance block at the top of
    each catalogue is free-form.
    """
    with path.open(encoding="utf-8") as handle:
        lines = [
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        ]
    return list(csv.DictReader(lines))


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "t", "yes", "1"}


@dataclass(frozen=True)
class DocumentType:
    type_code: str
    name_es: str
    name_en: str
    requires_receiver: bool
    enters_acceptance_workflow: bool
    credit_sign: int


@dataclass(frozen=True)
class TaxRate:
    rate_code: str
    rate_percent: Decimal
    description: str
    grants_credit: bool


@dataclass(frozen=True)
class EconomicActivity:
    activity_code: str
    sector: str
    description: str
    is_placeholder: bool


@lru_cache(maxsize=1)
def document_types() -> dict[str, DocumentType]:
    rows = _read_csv(paths.DOCUMENT_TYPES_CSV)
    return {
        row["type_code"]: DocumentType(
            type_code=row["type_code"],
            name_es=row["name_es"],
            name_en=row["name_en"],
            requires_receiver=_as_bool(row["requires_receiver"]),
            enters_acceptance_workflow=_as_bool(row["enters_acceptance_workflow"]),
            credit_sign=int(row["credit_sign"]),
        )
        for row in rows
    }


@lru_cache(maxsize=1)
def tax_rates() -> dict[str, TaxRate]:
    rows = _read_csv(paths.TAX_RATES_CSV)
    return {
        row["rate_code"]: TaxRate(
            rate_code=row["rate_code"],
            rate_percent=Decimal(row["rate_percent"]),
            description=row["description"],
            grants_credit=_as_bool(row["grants_credit"]),
        )
        for row in rows
    }


@lru_cache(maxsize=1)
def units_of_measure() -> dict[str, str]:
    """Map unit code -> description. Deliberately a subset; see the CSV header."""
    rows = _read_csv(paths.UNITS_CSV)
    return {row["unit_code"]: row["description"] for row in rows}


@lru_cache(maxsize=1)
def economic_activities() -> dict[str, EconomicActivity]:
    rows = _read_csv(paths.ACTIVITIES_CSV)
    return {
        row["activity_code"]: EconomicActivity(
            activity_code=row["activity_code"],
            sector=row["sector"],
            description=row["description"],
            is_placeholder=_as_bool(row["is_placeholder"]),
        )
        for row in rows
    }


def activities_by_sector(sector: str) -> list[EconomicActivity]:
    return [a for a in economic_activities().values() if a.sector == sector]


def creditable_rate_codes() -> set[str]:
    return {code for code, rate in tax_rates().items() if rate.grants_credit}
