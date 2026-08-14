"""Filesystem layout for the project.

Everything is resolved relative to the repository root so the project runs from
a fresh clone with no configuration and no environment variables.
"""

from __future__ import annotations

from pathlib import Path

# src/fractal_desk/paths.py -> src/fractal_desk -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
SQL_DIR = REPO_ROOT / "sql"
BUILD_DIR = REPO_ROOT / "build"
DOCS_DIR = REPO_ROOT / "docs"

# Reference data files (versioned, human-editable, comment-headed CSV).
HOLIDAYS_CSV = DATA_DIR / "cr_holidays.csv"
UNITS_CSV = DATA_DIR / "catalog_units_of_measure.csv"
TAX_RATES_CSV = DATA_DIR / "catalog_tax_rates.csv"
DOCUMENT_TYPES_CSV = DATA_DIR / "catalog_document_types.csv"
ACTIVITIES_CSV = DATA_DIR / "catalog_economic_activities.csv"

# Build artefacts. Everything under build/ is disposable and gitignored: a clean
# clone plus one pipeline run reproduces it exactly.
WAREHOUSE_DB = BUILD_DIR / "fractal_desk.duckdb"
RUN_REPORT_JSON = BUILD_DIR / "run_report.json"
RUN_REPORT_MD = BUILD_DIR / "run_report.md"

SQL_LAYERS = ("staging", "intermediate", "marts")


def ensure_build_dir() -> Path:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    return BUILD_DIR
