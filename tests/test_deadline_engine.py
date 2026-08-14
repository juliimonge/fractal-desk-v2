"""The deadline engine. Heaviest coverage in the suite, by design.

Expected deadlines below were worked out by hand against a 2025-2027 calendar.
They are written as literal dates, not derived from the code under test.

Worked example — March 2026, the hardest month in the window:

    Deadline = 8th business day of April 2026.
    Wed 1 Apr   business day 1
    Thu 2 Apr   Jueves Santo         (skip)
    Fri 3 Apr   Viernes Santo        (skip)
    Sat/Sun 4-5 weekend              (skip)
    Mon 6 Apr   business day 2
    Tue 7 Apr   business day 3
    Wed 8 Apr   business day 4
    Thu 9 Apr   business day 5
    Fri 10 Apr  business day 6
    Sat/Sun     weekend              (skip)
    Mon 13 Apr  business day 7
    Tue 14 Apr  business day 8   <-- deadline

Semana Santa pushes it from the 9th to the 14th. A tool that ignored holidays
would tell a business it had until the 9th and be five days optimistic in the
one direction that costs money.
"""

from __future__ import annotations

from datetime import date

import pytest

from fractal_desk.deadline import (
    ACCEPTANCE_WINDOW_BUSINESS_DAYS,
    DeadlineStatus,
    acceptance_deadline,
    acceptance_window_open,
    evaluate,
)


class TestDeadlineDate:
    @pytest.mark.parametrize(
        "issue_date,expected_deadline",
        [
            # --- ordinary months ---
            (date(2025, 10, 15), date(2025, 11, 12)),
            (date(2026, 1, 20), date(2026, 2, 11)),
            (date(2026, 5, 6), date(2026, 6, 10)),
            (date(2026, 6, 30), date(2026, 7, 10)),
            # --- Semana Santa lands INSIDE the window (see module docstring) ---
            # Easter 2026 is 5 April, so Jueves/Viernes Santo (2-3 April) fall on
            # business days 2 and 3 of the window and push the deadline out.
            (date(2026, 3, 1), date(2026, 4, 14)),
            (date(2026, 3, 31), date(2026, 4, 14)),
            # --- Semana Santa lands AFTER the window and shifts nothing ---
            # Easter 2025 is 20 April, so Jueves/Viernes Santo (17-18 April) fall
            # after the 8th business day. Same holiday, opposite effect, purely
            # because of where Easter sits that year. This is why the calendar is
            # a maintained data file rather than a fixed list of dates.
            (date(2025, 3, 10), date(2025, 4, 10)),
            # --- December to January rollover ---
            (date(2025, 12, 1), date(2026, 1, 13)),
            (date(2025, 12, 31), date(2026, 1, 13)),
            (date(2026, 12, 15), date(2027, 1, 13)),
            # --- following month opens on a holiday ---
            (date(2025, 12, 5), date(2026, 1, 13)),
        ],
    )
    def test_deadline_is_the_eighth_business_day_of_the_next_month(
        self, calendar, issue_date, expected_deadline
    ):
        assert acceptance_deadline(issue_date, calendar) == expected_deadline

    def test_deadline_always_lands_in_the_month_after_issue(self, calendar):
        for month in range(1, 13):
            issue = date(2026, month, 15)
            deadline = acceptance_deadline(issue, calendar)
            expected_month = 1 if month == 12 else month + 1
            expected_year = 2027 if month == 12 else 2026
            assert (deadline.year, deadline.month) == (expected_year, expected_month)

    def test_deadline_is_always_a_business_day(self, calendar):
        for month in range(1, 13):
            deadline = acceptance_deadline(date(2026, month, 10), calendar)
            assert calendar.is_business_day(deadline)


class TestDeadlineIsSharedAcrossTheIssueMonth:
    """The property most people get wrong on first reading of the rule."""

    def test_every_day_of_a_month_yields_one_deadline(self, calendar):
        deadlines = {
            acceptance_deadline(date(2026, 3, day), calendar) for day in range(1, 32)
        }
        assert deadlines == {date(2026, 4, 14)}

    def test_it_is_not_eight_business_days_after_the_invoice(self, calendar):
        """Guards against the naive implementation."""
        issue = date(2026, 3, 2)
        naive = calendar.add_business_days(issue, ACCEPTANCE_WINDOW_BUSINESS_DAYS)
        assert naive == date(2026, 3, 12)
        assert acceptance_deadline(issue, calendar) == date(2026, 4, 14)
        assert acceptance_deadline(issue, calendar) != naive

    def test_first_and_last_day_of_month_agree(self, calendar):
        for year, month, last in [(2026, 1, 31), (2026, 2, 28), (2026, 4, 30)]:
            first_deadline = acceptance_deadline(date(year, month, 1), calendar)
            last_deadline = acceptance_deadline(date(year, month, last), calendar)
            assert first_deadline == last_deadline


class TestWindowOpen:
    @pytest.mark.parametrize(
        "issue_date,expected_open",
        [
            (date(2026, 7, 15), date(2026, 8, 3)),   # 1-2 Aug are a weekend
            (date(2025, 12, 20), date(2026, 1, 2)),  # 1 Jan is Año Nuevo
            (date(2026, 3, 3), date(2026, 4, 1)),    # ordinary Wednesday
        ],
    )
    def test_window_opens_on_first_business_day_of_next_month(
        self, calendar, issue_date, expected_open
    ):
        assert acceptance_window_open(issue_date, calendar) == expected_open

    def test_window_spans_exactly_eight_business_days(self, calendar):
        for month in range(1, 13):
            issue = date(2026, month, 15)
            opens = acceptance_window_open(issue, calendar)
            closes = acceptance_deadline(issue, calendar)
            assert calendar.business_days_between(opens, closes) == (
                ACCEPTANCE_WINDOW_BUSINESS_DAYS
            )


class TestStatusTransitions:
    """Every branch of the status model."""

    ISSUE = date(2026, 7, 15)      # deadline: 12 August 2026
    DEADLINE = date(2026, 8, 12)

    def test_accepted_before_the_deadline(self, calendar):
        result = evaluate(
            self.ISSUE, calendar=calendar, as_of=date(2026, 8, 11),
            accepted_on=date(2026, 8, 5),
        )
        assert result.status is DeadlineStatus.ACCEPTED
        assert result.accepted_late is False
        assert result.deadline_date == self.DEADLINE

    def test_accepted_exactly_on_the_deadline_is_in_time(self, calendar):
        result = evaluate(
            self.ISSUE, calendar=calendar, as_of=date(2026, 8, 12),
            accepted_on=self.DEADLINE,
        )
        assert result.status is DeadlineStatus.ACCEPTED
        assert result.accepted_late is False

    def test_accepted_one_day_after_the_deadline_is_credit_lost(self, calendar):
        """A confirmation that exists but did not save the credit."""
        result = evaluate(
            self.ISSUE, calendar=calendar, as_of=date(2026, 8, 20),
            accepted_on=date(2026, 8, 13),
        )
        assert result.status is DeadlineStatus.EXPIRED_CREDIT_LOST
        assert result.accepted_late is True
        assert result.accepted_on == date(2026, 8, 13)

    def test_pending_safe_well_inside_the_window(self, calendar):
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 4))
        assert result.status is DeadlineStatus.PENDING_SAFE
        # 4,5,6,7,10,11,12 August are business days -> 7 remaining.
        assert result.business_days_remaining == 7

    def test_pending_at_risk_at_the_threshold(self, calendar):
        # 10 Aug: 10, 11, 12 remain -> exactly 3, the default threshold.
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 10))
        assert result.business_days_remaining == 3
        assert result.status is DeadlineStatus.PENDING_AT_RISK

    def test_one_business_day_either_side_of_the_threshold(self, calendar):
        safe = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 7))
        at_risk = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 10))
        assert safe.business_days_remaining == 4
        assert safe.status is DeadlineStatus.PENDING_SAFE
        assert at_risk.status is DeadlineStatus.PENDING_AT_RISK

    def test_on_the_deadline_day_itself_one_day_remains(self, calendar):
        """The off-by-one that would tell someone they are fine on the last day."""
        result = evaluate(self.ISSUE, calendar=calendar, as_of=self.DEADLINE)
        assert result.business_days_remaining == 1
        assert result.status is DeadlineStatus.PENDING_AT_RISK
        assert result.is_overdue is False

    def test_the_day_after_the_deadline_the_credit_is_gone(self, calendar):
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 13))
        assert result.status is DeadlineStatus.EXPIRED_CREDIT_LOST
        assert result.business_days_remaining == 0
        assert result.is_overdue is True

    def test_never_accepted_long_past_the_window(self, calendar):
        result = evaluate(date(2025, 10, 10), calendar=calendar, as_of=date(2026, 8, 11))
        assert result.status is DeadlineStatus.EXPIRED_CREDIT_LOST
        assert result.accepted_on is None
        assert result.accepted_late is False

    def test_asked_before_the_window_opens(self, calendar):
        """Still inside the issue month: safe, and the window is in the future."""
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 7, 20))
        assert result.status is DeadlineStatus.PENDING_SAFE
        assert result.window_opens_on == date(2026, 8, 3)
        assert result.as_of < result.window_opens_on

    def test_a_weekend_as_of_date_still_counts_correctly(self, calendar):
        # Saturday 8 August 2026: 10, 11, 12 remain.
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 8, 8))
        assert result.business_days_remaining == 3
        assert result.status is DeadlineStatus.PENDING_AT_RISK

    def test_custom_threshold_changes_only_the_escalation_point(self, calendar):
        as_of = date(2026, 8, 6)  # 5 business days remain
        default = evaluate(self.ISSUE, calendar=calendar, as_of=as_of)
        widened = evaluate(
            self.ISSUE, calendar=calendar, as_of=as_of, at_risk_threshold_days=5
        )
        assert default.status is DeadlineStatus.PENDING_SAFE
        assert widened.status is DeadlineStatus.PENDING_AT_RISK
        assert default.deadline_date == widened.deadline_date


class TestDecemberJanuaryRollover:
    """The rollover gets its own class because it is where month arithmetic breaks."""

    ISSUE = date(2025, 12, 18)
    DEADLINE = date(2026, 1, 13)

    def test_deadline_crosses_the_year_boundary(self, calendar):
        assert acceptance_deadline(self.ISSUE, calendar) == self.DEADLINE

    def test_window_opens_after_new_years_day(self, calendar):
        # 1 January 2026 is a Thursday and a holiday, so the window opens on the 2nd.
        assert acceptance_window_open(self.ISSUE, calendar) == date(2026, 1, 2)

    def test_counting_across_the_year_boundary(self, calendar):
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2025, 12, 31))
        assert result.status is DeadlineStatus.PENDING_SAFE
        # 31 Dec, then 2, 5, 6, 7, 8, 9, 12, 13 Jan = 9 business days.
        assert result.business_days_remaining == 9

    def test_at_risk_in_the_new_year_for_a_december_document(self, calendar):
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 1, 9))
        # 9, 12, 13 January = 3 remaining.
        assert result.business_days_remaining == 3
        assert result.status is DeadlineStatus.PENDING_AT_RISK

    def test_expired_in_the_new_year(self, calendar):
        result = evaluate(self.ISSUE, calendar=calendar, as_of=date(2026, 1, 14))
        assert result.status is DeadlineStatus.EXPIRED_CREDIT_LOST

    def test_december_2026_rolls_into_2027(self, calendar):
        assert acceptance_deadline(date(2026, 12, 31), calendar) == date(2027, 1, 13)

    def test_all_of_december_shares_one_deadline(self, calendar):
        deadlines = {
            acceptance_deadline(date(2025, 12, day), calendar) for day in range(1, 32)
        }
        assert deadlines == {date(2026, 1, 13)}


class TestMonthBoundaries:
    def test_last_day_of_month_and_first_of_next_are_a_month_apart(self, calendar):
        jan_31 = acceptance_deadline(date(2026, 1, 31), calendar)
        feb_01 = acceptance_deadline(date(2026, 2, 1), calendar)
        assert jan_31 == date(2026, 2, 11)
        assert feb_01 == date(2026, 3, 11)
        assert jan_31 < feb_01

    def test_one_day_of_issue_difference_can_mean_a_month_of_deadline(self, calendar):
        """Why month boundaries are a stress case worth generating on purpose."""
        a = acceptance_deadline(date(2026, 6, 30), calendar)
        b = acceptance_deadline(date(2026, 7, 1), calendar)
        assert (b - a).days > 25

    def test_february_in_a_non_leap_year(self, calendar):
        assert acceptance_deadline(date(2026, 2, 28), calendar) == date(2026, 3, 11)


class TestAssessmentShape:
    def test_terminal_statuses_report_zero_days_remaining(self, calendar):
        accepted = evaluate(
            date(2026, 7, 15), calendar=calendar, as_of=date(2026, 8, 11),
            accepted_on=date(2026, 8, 4),
        )
        expired = evaluate(date(2025, 10, 1), calendar=calendar, as_of=date(2026, 8, 11))
        assert accepted.business_days_remaining == 0
        assert expired.business_days_remaining == 0

    def test_days_remaining_is_never_negative(self, calendar):
        for day in range(1, 29):
            result = evaluate(
                date(2026, 6, 10), calendar=calendar, as_of=date(2026, 7, day)
            )
            assert result.business_days_remaining >= 0

    def test_status_helpers_agree_with_the_status(self, calendar):
        assert DeadlineStatus.PENDING_AT_RISK.is_actionable
        assert DeadlineStatus.PENDING_SAFE.is_actionable
        assert not DeadlineStatus.ACCEPTED.is_actionable
        assert not DeadlineStatus.EXPIRED_CREDIT_LOST.is_actionable
        assert DeadlineStatus.EXPIRED_CREDIT_LOST.credit_is_lost
        assert not DeadlineStatus.ACCEPTED.credit_is_lost

    def test_assessment_is_immutable(self, calendar):
        result = evaluate(date(2026, 7, 15), calendar=calendar, as_of=date(2026, 8, 11))
        with pytest.raises(Exception):
            result.status = DeadlineStatus.ACCEPTED  # type: ignore[misc]

    def test_every_status_is_reachable(self, calendar):
        """Guards against a branch becoming dead code."""
        issue = date(2026, 7, 15)
        produced = {
            evaluate(issue, calendar=calendar, as_of=date(2026, 8, 11),
                     accepted_on=date(2026, 8, 4)).status,
            evaluate(issue, calendar=calendar, as_of=date(2026, 8, 4)).status,
            evaluate(issue, calendar=calendar, as_of=date(2026, 8, 11)).status,
            evaluate(issue, calendar=calendar, as_of=date(2026, 8, 20)).status,
        }
        assert produced == set(DeadlineStatus)
