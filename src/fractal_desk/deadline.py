"""The deadline engine.

THE RULE
========
An electronic document that a business RECEIVES must be answered with a
confirmation message (aceptación, aceptación parcial or rechazo) inside a
statutory window. The window is:

    the first EIGHT BUSINESS DAYS of the month FOLLOWING the month in which the
    document was issued.

So the deadline is not "eight business days after the invoice". It is a fixed
calendar point per issue-month:

    deadline(issue_date) = 8th business day of (issue_month + 1)

Every document issued in March 2026 — the 1st, the 15th, the 31st — shares one
deadline: the 8th business day of April 2026. That is the single most
counter-intuitive thing about this rule and the reason a naive implementation
("add 8 business days to the issue date") is wrong for every document it
touches.

Miss the window and the IVA credit on that document is lost permanently. There
is no retroactive upload that restores it.

WHY THIS LIVES IN PYTHON AND NOT IN SQL
=======================================
The whole engine could be expressed in SQL against a date spine. It is in Python
because the holiday calendar, the coverage guard and the inclusive-count
convention need to be individually unit-testable, and because a wrong answer
here costs real money. The SQL layer consumes the result as a fact table
(``fct_deadline_status``); it does not re-derive it. One implementation, one
place to defend.

STATUS MODEL
============
``ACCEPTED``               Confirmed on or before the deadline. Credit secured.
``PENDING_SAFE``           Not yet confirmed, more than ``at_risk_threshold_days``
                           business days remain.
``PENDING_AT_RISK``        Not yet confirmed, ``at_risk_threshold_days`` (default
                           three) or fewer business days remain. Inclusive of the
                           deadline day itself.
``EXPIRED_CREDIT_LOST``    The window closed without a confirmation, OR a
                           confirmation was sent after the window closed.

That last clause is a judgement call worth stating plainly: a document confirmed
two days late is recorded in the source system as "accepted", but the credit is
gone. Reporting it as ACCEPTED would make the dashboard's headline number a lie.
The engine classifies outcome, not activity, so a late acceptance is
EXPIRED_CREDIT_LOST and carries ``accepted_late=True`` so the distinction is
still queryable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .business_calendar import BusinessCalendar

# The statutory window length. Named rather than inlined because it is the one
# number in this file that a change in the law would move, and because a bare 8
# in an arithmetic expression is exactly the kind of thing that gets copied into
# a second place and then updated in only one of them.
ACCEPTANCE_WINDOW_BUSINESS_DAYS = 8

# How many business days remaining counts as "at risk". Not statutory — this is
# an operational choice about when to start shouting. Three business days is
# roughly "you have this week", which is the smallest window in which a person
# can realistically chase a supplier for a corrected document and still confirm.
DEFAULT_AT_RISK_THRESHOLD_DAYS = 3


class DeadlineStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PENDING_SAFE = "PENDING_SAFE"
    PENDING_AT_RISK = "PENDING_AT_RISK"
    EXPIRED_CREDIT_LOST = "EXPIRED_CREDIT_LOST"

    @property
    def is_actionable(self) -> bool:
        """True when someone can still do something about it."""
        return self in (DeadlineStatus.PENDING_SAFE, DeadlineStatus.PENDING_AT_RISK)

    @property
    def credit_is_lost(self) -> bool:
        return self is DeadlineStatus.EXPIRED_CREDIT_LOST


@dataclass(frozen=True)
class DeadlineAssessment:
    """Everything the engine concluded about one document.

    Intermediate values (``window_opens_on``, ``business_days_remaining``) are
    kept on the result rather than thrown away. They are what makes a status
    explainable in the dashboard — "AT_RISK because 2 business days remain and
    the window closes on the 13th" — and what makes a disputed status auditable
    after the fact.
    """

    issue_date: date
    window_opens_on: date
    deadline_date: date
    status: DeadlineStatus
    business_days_remaining: int
    accepted_on: date | None
    accepted_late: bool
    as_of: date

    @property
    def is_overdue(self) -> bool:
        return self.status.credit_is_lost


def acceptance_window_open(issue_date: date, calendar: BusinessCalendar) -> date:
    """First business day of the month after ``issue_date``.

    This is when the confirmation window opens. In practice a receiver can
    confirm as soon as the document lands, so this date is informational rather
    than a gate — but it is what makes the eight-day count start where it starts,
    and showing it stops people reading the deadline as "8 days after receipt".
    """
    year, month = _following_month(issue_date)
    return calendar.nth_business_day_of_month(year, month, 1)


def acceptance_deadline(issue_date: date, calendar: BusinessCalendar) -> date:
    """The last día hábil on which this document can still be confirmed.

    The 8th business day of the month following the issue month.

    December rolls into January of the next year; that is handled by
    :func:`_following_month` rather than by month arithmetic at the call site,
    because ``month + 1`` producing month 13 is the single likeliest bug in this
    file and it should exist in exactly one place.
    """
    year, month = _following_month(issue_date)
    return calendar.nth_business_day_of_month(
        year, month, ACCEPTANCE_WINDOW_BUSINESS_DAYS
    )


def _following_month(day: date) -> tuple[int, int]:
    """(year, month) of the month after ``day``'s month, rolling Dec -> Jan."""
    if day.month == 12:
        return day.year + 1, 1
    return day.year, day.month + 1


def evaluate(
    issue_date: date,
    *,
    calendar: BusinessCalendar,
    as_of: date,
    accepted_on: date | None = None,
    at_risk_threshold_days: int = DEFAULT_AT_RISK_THRESHOLD_DAYS,
) -> DeadlineAssessment:
    """Classify one document against its acceptance deadline.

    Parameters
    ----------
    issue_date:
        ``FechaEmision`` of the received document. Note this is the ISSUE date,
        not the date it arrived — a document that reaches you three weeks late
        still has the deadline its issue month gave it. That asymmetry is where
        the money actually leaks, and modelling it correctly is the point of the
        tool.
    as_of:
        The date the question is being asked. Passed in rather than read from
        the system clock so that every status in a run is computed against one
        consistent instant, and so that tests can pin it.
    accepted_on:
        Date the confirmation message was sent, or ``None`` if it has not been.
    at_risk_threshold_days:
        Business days remaining at or below which a pending document is escalated
        to ``PENDING_AT_RISK``.
    """
    window_opens_on = acceptance_window_open(issue_date, calendar)
    deadline_date = acceptance_deadline(issue_date, calendar)

    # --- Already confirmed -------------------------------------------------
    # Outcome, not activity: a confirmation sent after the window closed did not
    # save the credit, so it is not ACCEPTED. accepted_late keeps the two cases
    # distinguishable downstream (a late confirmation is a process failure worth
    # counting separately from a document nobody ever touched).
    if accepted_on is not None:
        accepted_late = accepted_on > deadline_date
        return DeadlineAssessment(
            issue_date=issue_date,
            window_opens_on=window_opens_on,
            deadline_date=deadline_date,
            status=(
                DeadlineStatus.EXPIRED_CREDIT_LOST
                if accepted_late
                else DeadlineStatus.ACCEPTED
            ),
            # Nothing is "remaining" once the document has been answered.
            business_days_remaining=0,
            accepted_on=accepted_on,
            accepted_late=accepted_late,
            as_of=as_of,
        )

    # --- Not confirmed, window already closed ------------------------------
    if as_of > deadline_date:
        return DeadlineAssessment(
            issue_date=issue_date,
            window_opens_on=window_opens_on,
            deadline_date=deadline_date,
            status=DeadlineStatus.EXPIRED_CREDIT_LOST,
            business_days_remaining=0,
            accepted_on=None,
            accepted_late=False,
            as_of=as_of,
        )

    # --- Not confirmed, still open -----------------------------------------
    # Inclusive count across [as_of, deadline]. On the deadline day itself this
    # is 1, not 0: there is still a working day in which to act. See
    # BusinessCalendar.business_days_between for why that convention is fixed.
    #
    # When as_of falls before the window opens (i.e. we are still inside the
    # issue month) this count spans the tail of the issue month plus the window,
    # so it is comfortably above the threshold and the document reads as SAFE.
    # That is correct: an eight-business-day window means a document cannot
    # become at-risk until the window is well under way.
    remaining = calendar.business_days_between(as_of, deadline_date)

    status = (
        DeadlineStatus.PENDING_AT_RISK
        if remaining <= at_risk_threshold_days
        else DeadlineStatus.PENDING_SAFE
    )

    return DeadlineAssessment(
        issue_date=issue_date,
        window_opens_on=window_opens_on,
        deadline_date=deadline_date,
        status=status,
        business_days_remaining=remaining,
        accepted_on=None,
        accepted_late=False,
        as_of=as_of,
    )
