"""Costa Rican business-day (día hábil) arithmetic.

This module owns one question: **is a given calendar date a business day in
Costa Rica, and how do I count forward and backward in business days?**

It knows nothing about invoices, deadlines or tax. Keeping it that way is
deliberate — the deadline rule in ``deadline.py`` is then a three-line statement
on top of primitives that are individually testable.

DEFINITION USED
---------------
A date is a business day (*día hábil*) when it is:
  * Monday through Friday, AND
  * not a national public holiday that the calendar observes.

Two things this definition deliberately does NOT model:
  * **Half-day observances.** 24 and 31 December are worked as half days by many
    Costa Rican institutions. A half day is still a día hábil, so this makes no
    difference to the count, and modelling it would add a distinction with no
    effect on the answer.
  * **Institution-specific closures.** A bank holiday, an internal shutdown or a
    regional festival is not a national feriado and does not change the
    statutory count. If the tax administration ever announces an extraordinary
    closure that extends a filing window, that is a change to the holiday file,
    not to this code.

COVERAGE IS ENFORCED, NOT ASSUMED
---------------------------------
The holiday file covers a fixed range of years. Asking about a date outside that
range raises :class:`CalendarCoverageError`. The alternative — treating an
unknown year as having no holidays — would silently return deadlines that are
wrong by up to a week and would look completely normal in a dashboard. A loud
failure on an out-of-range date is the whole point.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from . import paths

# Monday..Friday. date.weekday() is 0 for Monday, 6 for Sunday.
_SATURDAY = 5


class CalendarCoverageError(ValueError):
    """Raised when a date falls outside the years the holiday file covers."""


class BusinessDayNotFoundError(ValueError):
    """Raised when a month does not contain the requested nth business day."""


@dataclass(frozen=True)
class Holiday:
    holiday_date: date
    name_es: str
    name_en: str
    pay_type: str
    moveable: bool
    observed_as_non_business: bool
    note: str

    @property
    def is_mandatory_pay(self) -> bool:
        return self.pay_type == "obligatorio"


def _load_holiday_rows(path: Path) -> list[Holiday]:
    with path.open(encoding="utf-8") as handle:
        lines = [
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        ]
    holidays: list[Holiday] = []
    for row in csv.DictReader(lines):
        holidays.append(
            Holiday(
                holiday_date=date.fromisoformat(row["holiday_date"]),
                name_es=row["name_es"],
                name_en=row["name_en"],
                pay_type=row["pay_type"],
                moveable=row["moveable"].strip().lower() == "true",
                observed_as_non_business=(
                    row["observed_as_non_business"].strip().lower() == "true"
                ),
                note=row.get("note", "") or "",
            )
        )
    return holidays


class BusinessCalendar:
    """A business-day calendar backed by a versioned holiday file.

    Parameters
    ----------
    holidays:
        The holiday records to observe.
    observe_non_mandatory_pay_holidays:
        Costa Rica splits its twelve national holidays into *pago obligatorio*
        (nine of them) and *pago no obligatorio* (2 August, 31 August and
        1 December). That split is a labour-law rule about whether an employer
        must pay for the day — it is **not** a statement about whether the day is
        a día hábil.

        The default, ``True``, treats all twelve as non-business days: they are
        national holidays, and *día hábil* in tax procedure excludes feriados.

        Setting this to ``False`` counts the three non-mandatory-pay holidays as
        working days, which moves every affected deadline EARLIER. That is the
        safer direction to be wrong in — you act sooner than required — but it is
        not the reading of the law, so it is not the default. If you want a
        safety margin, widen ``at_risk_threshold_days`` in the deadline engine
        rather than distorting the calendar; a distorted calendar produces a
        deadline you cannot defend to an auditor, and the difference only ever
        bites in three months of the year.
    """

    def __init__(
        self,
        holidays: list[Holiday],
        *,
        observe_non_mandatory_pay_holidays: bool = True,
    ) -> None:
        if not holidays:
            raise ValueError("BusinessCalendar requires at least one holiday record")

        self._all_holidays = tuple(sorted(holidays, key=lambda h: h.holiday_date))
        self.observe_non_mandatory_pay_holidays = observe_non_mandatory_pay_holidays

        observed = {
            h.holiday_date: h
            for h in self._all_holidays
            if h.observed_as_non_business
            and (observe_non_mandatory_pay_holidays or h.is_mandatory_pay)
        }
        self._observed: dict[date, Holiday] = observed

        years = {h.holiday_date.year for h in self._all_holidays}
        self.min_year = min(years)
        self.max_year = max(years)
        # Coverage is expressed in whole years because the holiday file is
        # maintained a year at a time.
        self.coverage_start = date(self.min_year, 1, 1)
        self.coverage_end = date(self.max_year, 12, 31)

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def covers(self, day: date) -> bool:
        return self.coverage_start <= day <= self.coverage_end

    def _require_coverage(self, day: date) -> None:
        if not self.covers(day):
            raise CalendarCoverageError(
                f"{day.isoformat()} is outside the holiday calendar's coverage "
                f"({self.coverage_start.isoformat()} .. {self.coverage_end.isoformat()}). "
                "Extend data/cr_holidays.csv rather than assuming the year has no holidays."
            )

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------

    def holiday_on(self, day: date) -> Holiday | None:
        """Return the observed holiday falling on ``day``, if any."""
        self._require_coverage(day)
        return self._observed.get(day)

    def is_weekend(self, day: date) -> bool:
        return day.weekday() >= _SATURDAY

    def is_business_day(self, day: date) -> bool:
        """True when ``day`` is a día hábil."""
        self._require_coverage(day)
        if self.is_weekend(day):
            return False
        return day not in self._observed

    def next_business_day(self, day: date, *, inclusive: bool = False) -> date:
        """The first business day on or after ``day``.

        ``inclusive=True`` returns ``day`` itself when it is already a business
        day; the default steps at least one day forward.
        """
        cursor = day if inclusive else day + timedelta(days=1)
        while not self.is_business_day(cursor):
            cursor += timedelta(days=1)
        return cursor

    def previous_business_day(self, day: date, *, inclusive: bool = False) -> date:
        """The last business day on or before ``day``."""
        cursor = day if inclusive else day - timedelta(days=1)
        while not self.is_business_day(cursor):
            cursor -= timedelta(days=1)
        return cursor

    def add_business_days(self, start: date, count: int) -> date:
        """Move ``count`` business days from ``start``.

        ``count`` is a number of *steps*, not a span: adding 1 to a Friday gives
        the following Monday, and adding 0 returns ``start`` unchanged even if
        ``start`` is a weekend. Callers that want "the nth business day of a
        window" should use :meth:`nth_business_day_of_month` or
        :meth:`business_days_between`, which are inclusive-count based and are
        what the statutory rule actually needs.
        """
        if count == 0:
            return start
        step = timedelta(days=1 if count > 0 else -1)
        remaining = abs(count)
        cursor = start
        while remaining:
            cursor += step
            if self.is_business_day(cursor):
                remaining -= 1
        return cursor

    def business_days_between(self, start: date, end: date) -> int:
        """Count business days in the CLOSED interval ``[start, end]``.

        Inclusive at both ends. ``business_days_between(d, d)`` is 1 when ``d``
        is a business day and 0 when it is not. Returns 0 when ``end < start``.

        Inclusivity is the single most important convention in this module, so
        it is stated once here and relied on everywhere else: "how many business
        days do I have left" on the deadline day itself must be 1, not 0 — you
        can still act that day. Getting this wrong by one is the classic way a
        deadline tool tells someone they are fine on the morning of the day the
        credit dies.
        """
        if end < start:
            return 0
        self._require_coverage(start)
        self._require_coverage(end)

        count = 0
        cursor = start
        while cursor <= end:
            if self.is_business_day(cursor):
                count += 1
            cursor += timedelta(days=1)
        return count

    def nth_business_day_of_month(self, year: int, month: int, n: int) -> date:
        """The ``n``-th business day of a calendar month, counting from 1.

        ``n=1`` is the first business day of the month — the day the statutory
        acceptance window opens. ``n=8`` is the deadline itself.

        Raises :class:`BusinessDayNotFoundError` if the month is too short to
        contain ``n`` business days. With ``n=8`` this cannot happen in practice
        (the worst possible month still has well over eight), but the engine
        should not depend on that being true forever.
        """
        if n < 1:
            raise ValueError("n must be >= 1")

        first = date(year, month, 1)
        self._require_coverage(first)

        seen = 0
        cursor = first
        while cursor.month == month:
            if self.is_business_day(cursor):
                seen += 1
                if seen == n:
                    return cursor
            cursor += timedelta(days=1)

        raise BusinessDayNotFoundError(
            f"{year}-{month:02d} contains only {seen} business days; "
            f"cannot take business day {n}"
        )

    # ------------------------------------------------------------------
    # Introspection, used by the dashboard and the run report
    # ------------------------------------------------------------------

    @property
    def observed_holidays(self) -> tuple[Holiday, ...]:
        return tuple(self._observed.values())

    @property
    def all_holidays(self) -> tuple[Holiday, ...]:
        return self._all_holidays

    def describe(self) -> dict[str, object]:
        return {
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "holidays_in_file": len(self._all_holidays),
            "holidays_observed": len(self._observed),
            "observe_non_mandatory_pay_holidays": (
                self.observe_non_mandatory_pay_holidays
            ),
        }


@lru_cache(maxsize=4)
def load_calendar(
    path: Path | None = None,
    *,
    observe_non_mandatory_pay_holidays: bool = True,
) -> BusinessCalendar:
    """Load the versioned Costa Rican holiday calendar from ``data/``."""
    return BusinessCalendar(
        _load_holiday_rows(path or paths.HOLIDAYS_CSV),
        observe_non_mandatory_pay_holidays=observe_non_mandatory_pay_holidays,
    )
