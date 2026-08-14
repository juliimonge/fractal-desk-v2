"""Business-day arithmetic.

The deadline engine is only as good as this module, so these tests are dense and
mostly assert against dates worked out by hand from a calendar rather than from
the code. A test that computes the expected value the same way the code does
proves nothing.
"""

from __future__ import annotations

from datetime import date

import pytest

from fractal_desk.business_calendar import (
    BusinessDayNotFoundError,
    CalendarCoverageError,
    load_calendar,
)


class TestWeekends:
    def test_saturday_and_sunday_are_not_business_days(self, calendar):
        assert not calendar.is_business_day(date(2026, 8, 8))   # Saturday
        assert not calendar.is_business_day(date(2026, 8, 9))   # Sunday

    def test_ordinary_weekdays_are_business_days(self, calendar):
        for day in range(10, 15):  # Mon 10 Aug .. Fri 14 Aug 2026
            assert calendar.is_business_day(date(2026, 8, day))


class TestHolidays:
    @pytest.mark.parametrize(
        "holiday",
        [
            date(2026, 1, 1),    # Año Nuevo, a Thursday
            date(2026, 4, 2),    # Jueves Santo
            date(2026, 4, 3),    # Viernes Santo
            date(2026, 5, 1),    # Día del Trabajo, a Friday
            date(2026, 9, 15),   # Independencia, a Tuesday
            date(2026, 12, 25),  # Navidad, a Friday
        ],
    )
    def test_weekday_holidays_are_not_business_days(self, calendar, holiday):
        assert holiday.weekday() < 5, "fixture date must be a weekday to be meaningful"
        assert not calendar.is_business_day(holiday)

    def test_semana_santa_moves_with_easter(self, calendar):
        # Easter 2025-04-20, 2026-04-05, 2027-03-28. Jueves and Viernes Santo
        # track it, which is why they are listed per-year in the data file.
        assert not calendar.is_business_day(date(2025, 4, 17))
        assert not calendar.is_business_day(date(2026, 4, 2))
        assert not calendar.is_business_day(date(2027, 3, 25))
        # And the equivalent date in a different year is an ordinary workday.
        assert calendar.is_business_day(date(2026, 3, 25))

    def test_holiday_falling_on_a_weekend_changes_nothing(self, calendar):
        # 25 July 2026 (Anexión de Nicoya) is a Saturday. Already not a business
        # day; the holiday flag must not double-count or shift anything.
        assert date(2026, 7, 25).weekday() == 5
        assert not calendar.is_business_day(date(2026, 7, 25))
        assert calendar.is_business_day(date(2026, 7, 24))
        assert calendar.is_business_day(date(2026, 7, 27))


class TestNonMandatoryPayHolidays:
    """The three pago-no-obligatorio holidays, and the switch that governs them."""

    def test_observed_by_default(self, calendar):
        assert not calendar.is_business_day(date(2026, 8, 31))  # Persona Negra, Monday
        assert not calendar.is_business_day(date(2026, 12, 1))  # Abolición, Tuesday

    def test_treated_as_working_when_switched_off(self, calendar_working_non_mandatory):
        cal = calendar_working_non_mandatory
        assert cal.is_business_day(date(2026, 8, 31))
        assert cal.is_business_day(date(2026, 12, 1))

    def test_mandatory_holidays_are_unaffected_by_the_switch(
        self, calendar_working_non_mandatory
    ):
        assert not calendar_working_non_mandatory.is_business_day(date(2026, 12, 25))

    def test_switching_it_off_moves_the_september_deadline_earlier(
        self, calendar, calendar_working_non_mandatory
    ):
        # September 2026's window is the one affected: 31 August is a Monday and
        # a pago-no-obligatorio holiday, but it is in AUGUST, so it shifts
        # nothing in September. December is the month where it bites: 1 December
        # 2026 is a Tuesday.
        strict = calendar.nth_business_day_of_month(2026, 12, 8)
        loose = calendar_working_non_mandatory.nth_business_day_of_month(2026, 12, 8)
        assert loose < strict, "treating the holiday as worked must pull the deadline in"
        assert strict == date(2026, 12, 11)
        assert loose == date(2026, 12, 10)


class TestCoverage:
    def test_dates_before_coverage_raise(self, calendar):
        with pytest.raises(CalendarCoverageError):
            calendar.is_business_day(date(2024, 6, 3))

    def test_dates_after_coverage_raise(self, calendar):
        with pytest.raises(CalendarCoverageError):
            calendar.is_business_day(date(2028, 1, 3))

    def test_coverage_bounds_match_the_data_file(self, calendar):
        assert calendar.coverage_start == date(2025, 1, 1)
        assert calendar.coverage_end == date(2027, 12, 31)

    def test_silent_wrong_answers_are_impossible(self, calendar):
        """The failure mode this guard exists to prevent.

        Without it, an out-of-range year would look holiday-free and the 8th
        business day would land days early — a wrong answer that looks
        completely normal in a dashboard.
        """
        with pytest.raises(CalendarCoverageError):
            calendar.nth_business_day_of_month(2028, 1, 8)


class TestBusinessDaysBetween:
    def test_inclusive_at_both_ends(self, calendar):
        # Mon 10 Aug .. Fri 14 Aug 2026 is five business days, not four.
        assert calendar.business_days_between(date(2026, 8, 10), date(2026, 8, 14)) == 5

    def test_same_business_day_is_one(self, calendar):
        """The convention that stops a deadline tool lying on the deadline day."""
        assert calendar.business_days_between(date(2026, 8, 11), date(2026, 8, 11)) == 1

    def test_same_non_business_day_is_zero(self, calendar):
        assert calendar.business_days_between(date(2026, 8, 8), date(2026, 8, 8)) == 0

    def test_span_across_a_weekend(self, calendar):
        # Fri 7 Aug .. Mon 10 Aug 2026 = Fri + Mon = 2.
        assert calendar.business_days_between(date(2026, 8, 7), date(2026, 8, 10)) == 2

    def test_span_across_a_holiday(self, calendar):
        # Wed 1 Apr .. Mon 6 Apr 2026 spans Jueves and Viernes Santo plus a
        # weekend: only 1 April and 6 April count.
        assert calendar.business_days_between(date(2026, 4, 1), date(2026, 4, 6)) == 2

    def test_reversed_range_is_zero_not_negative(self, calendar):
        assert calendar.business_days_between(date(2026, 8, 14), date(2026, 8, 10)) == 0


class TestAddBusinessDays:
    def test_friday_plus_one_is_monday(self, calendar):
        assert calendar.add_business_days(date(2026, 8, 7), 1) == date(2026, 8, 10)

    def test_zero_is_a_no_op_even_on_a_weekend(self, calendar):
        assert calendar.add_business_days(date(2026, 8, 8), 0) == date(2026, 8, 8)

    def test_skips_holidays(self, calendar):
        # Wed 1 Apr 2026 + 1 business day skips Jueves/Viernes Santo and the
        # weekend, landing on Monday 6 April.
        assert calendar.add_business_days(date(2026, 4, 1), 1) == date(2026, 4, 6)

    def test_negative_counts_go_backwards(self, calendar):
        assert calendar.add_business_days(date(2026, 8, 10), -1) == date(2026, 8, 7)

    def test_add_then_subtract_returns_to_a_business_day(self, calendar):
        start = date(2026, 3, 30)
        assert calendar.add_business_days(calendar.add_business_days(start, 12), -12) == start


class TestNthBusinessDayOfMonth:
    @pytest.mark.parametrize(
        "year,month,expected",
        [
            # August 2026: 1st and 2nd fall on a weekend (and the 2nd is a
            # holiday), so the month's business days start Monday 3rd.
            (2026, 8, date(2026, 8, 3)),
            # January 2026: the 1st is Año Nuevo on a Thursday, so the first
            # business day is Friday the 2nd.
            (2026, 1, date(2026, 1, 2)),
            # April 2026: the 1st is an ordinary Wednesday.
            (2026, 4, date(2026, 4, 1)),
        ],
    )
    def test_first_business_day(self, calendar, year, month, expected):
        assert calendar.nth_business_day_of_month(year, month, 1) == expected

    def test_rejects_n_below_one(self, calendar):
        with pytest.raises(ValueError):
            calendar.nth_business_day_of_month(2026, 8, 0)

    def test_raises_when_the_month_is_too_short(self, calendar):
        # No month has 40 business days; the engine should say so rather than
        # silently walking into the next month.
        with pytest.raises(BusinessDayNotFoundError):
            calendar.nth_business_day_of_month(2026, 8, 40)

    def test_never_crosses_into_the_next_month(self, calendar):
        for month in range(1, 13):
            result = calendar.nth_business_day_of_month(2026, month, 8)
            assert result.month == month
            assert result.year == 2026


class TestCalendarConstruction:
    def test_empty_holiday_list_is_rejected(self):
        from fractal_desk.business_calendar import BusinessCalendar

        with pytest.raises(ValueError):
            BusinessCalendar([])

    def test_shipped_file_has_twelve_holidays_per_year(self, calendar):
        by_year: dict[int, int] = {}
        for holiday in calendar.all_holidays:
            by_year[holiday.holiday_date.year] = by_year.get(holiday.holiday_date.year, 0) + 1
        assert by_year == {2025: 12, 2026: 12, 2027: 12}

    def test_loader_is_cached_per_configuration(self):
        assert load_calendar() is load_calendar()
        assert load_calendar() is not load_calendar(observe_non_mandatory_pay_holidays=False)
