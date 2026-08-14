"""Shared fixtures.

The calendar is session-scoped and built from the real ``data/cr_holidays.csv``
rather than from a fixture file. Tests that assert a specific deadline are
therefore also testing the shipped holiday data — if someone edits the calendar
and gets a date wrong, these tests go red. That coupling is deliberate: the
holiday file is reference data the engine's correctness depends on, so it should
be under test like anything else.
"""

from __future__ import annotations

from datetime import date

import pytest

from fractal_desk.business_calendar import load_calendar


@pytest.fixture(scope="session")
def calendar():
    """The shipped calendar, observing all twelve national holidays."""
    return load_calendar()


@pytest.fixture(scope="session")
def calendar_working_non_mandatory():
    """Variant that treats the three pago-no-obligatorio holidays as working days."""
    return load_calendar(observe_non_mandatory_pay_holidays=False)


@pytest.fixture
def as_of():
    return date(2026, 8, 11)
