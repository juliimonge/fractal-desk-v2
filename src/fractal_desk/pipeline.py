"""End-to-end pipeline: generate -> assess deadlines -> validate -> build marts.

One command, one deterministic result:

    python -m fractal_desk.pipeline

Writes ``build/fractal_desk.duckdb`` plus a run report in JSON and Markdown. The
report is the source of every number quoted in the README — the README does not
contain a figure that was not produced by an actual run of this module.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from . import paths
from .business_calendar import load_calendar
from .deadline import (
    ACCEPTANCE_WINDOW_BUSINESS_DAYS,
    DEFAULT_AT_RISK_THRESHOLD_DAYS,
    DeadlineStatus,
    evaluate,
)
from .generator import GeneratorConfig, SyntheticDocumentGenerator
from .validation import validate_all_indexed
from .warehouse import Warehouse

# The as-of date the shipped run report was built against.
#
# Pinned rather than read from the clock, for two reasons.
#
# 1. Reproducibility. Statuses are a function of "today": a run tomorrow moves
#    documents from PENDING to EXPIRED and silently invalidates every figure in
#    the README. A pinned date means the documented numbers can be reproduced
#    from a clean clone at any time.
# 2. A populated at-risk queue. 2026-08-11 is two business days before
#    2026-08-12, the deadline for everything issued in July 2026. That is the
#    state the dashboard exists to show. Picking a date mid-window would leave
#    the primary view empty and demonstrate nothing — not because the engine is
#    wrong, but because at-risk is a narrow window by definition.
#
# Pass --as-of to move it and watch the queue drain or fill.
DEFAULT_AS_OF = date(2026, 8, 11)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"not serialisable: {type(obj)}")


def run(
    *,
    seed: int = 42,
    document_count: int = 2000,
    as_of: date = DEFAULT_AS_OF,
    at_risk_threshold_days: int = DEFAULT_AT_RISK_THRESHOLD_DAYS,
    observe_non_mandatory_pay_holidays: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    def log(message: str) -> None:
        if not quiet:
            print(message, flush=True)

    started = datetime.now()

    # --- 1. calendar ----------------------------------------------------
    calendar = load_calendar(
        observe_non_mandatory_pay_holidays=observe_non_mandatory_pay_holidays
    )
    log(
        f"[1/5] Calendar loaded: {calendar.describe()['holidays_observed']} observed "
        f"holidays, {calendar.coverage_start} .. {calendar.coverage_end}"
    )

    # --- 2. generate ----------------------------------------------------
    config = GeneratorConfig(document_count=document_count, seed=seed)
    generator = SyntheticDocumentGenerator(config, calendar)
    documents = generator.generate(as_of=as_of)
    log(
        f"[2/5] Generated {len(documents)} SYNTHETIC documents "
        f"({config.document_count} requested + duplicate-clave injections), seed={seed}"
    )

    # --- 3. deadline engine ---------------------------------------------
    from . import catalogs

    doc_types = catalogs.document_types()
    assessments = {}
    for record_id, document in enumerate(documents, start=1):
        doc_type = doc_types.get(document.document_type_code)
        if doc_type is None or not doc_type.enters_acceptance_workflow:
            continue  # no receiver confirmation obligation, so no deadline
        assessments[record_id] = evaluate(
            document.issue_date,
            calendar=calendar,
            as_of=as_of,
            accepted_on=document.accepted_date,
            at_risk_threshold_days=at_risk_threshold_days,
        )
    log(f"[3/5] Deadline engine assessed {len(assessments)} documents as of {as_of}")

    # --- 4. validation ---------------------------------------------------
    # Indexed by record position, not by clave: duplicate claves exist in this
    # dataset by design, so a clave-based join would attribute each copy's
    # findings to both copies.
    indexed_findings = validate_all_indexed(documents)
    log(f"[4/5] Validation produced {len(indexed_findings)} findings")

    # --- 5. warehouse ----------------------------------------------------
    contributors = [generator.receiver, *generator.issuers]
    with Warehouse() as warehouse:
        warehouse.load_raw(
            documents=documents,
            assessments=assessments,
            findings=indexed_findings,
            contributors=contributors,
            calendar=calendar,
        )
        model_runs = warehouse.run_models()
        log(
            f"[5/5] Built {len(model_runs)} SQL models "
            f"({', '.join(paths.SQL_LAYERS)}) -> {paths.WAREHOUSE_DB.name}"
        )
        report = _build_report(
            warehouse=warehouse,
            documents=documents,
            assessments=assessments,
            findings=indexed_findings,
            model_runs=model_runs,
            calendar=calendar,
            seed=seed,
            as_of=as_of,
            at_risk_threshold_days=at_risk_threshold_days,
            started=started,
        )

    paths.RUN_REPORT_JSON.write_text(
        json.dumps(report, indent=2, default=_json_default, ensure_ascii=False),
        encoding="utf-8",
    )
    paths.RUN_REPORT_MD.write_text(_report_markdown(report), encoding="utf-8")
    log(f"\nRun report: {paths.RUN_REPORT_MD}")
    return report


def _build_report(
    *,
    warehouse: Warehouse,
    documents: list,
    assessments: dict,
    findings: list,
    model_runs: list,
    calendar,
    seed: int,
    as_of: date,
    at_risk_threshold_days: int,
    started: datetime,
) -> dict[str, Any]:
    q = warehouse.query

    status_rows = q(
        """
        SELECT status, COUNT(*) AS n,
               SUM(iva_at_risk_crc) AS at_risk,
               SUM(iva_lost_crc) AS lost,
               SUM(iva_secured_crc) AS secured
        FROM fct_deadline_status GROUP BY status ORDER BY status
        """
    )
    rule_rows = q(
        """
        SELECT rule_id, ANY_VALUE(rule_name), ANY_VALUE(severity),
               COUNT(*) AS n, COUNT(DISTINCT document_record_id) AS docs
        FROM fct_validation_finding GROUP BY rule_id ORDER BY n DESC
        """
    )
    defect_rows = q(
        """
        WITH exploded AS (
            SELECT UNNEST(STRING_SPLIT(injected_defects, ',')) AS defect
            FROM fct_document WHERE injected_defects <> ''
        )
        SELECT defect, COUNT(*) AS n FROM exploded GROUP BY defect ORDER BY n DESC
        """
    )
    month_rows = q(
        """
        SELECT issue_month, COUNT(*) AS n, ANY_VALUE(deadline_date) AS deadline,
               COUNT(DISTINCT deadline_date) AS distinct_deadlines
        FROM fct_deadline_status GROUP BY issue_month ORDER BY issue_month
        """
    )

    return {
        "run": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round((datetime.now() - started).total_seconds(), 2),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "seed": seed,
            "as_of": as_of,
            "at_risk_threshold_business_days": at_risk_threshold_days,
            "acceptance_window_business_days": ACCEPTANCE_WINDOW_BUSINESS_DAYS,
            "all_data_synthetic": True,
        },
        "calendar": calendar.describe(),
        "counts": {
            "documents": len(documents),
            "document_lines": warehouse.scalar("SELECT COUNT(*) FROM stg_document_lines"),
            "contributors": warehouse.scalar("SELECT COUNT(*) FROM dim_contributor"),
            "documents_with_deadline": len(assessments),
            "documents_without_deadline": len(documents) - len(assessments),
            "distinct_claves": warehouse.scalar("SELECT COUNT(DISTINCT clave) FROM fct_document"),
            "duplicate_clave_records": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_document WHERE clave_is_duplicated"
            ),
            "validation_findings": len(findings),
            "documents_with_error": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_document WHERE has_blocking_error"
            ),
            "documents_clean": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_document WHERE finding_count = 0"
            ),
        },
        "deadline_status": [
            {
                "status": r[0],
                "documents": r[1],
                "iva_at_risk_crc": float(r[2] or 0),
                "iva_lost_crc": float(r[3] or 0),
                "iva_secured_crc": float(r[4] or 0),
            }
            for r in status_rows
        ],
        "headline": {
            "iva_at_risk_crc": float(
                warehouse.scalar("SELECT COALESCE(SUM(iva_at_risk_crc),0) FROM fct_deadline_status")
            ),
            "iva_lost_crc": float(
                warehouse.scalar("SELECT COALESCE(SUM(iva_lost_crc),0) FROM fct_deadline_status")
            ),
            "iva_secured_crc": float(
                warehouse.scalar("SELECT COALESCE(SUM(iva_secured_crc),0) FROM fct_deadline_status")
            ),
            "at_risk_documents": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_deadline_status WHERE status='PENDING_AT_RISK'"
            ),
            "expired_documents": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_deadline_status WHERE status='EXPIRED_CREDIT_LOST'"
            ),
            "accepted_late_documents": warehouse.scalar(
                "SELECT COUNT(*) FROM fct_deadline_status WHERE accepted_late"
            ),
            "acceptance_rate_closed_windows": float(
                warehouse.scalar(
                    """
                    SELECT ROUND(
                        100.0 * COUNT(*) FILTER (WHERE status='ACCEPTED') / NULLIF(COUNT(*),0), 2)
                    FROM fct_deadline_status WHERE deadline_date < as_of
                    """
                )
                or 0
            ),
            "iva_discrepancy_crc": float(
                warehouse.scalar(
                    "SELECT ROUND(COALESCE(SUM(ABS(iva_discrepancy_crc)),0),2) FROM fct_document"
                )
            ),
        },
        "validation_rules": [
            {"rule_id": r[0], "rule_name": r[1], "severity": r[2],
             "findings": r[3], "documents": r[4]}
            for r in rule_rows
        ],
        "injected_defects": [{"defect": r[0], "documents": r[1]} for r in defect_rows],
        "issue_months": [
            {"issue_month": r[0], "documents": r[1], "deadline": r[2],
             "distinct_deadlines": r[3]}
            for r in month_rows
        ],
        "models": [
            {"layer": m.layer, "model": m.name, "rows": m.row_count, "file": m.path.name}
            for m in model_runs
        ],
    }


def _report_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    counts = report["counts"]
    head = report["headline"]

    lines = [
        "# Run report",
        "",
        "**ALL DATA IN THIS REPORT IS SYNTHETIC.** No real invoice, taxpayer or",
        "filing is represented. Nothing was transmitted anywhere.",
        "",
        f"- Generated: `{run['generated_at']}`",
        f"- As-of date: `{run['as_of']}`",
        f"- Seed: `{run['seed']}` (output is deterministic for a given seed)",
        f"- Duration: {run['duration_seconds']}s",
        f"- Python {run['python']}",
        "",
        "## Volume",
        "",
        f"| Metric | Value |",
        f"|---|---:|",
        f"| Documents generated | {counts['documents']:,} |",
        f"| Document lines | {counts['document_lines']:,} |",
        f"| Synthetic contributors | {counts['contributors']:,} |",
        f"| Documents with an acceptance deadline | {counts['documents_with_deadline']:,} |",
        f"| Documents with no acceptance obligation | {counts['documents_without_deadline']:,} |",
        f"| Distinct claves | {counts['distinct_claves']:,} |",
        f"| Records carrying a duplicated clave | {counts['duplicate_clave_records']:,} |",
        f"| Validation findings | {counts['validation_findings']:,} |",
        f"| Documents with at least one ERROR | {counts['documents_with_error']:,} |",
        f"| Documents with no findings at all | {counts['documents_clean']:,} |",
        "",
        "## Deadline status",
        "",
        "| Status | Documents | IVA at risk (₡) | IVA lost (₡) | IVA secured (₡) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["deadline_status"]:
        lines.append(
            f"| {row['status']} | {row['documents']:,} | {row['iva_at_risk_crc']:,.2f} "
            f"| {row['iva_lost_crc']:,.2f} | {row['iva_secured_crc']:,.2f} |"
        )

    lines += [
        "",
        "## Headline",
        "",
        f"- IVA credit still recoverable (pending): **₡{head['iva_at_risk_crc']:,.2f}**",
        f"- IVA credit permanently lost: **₡{head['iva_lost_crc']:,.2f}**",
        f"- IVA credit secured: ₡{head['iva_secured_crc']:,.2f}",
        f"- Documents currently at risk: **{head['at_risk_documents']:,}**",
        f"- Documents expired: {head['expired_documents']:,}",
        f"- Confirmed but too late (counted as lost): {head['accepted_late_documents']:,}",
        f"- Acceptance rate on closed windows: {head['acceptance_rate_closed_windows']}%",
        f"- Absolute IVA discrepancy between headers and their lines: "
        f"₡{head['iva_discrepancy_crc']:,.2f}",
        "",
        "## Validation rules fired",
        "",
        "| Rule | Name | Severity | Findings | Documents |",
        "|---|---|---|---:|---:|",
    ]
    for rule in report["validation_rules"]:
        lines.append(
            f"| {rule['rule_id']} | {rule['rule_name']} | {rule['severity']} "
            f"| {rule['findings']:,} | {rule['documents']:,} |"
        )

    lines += ["", "## SQL models built", "", "| Layer | Model | Rows |", "|---|---|---:|"]
    for model in report["models"]:
        lines.append(f"| {model['layer']} | `{model['model']}` | {model['rows']:,} |")

    lines += [
        "",
        "## Deadline per issue month",
        "",
        "Every document issued in a month shares one deadline — the 8th business",
        "day of the following month. `distinct_deadlines` is 1 for every month,",
        "which is the engine demonstrating that property on real output.",
        "",
        "| Issue month | Documents | Deadline | Distinct deadlines |",
        "|---|---:|---|---:|",
    ]
    for month in report["issue_months"]:
        lines.append(
            f"| {month['issue_month']} | {month['documents']:,} "
            f"| {month['deadline']} | {month['distinct_deadlines']} |"
        )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the synthetic TRIBU-CR deadline warehouse end to end."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--documents", type=int, default=2000)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEFAULT_AS_OF,
        help="Date to evaluate deadlines against (YYYY-MM-DD). Pinned by default "
             "so documented numbers stay reproducible.",
    )
    parser.add_argument("--at-risk-days", type=int, default=DEFAULT_AT_RISK_THRESHOLD_DAYS)
    parser.add_argument(
        "--working-non-mandatory-holidays",
        action="store_true",
        help="Treat the three pago-no-obligatorio holidays as working days. "
             "Produces earlier deadlines. See business_calendar.py.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run(
        seed=args.seed,
        document_count=args.documents,
        as_of=args.as_of,
        at_risk_threshold_days=args.at_risk_days,
        observe_non_mandatory_pay_holidays=not args.working_non_mandatory_holidays,
        quiet=args.quiet,
    )

    if not args.quiet:
        head = report["headline"]
        print("\n" + "=" * 68)
        print("  ALL DATA SYNTHETIC — nothing was filed, signed or transmitted")
        print("=" * 68)
        print(f"  Documents:            {report['counts']['documents']:,}")
        print(f"  At risk now:          {head['at_risk_documents']:,} documents")
        print(f"  IVA recoverable:      ₡{head['iva_at_risk_crc']:,.2f}")
        print(f"  IVA already lost:     ₡{head['iva_lost_crc']:,.2f}")
        print(f"  Acceptance rate:      {head['acceptance_rate_closed_windows']}%")
        print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
