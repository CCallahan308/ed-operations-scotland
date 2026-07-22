"""Tests for Phase 4 baselines and evaluation protocol.

These tests enforce two things that matter most:
1. Baselines use only history through month t (no future leakage).
2. evaluate() scores against the true t+1 target, never the prior value.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ed_ops import baselines, evaluation
from ed_ops.config import RAW_DIR
from ed_ops.splits import build_temporal_split

requires_full_data = pytest.mark.skipif(
    not (RAW_DIR / "nhs_scotland_ae_activity_monthly.csv").exists(),
    reason="Full PHS dataset absent -- run `python scripts/fetch_data.py` (see README Quickstart).",
)

# ---------------------------------------------------------------------------
# Synthetic fixtures with KNOWN answers (so we can verify the math)
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_panel():
    """Two sites, 18 months each, with a known pattern.

    Site A: linear decline 100, 95, 90, 85, ... (5pp/month down)
    Site B: seasonal 80, 70, 80, 70, ... (alternating)

    persistence[t+1] = actual[t]
    seasonal_naive[t+1] = actual[t-11]  (same month last year)
    """
    rows = []
    # Site A: months 202301..202306 (so seasonal has a 12-month lookback)
    a_pattern = [100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15]
    a_months = [
        202301,
        202302,
        202303,
        202304,
        202305,
        202306,
        202307,
        202308,
        202309,
        202310,
        202311,
        202312,
        202401,
        202402,
        202403,
        202404,
        202405,
        202406,
    ]
    for m, v in zip(a_months, a_pattern):
        rows.append(
            {
                "TreatmentLocation": "A",
                "Month": str(m),
                "HBT": "S01",
                "NumberOfAttendancesAll": 1000,
                "NumberWithin4HoursAll": int(10 * v),
                "NumberOver4HoursAll": int(1000 - 10 * v),
                "compliance_pct": float(v),
            }
        )
    # Site B: alternating
    b_pattern = [80, 70, 80, 70, 80, 70, 80, 70, 80, 70, 80, 70, 80, 70, 80, 70, 80, 70]
    for m, v in zip(a_months, b_pattern):
        rows.append(
            {
                "TreatmentLocation": "B",
                "Month": str(m),
                "HBT": "S01",
                "NumberOfAttendancesAll": 1000,
                "NumberWithin4HoursAll": int(10 * v),
                "NumberOver4HoursAll": int(1000 - 10 * v),
                "compliance_pct": float(v),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Baseline leakage controls
# ---------------------------------------------------------------------------


class TestBaselineNoLeakage:
    """Every baseline must forecast t+1 using only data through t."""

    def test_persistence_uses_prior_month_not_target(self, synthetic_panel):
        """Persistence prediction[t+1] must equal actual[t], NOT actual[t+1]."""
        preds = baselines.baseline_persistence(synthetic_panel)
        # For every row, prediction == prior_compliance (the t value)
        assert (preds["prediction"] == preds["prior_compliance"]).all()
        # And prediction must NOT equal target (that would be leakage)
        assert not (preds["prediction"] == preds["target_compliance"]).all()

    def test_seasonal_naive_forecasts_same_calendar_month_last_year(self, synthetic_panel):
        """Seasonal naive for target t+1 must equal actual at month (t+1)-12,
        i.e. the same calendar month one year prior. Implemented as lag-11 of
        the current row (NOT lag-12)."""
        preds = baselines.baseline_seasonal_naive(synthetic_panel)
        # Site B in 2024-01 (target_month) should forecast 80 (the Jan-2023 value)
        b_202401 = preds[(preds["TreatmentLocation"] == "B") & (preds["target_month"] == 202401)]
        assert len(b_202401) == 1
        # B alternates 80,70,80,70,... Jan-2023=80, so Jan-2024 forecast=80
        assert b_202401["prediction"].iloc[0] == 80.0
        # Actual 2024-01 for B is also 80 (alternating repeats), so perfect
        assert b_202401["target_compliance"].iloc[0] == 80.0

    def test_seasonal_naive_drops_short_history(self, synthetic_panel):
        """Rows where the year-ago month doesn't exist must be dropped, not
        fabricated. The first forecastable target per site is month 13
        (needs the month-1 value from 12 months prior)."""
        preds = baselines.baseline_seasonal_naive(synthetic_panel)
        # Synthetic sites start at 202301. First forecastable target is 202401
        # (Jan-2024), which needs Jan-2023 = the first row.
        for site in ("A", "B"):
            site_preds = preds[preds["TreatmentLocation"] == site]
            assert site_preds["target_month"].min() >= 202401

    def test_site_historical_mean_excludes_future(self, synthetic_panel):
        """Expanding mean must include only current and prior months,
        never the target or later."""
        preds = baselines.baseline_site_historical_mean(synthetic_panel)
        # For site A (declining 100,95,90,...), the forecast for month 3
        # (target 202303, actual 90) made at month 2 (actual 95) should be
        # mean(100, 95) = 97.5
        a_202303 = preds[(preds["TreatmentLocation"] == "A") & (preds["target_month"] == 202303)]
        assert len(a_202303) == 1
        assert a_202303["prediction"].iloc[0] == pytest.approx(97.5, abs=0.01)


# ---------------------------------------------------------------------------
# evaluate() correctness (regression test for the column-name bug)
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_scores_against_target_not_prior(self):
        """REGRESSION GUARD: the default target_col must be 'target_compliance',
        not 'compliance_pct'. If this regresses, persistence would show MAE=0."""
        df = pd.DataFrame(
            {
                "TreatmentLocation": ["A"] * 3,
                "compliance_pct": [80.0, 70.0, 60.0],  # prior (t)
                "target_compliance": [70.0, 60.0, 50.0],  # actual (t+1)
                "prior_compliance": [80.0, 70.0, 60.0],  # for direction
                "prediction": [80.0, 70.0, 60.0],  # persistence
            }
        )
        m = evaluation.evaluate(df)
        # Persistence prediction (80,70,60) vs target (70,60,50) -> errors 10,10,10
        assert m.mae == pytest.approx(10.0, abs=0.001)
        # If target_col regressed to 'compliance_pct', mae would be 0
        assert m.mae > 0

    def test_clip_predictions_to_bounds(self):
        df = pd.DataFrame(
            {
                "TreatmentLocation": ["A"] * 2,
                "target_compliance": [50.0, 80.0],
                "prior_compliance": [40.0, 70.0],
                "prediction": [150.0, -10.0],  # out of bounds
            }
        )
        m = evaluation.evaluate(df, clip_predictions=True)
        # Clipped to [0,100]: preds become 100, 0; errors 50, 80
        assert m.mae == pytest.approx(65.0, abs=0.001)

    def test_per_site_equity_metrics(self):
        df = pd.DataFrame(
            {
                "TreatmentLocation": ["A", "A", "B", "B"],
                "target_compliance": [50.0, 50.0, 80.0, 80.0],
                "prior_compliance": [40.0, 40.0, 70.0, 70.0],
                "prediction": [55.0, 55.0, 75.0, 75.0],  # site A err 5, site B err 5
            }
        )
        m = evaluation.evaluate(df)
        assert m.per_site_mae_median == pytest.approx(5.0, abs=0.001)
        assert m.per_site_mae_iqr == pytest.approx(0.0, abs=0.001)  # equal sites

    def test_compare_models_sorted_by_mae(self):
        df_good = pd.DataFrame(
            {
                "TreatmentLocation": ["A"],
                "target_compliance": [70.0],
                "prior_compliance": [80.0],
                "prediction": [71.0],
            }
        )
        df_bad = pd.DataFrame(
            {
                "TreatmentLocation": ["A"],
                "target_compliance": [70.0],
                "prior_compliance": [80.0],
                "prediction": [50.0],
            }
        )
        results = {"good": evaluation.evaluate(df_good), "bad": evaluation.evaluate(df_bad)}
        comp = evaluation.compare_models(results)
        assert comp.index[0] == "good"  # lower MAE first
        assert comp.index[1] == "bad"


# ---------------------------------------------------------------------------
# Real-data sanity (baselines must not produce absurd metrics)
# ---------------------------------------------------------------------------


@requires_full_data
class TestRealDataBaselines:
    """On the real panel, baselines must produce plausible metrics. These
    tests catch the kind of bug where a column mix-up produces MAE=0."""

    @pytest.fixture(scope="class")
    def val_preds(self):
        split = build_temporal_split()
        return baselines.run_all_baselines_on_partition(split.windows["validation"])

    def test_persistence_mae_is_nonzero_and_plausible(self, val_preds):
        m = evaluation.evaluate(val_preds["persistence"])
        # Month-to-month compliance moves: persistence MAE must be > 0
        # and operationally plausible (single-digit pp on average).
        assert m.mae > 0.5, f"persistence MAE suspiciously low: {m.mae}"
        assert m.mae < 20.0, f"persistence MAE suspiciously high: {m.mae}"

    def test_seasonal_naive_mae_is_nonzero_and_plausible(self, val_preds):
        m = evaluation.evaluate(val_preds["seasonal_naive"])
        assert m.mae > 0.5
        assert m.mae < 20.0

    def test_seasonal_naive_beats_site_historical_mean(self, val_preds):
        """The seasonal naive should outperform the long-run site mean on a
        drifting series (per PROBLEM_FRAMING.md the bar is seasonal naive)."""
        m_sn = evaluation.evaluate(val_preds["seasonal_naive"])
        m_hm = evaluation.evaluate(val_preds["site_historical_mean"])
        assert m_sn.mae < m_hm.mae

    def test_directional_accuracy_in_valid_range(self, val_preds):
        for name, preds in val_preds.items():
            m = evaluation.evaluate(preds)
            # Directional accuracy must be in [0, 1]. A model that always
            # predicts 'no change' (persistence) will score near 0 here
            # because compliance moves almost every month -- that is correct,
            # not a bug.
            assert 0.0 <= m.directional_accuracy <= 1.0
