"""Dashboard smoke test.

Runs the Streamlit script end to end against the built warehouse and asserts it
raises nothing. A dashboard is the one part of a project people judge on sight,
and the usual way it breaks is a renamed column in a mart — which is invisible
until someone opens the page. This catches that in CI instead.

Skipped when no warehouse has been built, so `pytest` works on a clean clone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fractal_desk import paths

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"

pytestmark = pytest.mark.skipif(
    not paths.WAREHOUSE_DB.exists(),
    reason="no warehouse built; run `python -m fractal_desk.pipeline` first",
)


@pytest.fixture(scope="module")
def app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(APP), default_timeout=180).run()


def test_page_renders_without_exceptions(app):
    assert not app.exception, [str(e.value) for e in app.exception]


def test_all_five_tabs_are_present(app):
    assert len(app.tabs) == 5


def test_headline_metrics_are_populated(app):
    labels = {m.label for m in app.metric}
    assert {"At risk now", "Recoverable total", "Already lost", "Secured"} <= labels


def test_synthetic_banner_is_rendered_top_and_bottom(app):
    banners = [
        block for block in app.markdown
        if "ALL DATA ON THIS PAGE IS SYNTHETIC" in str(block.value)
    ]
    assert len(banners) >= 2, "the synthetic-data banner must open and close the page"


def test_no_live_call_disclaimer_is_present(app):
    text = " ".join(str(w.value) for w in app.warning)
    assert "no cryptographic keys" in text
    assert "no live API" in text.replace("makes no live API calls", "no live API calls")
