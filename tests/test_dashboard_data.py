"""Tests for the committed dashboard artifact and its builder."""

from __future__ import annotations

import pytest

from ed_ops.config import RAW_DIR
from ed_ops.dashboard_data import DASHBOARD_DATA_PATH, load_dashboard_data

requires_full_data = pytest.mark.skipif(
    not (RAW_DIR / "nhs_scotland_ae_activity_monthly.csv").exists(),
    reason="Full PHS dataset absent -- run `python scripts/fetch_data.py` (see README Quickstart).",
)

EXPECTED_KEYS = {
    "panel_summary",
    "panel_preview",
    "annual_median",
    "split_summary",
    "split_box",
    "holdout_forecast",
    "feature_importance",
    "frozen_config",
    "meta",
}


def test_committed_artifact_present_and_shaped():
    assert DASHBOARD_DATA_PATH.exists(), "reports/dashboard_data.json is not committed"
    d = load_dashboard_data()
    assert EXPECTED_KEYS.issubset(d)
    assert d["panel_summary"]["rows"] == 7022
    assert d["panel_summary"]["sites"] == 35
    assert len(d["holdout_forecast"]) == 360
    assert set(d["split_box"]) == {"train", "validation", "holdout"}
    row = d["holdout_forecast"][0]
    assert {"site", "month", "actual", "pred_ca", "pred_pers"}.issubset(row)


@requires_full_data
def test_builder_reproduces_artifact_from_raw():
    from ed_ops.dashboard_data import build_dashboard_data

    d = build_dashboard_data()
    assert d["panel_summary"]["rows"] == 7022
    assert len(d["holdout_forecast"]) == 360
    assert d["frozen_config"]["ensemble_weight_ca"] == 0.4
