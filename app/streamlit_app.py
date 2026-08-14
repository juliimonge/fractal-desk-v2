"""Dashboard.

The primary view answers ONE question: what must be accepted today or this week
before the IVA credit is lost. Everything else on the page is secondary and sits
below it or behind a tab.

That constraint is the design. A deadline tool that opens on a grid of charts
makes the reader hunt for the thing that is on fire. This one opens on the
at-risk queue, sorted by deadline, priced in colones, and it says how many
business days are left in words a person can act on.

ALL DATA IS SYNTHETIC. The banner saying so is not dismissible and is rendered
before anything else on every tab.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from fractal_desk import paths  # noqa: E402

st.set_page_config(
    page_title="fractal desk v2 — TRIBU-CR deadline engine",
    page_icon="🕗",
    layout="wide",
)

# --------------------------------------------------------------------------
# Palette. Status colours are load-bearing: they have to survive being glanced
# at, and the at-risk / expired distinction must be obvious without reading.
# --------------------------------------------------------------------------
C_AT_RISK = "#d1495b"
C_EXPIRED = "#6b2737"
C_SAFE = "#457b9d"
C_ACCEPTED = "#2a9d8f"
STATUS_COLOURS = {
    "PENDING_AT_RISK": C_AT_RISK,
    "EXPIRED_CREDIT_LOST": C_EXPIRED,
    "PENDING_SAFE": C_SAFE,
    "ACCEPTED": C_ACCEPTED,
}
STATUS_ORDER = ["PENDING_AT_RISK", "PENDING_SAFE", "ACCEPTED", "EXPIRED_CREDIT_LOST"]


@st.cache_resource
def connect() -> duckdb.DuckDBPyConnection:
    if not paths.WAREHOUSE_DB.exists():
        st.error(
            f"No warehouse at `{paths.WAREHOUSE_DB}`.\n\n"
            "Build it first:\n\n    ./run.sh\n\nor\n\n    python -m fractal_desk.pipeline"
        )
        st.stop()
    return duckdb.connect(str(paths.WAREHOUSE_DB), read_only=True)


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    return connect().execute(sql).df()


def colones(value: float | None) -> str:
    return f"₡{(value or 0):,.0f}"


def synthetic_banner() -> None:
    """Rendered at the top of every tab. Not dismissible, by design."""
    st.markdown(
        f"""
        <div style="background:{C_AT_RISK};color:#fff;padding:0.65rem 1rem;
                    border-radius:6px;margin-bottom:1rem;font-weight:600;
                    letter-spacing:0.01em;">
          ⚠️ ALL DATA ON THIS PAGE IS SYNTHETIC — generated, not real.
          No real invoice, taxpayer or filing is represented. Nothing is filed,
          signed or transmitted. This is not a tax compliance product.
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------

synthetic_banner()

meta = q("SELECT MAX(as_of) AS as_of FROM fct_deadline_status")
AS_OF: date = pd.to_datetime(meta["as_of"].iloc[0]).date()

st.title("Acceptance deadline engine")
st.caption(
    f"Received electronic documents · TRIBU-CR · evaluated as of **{AS_OF:%d %B %Y}** · "
    "a received document must be accepted within the first 8 business days of the "
    "month following its issue date, or the IVA credit is permanently lost."
)

# --------------------------------------------------------------------------
# The one question
# --------------------------------------------------------------------------

head = q(
    """
    SELECT
        COUNT(*) FILTER (WHERE status = 'PENDING_AT_RISK')                     AS at_risk_docs,
        COUNT(*) FILTER (WHERE due_today_or_next)                              AS due_now_docs,
        COUNT(*) FILTER (WHERE status = 'EXPIRED_CREDIT_LOST')                 AS expired_docs,
        COUNT(*) FILTER (WHERE accepted_late)                                  AS late_docs,
        COALESCE(SUM(iva_at_risk_crc)  FILTER (WHERE status='PENDING_AT_RISK'), 0) AS at_risk_crc,
        COALESCE(SUM(iva_at_risk_crc), 0)                                      AS pending_crc,
        COALESCE(SUM(iva_lost_crc), 0)                                         AS lost_crc,
        COALESCE(SUM(iva_secured_crc), 0)                                      AS secured_crc,
        MIN(deadline_date) FILTER (WHERE status LIKE 'PENDING%')               AS next_deadline
    FROM fct_deadline_status
    """
).iloc[0]

if head["at_risk_docs"]:
    st.markdown(
        f"""
        <div style="background:{C_AT_RISK}18;border-left:6px solid {C_AT_RISK};
                    padding:1.1rem 1.3rem;border-radius:4px;margin:0.5rem 0 1.5rem;">
          <div style="font-size:1.55rem;font-weight:700;color:{C_AT_RISK};">
            {int(head['at_risk_docs'])} documents must be accepted by
            {pd.to_datetime(head['next_deadline']):%d %B}
          </div>
          <div style="font-size:1.05rem;margin-top:0.35rem;">
            {colones(head['at_risk_crc'])} of IVA credit is lost if they are not.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.success(
        f"Nothing is at risk as of {AS_OF:%d %B %Y}. "
        f"The next pending deadline is {pd.to_datetime(head['next_deadline']):%d %B %Y}."
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric("At risk now", f"{int(head['at_risk_docs'])}", colones(head["at_risk_crc"]),
          delta_color="off", help="3 or fewer business days remain.")
c2.metric("Recoverable total", colones(head["pending_crc"]),
          f"{int(head['at_risk_docs'])} at risk + safe", delta_color="off",
          help="All pending documents — credit that can still be secured.")
c3.metric("Already lost", colones(head["lost_crc"]),
          f"{int(head['expired_docs'])} documents", delta_color="off",
          help="Window closed unanswered, or answered too late.")
c4.metric("Secured", colones(head["secured_crc"]),
          f"incl. {int(head['late_docs'])} answered too late", delta_color="off",
          help="Accepted on or before the deadline.")

st.divider()

tab_queue, tab_lost, tab_quality, tab_trend, tab_engine = st.tabs(
    ["🔥 Action queue", "💸 Lost credit", "🔍 Validation", "📈 Acceptance over time", "⚙️ The engine"]
)

# --------------------------------------------------------------------------
# 1. Action queue — the primary view
# --------------------------------------------------------------------------

with tab_queue:
    st.subheader("What has to be accepted, soonest first")
    st.caption(
        "Sorted by deadline, then by IVA at stake. Everything on this list can "
        "still be saved."
    )

    only_at_risk = st.toggle("At-risk only (3 or fewer business days)", value=True)
    status_filter = (
        "status = 'PENDING_AT_RISK'" if only_at_risk else "status LIKE 'PENDING%'"
    )

    queue = q(
        f"""
        SELECT
            deadline_date          AS "Deadline",
            business_days_remaining AS "Business days left",
            status                 AS "Status",
            clave                  AS "Clave",
            document_type_name_es  AS "Type",
            issuer_name            AS "Issuer",
            issue_date             AS "Issued",
            received_date          AS "Received",
            arrival_lag_days       AS "Arrival lag (days)",
            currency               AS "Ccy",
            iva_at_risk_crc        AS "IVA at risk (CRC)",
            error_count            AS "Validation errors"
        FROM fct_deadline_status
        WHERE {status_filter}
        ORDER BY deadline_date, iva_at_risk_crc DESC
        """
    )

    if queue.empty:
        st.info("Nothing in this queue as of the evaluation date.")
    else:
        st.caption(
            f"**{len(queue)} documents · {colones(queue['IVA at risk (CRC)'].sum())} "
            "of IVA credit still recoverable**"
        )
        st.dataframe(
            queue,
            width="stretch",
            hide_index=True,
            column_config={
                "IVA at risk (CRC)": st.column_config.NumberColumn(format="₡%.0f"),
                "Business days left": st.column_config.NumberColumn(
                    help="Inclusive of today and of the deadline day itself."
                ),
            },
        )

        st.markdown("##### Where the exposure sits")
        by_issuer = (
            queue.groupby("Issuer", as_index=False)["IVA at risk (CRC)"]
            .sum()
            .nlargest(12, "IVA at risk (CRC)")
        )
        st.altair_chart(
            alt.Chart(by_issuer)
            .mark_bar(color=C_AT_RISK, cornerRadiusEnd=3)
            .encode(
                x=alt.X("IVA at risk (CRC):Q", title="IVA at risk (₡)"),
                y=alt.Y("Issuer:N", sort="-x", title=None),
                tooltip=["Issuer", alt.Tooltip("IVA at risk (CRC):Q", format=",.0f")],
            )
            .properties(height=min(340, 30 * len(by_issuer) + 40)),
            width="stretch",
        )

# --------------------------------------------------------------------------
# 2. Lost credit
# --------------------------------------------------------------------------

with tab_lost:
    st.subheader("Credit already lost")
    st.caption(
        "Documents whose window closed without an acceptance, plus documents "
        "accepted after the window closed. Both cost the same money. Nothing "
        "here is recoverable — there is no retroactive upload."
    )

    lost_by_month = q(
        """
        SELECT issue_month, COUNT(*) AS documents, SUM(iva_lost_crc) AS iva_lost_crc,
               ANY_VALUE(deadline_date) AS deadline
        FROM fct_deadline_status
        WHERE status = 'EXPIRED_CREDIT_LOST'
        GROUP BY issue_month ORDER BY issue_month
        """
    )
    if not lost_by_month.empty:
        st.altair_chart(
            alt.Chart(lost_by_month)
            .mark_bar(color=C_EXPIRED, cornerRadiusEnd=3)
            .encode(
                x=alt.X("issue_month:T", title="Issue month"),
                y=alt.Y("iva_lost_crc:Q", title="IVA lost (₡)"),
                tooltip=[
                    alt.Tooltip("issue_month:T", title="Issue month"),
                    alt.Tooltip("deadline:T", title="Deadline was"),
                    alt.Tooltip("documents:Q", title="Documents"),
                    alt.Tooltip("iva_lost_crc:Q", title="IVA lost", format=",.0f"),
                ],
            )
            .properties(height=280),
            width="stretch",
        )

    left, right = st.columns(2)

    with left:
        st.markdown("##### Why it was lost")
        reasons = q(
            """
            SELECT CASE WHEN accepted_late THEN 'Accepted, but after the deadline'
                        ELSE 'Never accepted' END AS reason,
                   COUNT(*) AS documents, SUM(iva_lost_crc) AS iva_lost_crc
            FROM fct_deadline_status WHERE status = 'EXPIRED_CREDIT_LOST'
            GROUP BY reason ORDER BY iva_lost_crc DESC
            """
        )
        st.dataframe(
            reasons, hide_index=True, width="stretch",
            column_config={"iva_lost_crc": st.column_config.NumberColumn(
                "IVA lost", format="₡%.0f")},
        )
        st.caption(
            "A document accepted late is recorded as accepted in the source "
            "system. It is counted as lost here because the credit is gone "
            "either way — the engine classifies outcome, not activity."
        )

    with right:
        st.markdown("##### Suppliers costing the most")
        st.dataframe(
            q(
                """
                SELECT contributor_name AS "Issuer", expired_document_count AS "Expired",
                       credit_lost_crc AS "IVA lost", avg_arrival_lag_days AS "Avg arrival lag (days)"
                FROM dim_contributor
                WHERE credit_lost_crc > 0
                ORDER BY credit_lost_crc DESC LIMIT 12
                """
            ),
            hide_index=True, width="stretch",
            column_config={"IVA lost": st.column_config.NumberColumn(format="₡%.0f")},
        )
        st.caption(
            "A high average arrival lag means the document reached the business "
            "too late to accept. That is fixed by talking to the supplier, not "
            "by working faster internally."
        )

# --------------------------------------------------------------------------
# 3. Validation
# --------------------------------------------------------------------------

with tab_quality:
    st.subheader("Validation failures by defect type")
    st.caption(
        "Structural checks against v4.4 expectations. This does not assess "
        "whether a document is legally correct — see REGULATORY_NOTES.md."
    )

    by_rule = q(
        """
        SELECT rule_id AS "Rule", ANY_VALUE(rule_name) AS "Defect",
               ANY_VALUE(severity) AS "Severity",
               COUNT(*) AS "Findings",
               COUNT(DISTINCT document_record_id) AS "Documents",
               COUNT(DISTINCT issuer_id) AS "Issuers"
        FROM fct_validation_finding
        GROUP BY rule_id ORDER BY "Findings" DESC
        """
    )
    st.altair_chart(
        alt.Chart(by_rule)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("Findings:Q"),
            y=alt.Y("Defect:N", sort="-x", title=None),
            color=alt.Color(
                "Severity:N",
                scale=alt.Scale(domain=["ERROR", "WARNING", "INFO"],
                                range=[C_AT_RISK, "#e9a13b", C_SAFE]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=["Rule", "Defect", "Severity", "Findings", "Documents", "Issuers"],
        )
        .properties(height=max(240, 26 * len(by_rule))),
        width="stretch",
    )
    st.dataframe(by_rule, hide_index=True, width="stretch")

    st.markdown("##### Documents that are both defective and running out of time")
    st.caption(
        "The worst quadrant: a document with a structural error usually has to "
        "go back to the supplier for a corrected one, and that round trip has to "
        "fit inside the window that is already closing."
    )
    st.dataframe(
        q(
            """
            SELECT deadline_date AS "Deadline", business_days_remaining AS "Days left",
                   issuer_name AS "Issuer", clave AS "Clave",
                   error_count AS "Errors", iva_at_risk_crc AS "IVA at risk"
            FROM fct_deadline_status
            WHERE status IN ('PENDING_AT_RISK','PENDING_SAFE') AND has_blocking_error
            ORDER BY business_days_remaining, iva_at_risk_crc DESC LIMIT 30
            """
        ),
        hide_index=True, width="stretch",
        column_config={"IVA at risk": st.column_config.NumberColumn(format="₡%.0f")},
    )

# --------------------------------------------------------------------------
# 4. Acceptance over time
# --------------------------------------------------------------------------

with tab_trend:
    st.subheader("Acceptance rate over time")
    st.caption(
        "By issue month. Only months whose window has closed can have a final "
        "rate; the current month is still in play and is shown for context."
    )

    trend = q(
        """
        SELECT issue_month,
               ANY_VALUE(deadline_date) AS deadline_date,
               ANY_VALUE(as_of) AS as_of,
               COUNT(*) AS documents,
               COUNT(*) FILTER (WHERE status = 'ACCEPTED') AS accepted,
               ROUND(100.0 * COUNT(*) FILTER (WHERE status='ACCEPTED') / COUNT(*), 1)
                   AS acceptance_rate,
               SUM(iva_lost_crc) AS iva_lost_crc
        FROM fct_deadline_status
        GROUP BY issue_month ORDER BY issue_month
        """
    )
    trend["window"] = [
        "closed" if d < a else "still open"
        for d, a in zip(trend["deadline_date"], trend["as_of"])
    ]

    st.altair_chart(
        alt.layer(
            alt.Chart(trend)
            .mark_line(point=True, strokeWidth=2.5, color=C_ACCEPTED)
            .encode(
                x=alt.X("issue_month:T", title="Issue month"),
                y=alt.Y("acceptance_rate:Q", title="Accepted in time (%)",
                        scale=alt.Scale(domain=[0, 100])),
                tooltip=[
                    alt.Tooltip("issue_month:T", title="Issue month"),
                    alt.Tooltip("deadline_date:T", title="Deadline"),
                    alt.Tooltip("documents:Q", title="Documents"),
                    alt.Tooltip("accepted:Q", title="Accepted in time"),
                    alt.Tooltip("acceptance_rate:Q", title="Rate %"),
                    alt.Tooltip("window:N", title="Window"),
                ],
            ),
            alt.Chart(trend[trend["window"] == "still open"])
            .mark_point(size=200, color=C_SAFE, filled=False, strokeWidth=2)
            .encode(x="issue_month:T", y="acceptance_rate:Q"),
        ).properties(height=320),
        width="stretch",
    )
    st.caption("Hollow markers: the acceptance window for that month has not closed yet.")

    st.markdown("##### Status mix by issue month")
    mix = q(
        """
        SELECT issue_month, status, COUNT(*) AS documents
        FROM fct_deadline_status GROUP BY issue_month, status ORDER BY issue_month
        """
    )
    st.altair_chart(
        alt.Chart(mix)
        .mark_bar()
        .encode(
            x=alt.X("issue_month:T", title="Issue month"),
            y=alt.Y("documents:Q", title="Documents", stack="normalize"),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(domain=STATUS_ORDER,
                                range=[STATUS_COLOURS[s] for s in STATUS_ORDER]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=["issue_month:T", "status:N", "documents:Q"],
        )
        .properties(height=300),
        width="stretch",
    )

    st.dataframe(
        trend[["issue_month", "deadline_date", "documents", "accepted",
               "acceptance_rate", "iva_lost_crc", "window"]],
        hide_index=True, width="stretch",
        column_config={
            "issue_month": "Issue month",
            "deadline_date": "Deadline",
            "acceptance_rate": st.column_config.NumberColumn("Accepted in time %", format="%.1f"),
            "iva_lost_crc": st.column_config.NumberColumn("IVA lost", format="₡%.0f"),
        },
    )

# --------------------------------------------------------------------------
# 5. The engine
# --------------------------------------------------------------------------

with tab_engine:
    st.subheader("How the deadline is computed")
    st.markdown(
        """
The rule: a received electronic document must be answered with a confirmation
message within the **first 8 business days of the month following its issue
date**. Miss it and the IVA credit is gone permanently.

The deadline is therefore **not** "8 business days after the invoice". Every
document issued in a given month shares one deadline. The table below is the
engine's own output, and `distinct deadlines` is 1 for every month — that is
the property, demonstrated rather than asserted.
        """
    )

    st.dataframe(
        q(
            """
            SELECT issue_month AS "Issue month",
                   ANY_VALUE(window_opens_on) AS "Window opens",
                   ANY_VALUE(deadline_date) AS "Deadline",
                   COUNT(DISTINCT deadline_date) AS "Distinct deadlines",
                   COUNT(*) AS "Documents"
            FROM fct_deadline_status GROUP BY issue_month ORDER BY issue_month
            """
        ),
        hide_index=True, width="stretch",
    )

    st.markdown("##### Status definitions")
    st.table(
        pd.DataFrame(
            [
                ("ACCEPTED", "Confirmed on or before the deadline. Credit secured."),
                ("PENDING_SAFE", "Not yet confirmed, more than 3 business days remain."),
                ("PENDING_AT_RISK", "Not yet confirmed, 3 or fewer business days remain "
                                    "(inclusive of the deadline day itself)."),
                ("EXPIRED_CREDIT_LOST", "Window closed unanswered, OR answered after it "
                                        "closed. Credit gone either way."),
            ],
            columns=["Status", "Meaning"],
        )
    )

    st.markdown("##### Holiday calendar in use")
    st.caption(
        "Costa Rican national holidays, 2025–2027, as a versioned data file. "
        "Holidays shift between years — Jueves and Viernes Santo track Easter, "
        "and the Monday-transfer rule has been on and off. The file needs "
        "maintaining; the engine refuses to compute outside its coverage rather "
        "than assuming a year has no holidays."
    )
    holidays = q(
        """
        SELECT holiday_date AS "Date", name_es AS "Holiday", name_en AS "English",
               pay_type AS "Pay type", moveable AS "Moves with Easter"
        FROM ref_holidays ORDER BY holiday_date
        """
    )
    year = st.selectbox(
        "Year", sorted({pd.to_datetime(d).year for d in holidays["Date"]}), index=1
    )
    st.dataframe(
        holidays[[pd.to_datetime(d).year == year for d in holidays["Date"]]],
        hide_index=True, width="stretch",
    )

    st.markdown("##### Signing and submission")
    st.warning(
        "This repository contains **no cryptographic keys and makes no live API "
        "calls**. The signing and submission layer is an interface with a mock "
        "implementation only — it returns canned responses from a dictionary and "
        "opens no network connection. It is structurally incapable of signing or "
        "submitting a real document. See `src/fractal_desk/submission/interface.py`."
    )

synthetic_banner()
