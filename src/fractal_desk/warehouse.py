"""DuckDB warehouse: load raw tables, then run the versioned SQL models in order.

DuckDB rather than Postgres because the whole point is that a clone runs with no
accounts, no server and no credentials. The database is a single file under
``build/`` and is disposable — one pipeline run rebuilds it exactly.

Execution order is the sorted filename order within each layer, and layers run
staging -> intermediate -> marts. The numeric prefixes are the dependency
declaration. A real dbt-style DAG would infer it from the refs; a numbered
manifest is the honest version of that for a project this size, and it fails
loudly (a missing table) rather than subtly if the order is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb

from . import catalogs, paths
from .business_calendar import BusinessCalendar
from .deadline import DeadlineAssessment
from .models import Document
from .validation import Finding


@dataclass
class ModelRun:
    layer: str
    name: str
    path: Path
    row_count: int


def _decimal(value: Decimal | None) -> float | None:
    """DuckDB's Python API takes Decimal fine, but None must stay None."""
    return value if value is not None else None


def _rows_documents(documents: Sequence[Document]) -> list[tuple[Any, ...]]:
    return [
        (
            i,
            d.clave,
            d.consecutivo,
            d.document_type_code,
            d.issuer_id,
            d.issuer_id_type,
            d.issuer_name,
            d.receiver_id,
            d.receiver_id_type,
            d.receiver_name,
            d.issue_datetime,
            d.received_datetime,
            d.accepted_datetime,
            d.economic_activity_code,
            d.currency,
            _decimal(d.exchange_rate),
            _decimal(d.total_taxable),
            _decimal(d.total_exempt),
            _decimal(d.total_discount),
            _decimal(d.total_net),
            _decimal(d.total_tax),
            _decimal(d.total_document),
            ",".join(d.injected_defects),
            d.is_synthetic,
        )
        for i, d in enumerate(documents, start=1)
    ]


def _rows_lines(documents: Sequence[Document]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for i, document in enumerate(documents, start=1):
        for line in document.lines:
            rows.append(
                (
                    i,
                    line.line_number,
                    line.cabys_code,
                    line.description,
                    _decimal(line.quantity),
                    line.unit_of_measure,
                    _decimal(line.unit_price),
                    _decimal(line.line_gross),
                    _decimal(line.discount),
                    _decimal(line.line_subtotal),
                    line.tax_rate_code,
                    _decimal(line.tax_rate_percent),
                    _decimal(line.tax_amount),
                    _decimal(line.line_total),
                )
            )
    return rows


class Warehouse:
    def __init__(self, db_path: Path | None = None) -> None:
        paths.ensure_build_dir()
        self.db_path = db_path or paths.WAREHOUSE_DB
        # Rebuild from scratch every run. An incremental warehouse over
        # regenerated synthetic data would only ever accumulate confusion.
        if self.db_path.exists():
            self.db_path.unlink()
        self.con = duckdb.connect(str(self.db_path))
        self.model_runs: list[ModelRun] = []

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Raw loads
    # ------------------------------------------------------------------

    def load_raw(
        self,
        *,
        documents: Sequence[Document],
        assessments: dict[int, DeadlineAssessment],
        findings: Sequence[tuple[int, Finding]],
        contributors: Iterable[Any],
        calendar: BusinessCalendar,
    ) -> None:
        con = self.con

        con.execute(
            """
            CREATE TABLE raw_documents (
                document_record_id BIGINT, clave VARCHAR, consecutivo VARCHAR,
                document_type_code VARCHAR, issuer_id VARCHAR, issuer_id_type VARCHAR,
                issuer_name VARCHAR, receiver_id VARCHAR, receiver_id_type VARCHAR,
                receiver_name VARCHAR, issue_datetime TIMESTAMP,
                received_datetime TIMESTAMP, accepted_datetime TIMESTAMP,
                economic_activity_code VARCHAR, currency VARCHAR,
                exchange_rate DECIMAL(18,5), total_taxable DECIMAL(18,5),
                total_exempt DECIMAL(18,5), total_discount DECIMAL(18,5),
                total_net DECIMAL(18,5), total_tax DECIMAL(18,5),
                total_document DECIMAL(18,5), injected_defects VARCHAR,
                is_synthetic BOOLEAN
            )
            """
        )
        con.executemany(
            "INSERT INTO raw_documents VALUES (" + ",".join(["?"] * 24) + ")",
            _rows_documents(documents),
        )

        con.execute(
            """
            CREATE TABLE raw_document_lines (
                document_record_id BIGINT, line_number INTEGER, cabys_code VARCHAR,
                description VARCHAR, quantity DECIMAL(18,5), unit_of_measure VARCHAR,
                unit_price DECIMAL(18,5), line_gross DECIMAL(18,5),
                discount DECIMAL(18,5), line_subtotal DECIMAL(18,5),
                tax_rate_code VARCHAR, tax_rate_percent DECIMAL(9,5),
                tax_amount DECIMAL(18,5), line_total DECIMAL(18,5)
            )
            """
        )
        con.executemany(
            "INSERT INTO raw_document_lines VALUES (" + ",".join(["?"] * 14) + ")",
            _rows_lines(documents),
        )

        con.execute(
            """
            CREATE TABLE raw_deadline_status (
                document_record_id BIGINT, clave VARCHAR, issue_date DATE,
                window_opens_on DATE, deadline_date DATE, status VARCHAR,
                business_days_remaining INTEGER, accepted_on DATE,
                accepted_late BOOLEAN, as_of DATE
            )
            """
        )
        con.executemany(
            "INSERT INTO raw_deadline_status VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    record_id,
                    documents[record_id - 1].clave,
                    a.issue_date,
                    a.window_opens_on,
                    a.deadline_date,
                    a.status.value,
                    a.business_days_remaining,
                    a.accepted_on,
                    a.accepted_late,
                    a.as_of,
                )
                for record_id, a in sorted(assessments.items())
            ],
        )

        con.execute(
            """
            CREATE TABLE raw_validation_findings (
                document_record_id BIGINT, clave VARCHAR, rule_id VARCHAR,
                rule_name VARCHAR, severity VARCHAR, message VARCHAR,
                line_number INTEGER, expected VARCHAR, actual VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO raw_validation_findings VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    record_id,
                    f.clave,
                    f.rule_id,
                    f.rule_name,
                    f.severity.value,
                    f.message,
                    f.line_number,
                    f.expected,
                    f.actual,
                )
                for record_id, f in findings
            ],
        )

        con.execute(
            """
            CREATE TABLE raw_contributors (
                contributor_id VARCHAR, id_type VARCHAR, name VARCHAR,
                sector VARCHAR, activity_code VARCHAR, role VARCHAR,
                handling_probability DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO raw_contributors VALUES (?,?,?,?,?,?,?)",
            [
                (
                    c.contributor_id,
                    c.id_type,
                    c.name,
                    c.sector,
                    c.activity_code,
                    c.role,
                    c.handling_probability,
                )
                for c in contributors
            ],
        )

        self._load_reference_tables(calendar)

    def _load_reference_tables(self, calendar: BusinessCalendar) -> None:
        """Reference catalogues into the warehouse, so the DB is self-describing.

        A warehouse that needs the CSV files alongside it to be interpretable is
        half a warehouse. Loading the catalogues means the build artefact carries
        its own reference data and the version it was built against.
        """
        con = self.con

        con.execute(
            """
            CREATE TABLE ref_document_types (
                type_code VARCHAR, name_es VARCHAR, name_en VARCHAR,
                requires_receiver BOOLEAN, enters_acceptance_workflow BOOLEAN,
                credit_sign INTEGER
            )
            """
        )
        con.executemany(
            "INSERT INTO ref_document_types VALUES (?,?,?,?,?,?)",
            [
                (t.type_code, t.name_es, t.name_en, t.requires_receiver,
                 t.enters_acceptance_workflow, t.credit_sign)
                for t in catalogs.document_types().values()
            ],
        )

        con.execute(
            """
            CREATE TABLE ref_tax_rates (
                rate_code VARCHAR, rate_percent DECIMAL(9,5),
                description VARCHAR, grants_credit BOOLEAN
            )
            """
        )
        con.executemany(
            "INSERT INTO ref_tax_rates VALUES (?,?,?,?)",
            [
                (r.rate_code, r.rate_percent, r.description, r.grants_credit)
                for r in catalogs.tax_rates().values()
            ],
        )

        con.execute("CREATE TABLE ref_units_of_measure (unit_code VARCHAR, description VARCHAR)")
        con.executemany(
            "INSERT INTO ref_units_of_measure VALUES (?,?)",
            list(catalogs.units_of_measure().items()),
        )

        con.execute(
            """
            CREATE TABLE ref_economic_activities (
                activity_code VARCHAR, sector VARCHAR, description VARCHAR,
                is_placeholder BOOLEAN
            )
            """
        )
        con.executemany(
            "INSERT INTO ref_economic_activities VALUES (?,?,?,?)",
            [
                (a.activity_code, a.sector, a.description, a.is_placeholder)
                for a in catalogs.economic_activities().values()
            ],
        )

        con.execute(
            """
            CREATE TABLE ref_holidays (
                holiday_date DATE, name_es VARCHAR, name_en VARCHAR,
                pay_type VARCHAR, moveable BOOLEAN, observed_as_non_business BOOLEAN
            )
            """
        )
        con.executemany(
            "INSERT INTO ref_holidays VALUES (?,?,?,?,?,?)",
            [
                (h.holiday_date, h.name_es, h.name_en, h.pay_type,
                 h.moveable, h.observed_as_non_business)
                for h in calendar.all_holidays
            ],
        )

    # ------------------------------------------------------------------
    # SQL models
    # ------------------------------------------------------------------

    def run_models(self) -> list[ModelRun]:
        """Execute every .sql file, staging -> intermediate -> marts."""
        for layer in paths.SQL_LAYERS:
            layer_dir = paths.SQL_DIR / layer
            for sql_path in sorted(layer_dir.glob("*.sql")):
                statement = sql_path.read_text(encoding="utf-8")
                self.con.execute(statement)
                name = self._model_name(sql_path)
                count = self.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                self.model_runs.append(
                    ModelRun(layer=layer, name=name, path=sql_path, row_count=count)
                )
        return self.model_runs

    @staticmethod
    def _model_name(sql_path: Path) -> str:
        """``03_fct_document.sql`` -> ``fct_document``."""
        stem = sql_path.stem
        return stem.split("_", 1)[1] if stem[0].isdigit() else stem

    # ------------------------------------------------------------------

    def query(self, sql: str, params: Sequence[Any] | None = None):
        return self.con.execute(sql, params or []).fetchall()

    def df(self, sql: str, params: Sequence[Any] | None = None):
        return self.con.execute(sql, params or []).df()

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        row = self.con.execute(sql, params or []).fetchone()
        return row[0] if row else None
