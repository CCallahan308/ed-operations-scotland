"""Headless smoke test: the Streamlit app renders every page without error.

Runs from the committed artifacts (no raw data, no model fit), so it runs on any
clone with the app dependencies installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.mark.parametrize("page", ["Overview", "The data", "The split", "Forecast", "Model"])
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.radio[0].set_value(page).run()
    assert not at.exception, f"{page} raised: {at.exception}"


def test_overview_headline_numbers_present():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    blob = " ".join(m.value for m in at.markdown)
    assert "holdout MAE" in blob
    assert "CI includes zero" in blob
    assert "near chance" in blob  # honest directional framing, not a success color
