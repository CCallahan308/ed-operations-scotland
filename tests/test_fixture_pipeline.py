"""End-to-end pipeline smoke tests on a committed fixture sample.

These run on ANY clone (no full dataset required): they exercise cleaning,
leak-free feature construction, the temporal split, baselines, evaluation, and a
model fit on a small committed subset of the real PHS data (5 sites). They assert
STRUCTURAL invariants (leak-free, valid ranges, runs deterministically), never
the project's published metrics -- those need the full dataset and live in the
@requires_full_data tests, which skip when it is absent.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from ed_ops import baselines as bl
from ed_ops import data_quality as dq
from ed_ops import features as fm
from ed_ops.evaluation import evaluate
from ed_ops.splits import build_temporal_split

FIXTURE = Path(__file__).parent / "fixtures" / "activity_sample.csv"


@pytest.fixture(scope="module")
def sample_raw():
    assert FIXTURE.exists(), "committed fixture tests/fixtures/activity_sample.csv is missing"
    return pd.read_csv(FIXTURE, dtype=str)


@pytest.fixture(scope="module")
def sample_panel(sample_raw):
    # The fixture omits the two quarantined bad site-months by design, so the
    # "quarantine removed 0 rows" warning is expected and intentionally ignored.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return dq.clean_activity_to_panel(sample_raw)


def test_fixture_present_and_git_friendly(sample_raw):
    assert len(sample_raw) > 100
    assert FIXTURE.stat().st_size < 500_000


def test_clean_panel_invariants(sample_panel):
    p = sample_panel
    assert (
        p["NumberWithin4HoursAll"] + p["NumberOver4HoursAll"] == p["NumberOfAttendancesAll"]
    ).all()
    assert ((p["compliance_pct"] >= 0) & (p["compliance_pct"] <= 100)).all()
    assert not p.duplicated(subset=["TreatmentLocation", "Month"]).any()


def test_features_are_leak_free(sample_panel):
    ff = fm.FeatureBuilder().build(panel=sample_panel)
    res = fm.check_feature_leakage(ff)
    assert res["L1_no_target_as_feature"] == "PASS"
    assert res["L1b_no_unlagged_compliance"] == "PASS"


def test_temporal_split_is_chronological(sample_panel):
    s = build_temporal_split(panel=sample_panel)
    assert s.train.end_month < s.validation.start_month
    assert s.validation.end_month < s.holdout.start_month
    assert len(s.train.df) > 0 and len(s.holdout.df) > 0


def test_persistence_baseline_is_plausible(sample_panel):
    preds = bl.run_all_baselines_on_partition((202401, 202505), panel=sample_panel)
    m = evaluate(preds["persistence"])
    assert 0.0 < m.mae < 40.0  # non-zero (no target leak), operationally plausible


def test_model_fits_and_predicts_in_range(sample_panel):
    ff = fm.FeatureBuilder().build(panel=sample_panel)
    cols = fm.FeatureBuilder().feature_columns()
    s = build_temporal_split(panel=sample_panel)
    lo_tr, hi_tr = s.windows["train"]
    lo_ho, hi_ho = s.windows["holdout"]
    tr = ff[(ff["target_month"] >= lo_tr) & (ff["target_month"] <= hi_tr)]
    ho = ff[(ff["target_month"] >= lo_ho) & (ff["target_month"] <= hi_ho)]
    model = HistGradientBoostingRegressor(random_state=20260721, max_depth=3, max_iter=60)
    model.fit(tr[cols].to_numpy(), tr["target_compliance"].to_numpy())
    pred = np.clip(model.predict(ho[cols].to_numpy()), 0, 100)
    assert len(pred) == len(ho)
    assert (pred >= 0).all() and (pred <= 100).all()


def test_rolling_feature_excludes_current_month():
    """Synthetic leak check: rolling-3 mean uses t-1..t-3, never the current month."""
    df = pd.DataFrame(
        {
            "TreatmentLocation": ["A"] * 6,
            "Month": [202301, 202302, 202303, 202304, 202305, 202306],
            "HBT": "S01",
            "NumberOfAttendancesAll": 1000,
            "NumberWithin4HoursAll": [800, 700, 600, 500, 400, 300],
            "NumberOver4HoursAll": [200, 300, 400, 500, 600, 700],
            "compliance_pct": [80.0, 70.0, 60.0, 50.0, 40.0, 30.0],
        }
    )
    ff = fm.FeatureBuilder().build(df)
    row5 = ff[ff["Month"] == 202305].iloc[0]
    assert row5["f_compliance_roll3_mean"] == pytest.approx(60.0, abs=0.01)
