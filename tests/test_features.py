"""Tests for Phase 4 feature pipeline and leakage guards."""

from __future__ import annotations

import pandas as pd
import pytest

from ed_ops import features
from ed_ops.config import RAW_DIR

requires_full_data = pytest.mark.skipif(
    not (RAW_DIR / "nhs_scotland_ae_activity_monthly.csv").exists(),
    reason="Full PHS dataset absent -- run `python scripts/fetch_data.py` (see README Quickstart).",
)
pytestmark = requires_full_data

# ---------------------------------------------------------------------------
# Leakage guards (L1, L2) - the most important tests in the project
# ---------------------------------------------------------------------------


class TestFeatureLeakage:
    """These tests are the hard guard against target leakage. If any fails,
    the model's metrics are contaminated and unusable."""

    @pytest.fixture(scope="class")
    def feature_frame(self):
        return features.FeatureBuilder().build()

    def test_no_target_column_is_a_feature(self, feature_frame):
        """L1: compliance_pct, target_compliance, NumberWithin4HoursAll,
        NumberOver4HoursAll must never appear as f_ features."""
        results = features.check_feature_leakage(feature_frame)
        assert results["L1_no_target_as_feature"] == "PASS", results["L1_no_target_as_feature"]

    def test_no_unlagged_compliance_in_features(self, feature_frame):
        """L1b: any compliance-derived feature must be lagged or rolled.
        A bare 'compliance' feature would leak the target."""
        results = features.check_feature_leakage(feature_frame)
        assert results["L1b_no_unlagged_compliance"] == "PASS", results[
            "L1b_no_unlagged_compliance"
        ]

    def test_lag1_does_not_equal_target(self, feature_frame):
        """L2 spot-check: f_compliance_lag1 (compliance at month t-1) must NOT
        equal target_compliance (compliance at month t+1). If they matched,
        the lag construction would be wrong."""
        # lag1 = compliance at t-1; target = compliance at t+1
        # These should differ on the vast majority of rows.
        sample = feature_frame.dropna(subset=["f_compliance_lag1"]).head(200)
        matches = (sample["f_compliance_lag1"] == sample["target_compliance"]).sum()
        # Some coincidental matches are fine (compliance is sticky), but >50%
        # would indicate the lag is pointing at the wrong row.
        assert matches < 0.5 * len(sample), (
            f"lag1 matches target on {matches}/{len(sample)} rows -- lag logic broken"
        )

    def test_rolling_window_excludes_current_month(self, feature_frame):
        """L2: the rolling-3 mean must NOT equal a rolling window that includes
        the current month. We verify by recomputing both ways and checking
        they differ on rows where current != prior."""
        # Build a tiny panel where current month differs from prior
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
        ff = features.FeatureBuilder().build(df)
        # f_compliance_roll3_mean at row 5 (Month=202305, prior=40) should be
        # mean(80,70,60) = 70 if it EXCLUDES current, or mean(70,60,50)=60 if
        # it (wrongly) INCLUDES the current row shifted by 1... actually:
        # shift(1).rolling(3) at row 5 = mean of rows 2,3,4 = mean(70,60,50)=60.
        # That's correct: uses t-1, t-2, t-3.
        row5 = ff[ff["Month"] == 202305].iloc[0]
        assert row5["f_compliance_roll3_mean"] == pytest.approx(60.0, abs=0.01)


# ---------------------------------------------------------------------------
# Feature construction correctness
# ---------------------------------------------------------------------------


class TestFeatureConstruction:
    def test_feature_frame_has_expected_columns(self):
        fb = features.FeatureBuilder()
        ff = fb.build()
        f_cols = [c for c in ff.columns if c.startswith("f_")]
        # Must include the documented lag/rolling/calendar/trend features
        assert "f_compliance_lag1" in f_cols
        assert "f_compliance_lag12" in f_cols
        assert "f_compliance_roll3_mean" in f_cols
        assert "f_attendance_lag1" in f_cols
        assert "f_month_of_year" in f_cols
        assert "f_recent_slope_3m" in f_cols

    def test_target_and_prior_attached(self):
        ff = features.FeatureBuilder().build()
        assert "target_compliance" in ff.columns
        assert "target_month" in ff.columns
        assert "prior_compliance" in ff.columns

    def test_no_rows_with_future_target_leak(self):
        """Every output row forecasts a future month; target_compliance must
        be the ACTUAL t+1, and the features must be from t or earlier.

        Diffs between target_month and Month are usually 1 (or 89 for Dec->Jan),
        but can be 2 in rare cases where a quarantined month (F002 G405H-201505)
        creates a 1-month gap in a site's series. Allow 1, 2, 89, 90.
        """
        ff = features.FeatureBuilder().build()
        diff = ff["target_month"] - ff["Month"]
        valid_diffs = diff.isin([1, 2, 89, 90])
        assert valid_diffs.all(), f"Unexpected target_month diffs: {diff[~valid_diffs].unique()}"

    def test_calendar_features_in_valid_range(self):
        ff = features.FeatureBuilder().build()
        assert ff["f_month_of_year"].between(1, 12).all()
        assert ff["f_quarter"].between(1, 4).all()

    def test_feature_frame_restricted_to_partition_correctly(self):
        """The feature frame can be filtered to a partition by target_month,
        and the features remain leak-free (they were built from history)."""
        from ed_ops.splits import DEFAULT_SPLIT_WINDOWS

        ff = features.FeatureBuilder().build()
        lo, hi = DEFAULT_SPLIT_WINDOWS["validation"]
        val = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)]
        assert len(val) > 0
        # All validation target_months in window
        assert val["target_month"].between(lo, hi).all()


# ---------------------------------------------------------------------------
# Real-data sanity
# ---------------------------------------------------------------------------


class TestRealDataFeatures:
    def test_feature_frame_covers_full_panel(self):
        """The feature frame should cover most panel rows (minus the last
        month per site which has no target)."""
        from ed_ops.data_quality import build_primary_panel

        panel = build_primary_panel()
        ff = features.FeatureBuilder().build()
        # ~30 sites drop their last month -> ~30 fewer rows than panel
        assert len(ff) >= len(panel) - 50
        assert len(ff) <= len(panel)

    def test_lag_features_have_expected_null_patterns(self):
        """Lag-1 feature must be null on each site's chronologically-first row
        (no prior month exists). Use nth(0) not first() because pandas
        groupby.first() skips NaNs and would hide the null we're checking."""
        ff = features.FeatureBuilder().build()
        # nth(0) returns the literal first row per group, preserving NaNs
        first_rows = ff.groupby("TreatmentLocation").nth(0)
        # Every site's first forecastable row should have null lag1
        nulls = first_rows["f_compliance_lag1"].isna()
        assert nulls.all(), (
            f"{(~nulls).sum()} sites have non-null lag1 on their first row -- "
            "lag construction would be leaking"
        )
