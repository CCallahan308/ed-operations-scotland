"""Phase 4: Honest baselines.

Three baselines defined in docs/PROBLEM_FRAMING.md:

  B1 persistence:        forecast[t+1] = actual[t]            (per site)
  B2 seasonal naive:     forecast[t+1] = actual[t-11]         (per site, same
                                                             calendar month
                                                             one year prior)
  B3 site historical mean: forecast[t+1] = mean(actual[..t])  (per site, expanding)

All three use ONLY information through month t (the month before the forecast
target). This is enforced by construction: each baseline shifts known history
forward, never peeks at t+1.

The bar Candidate A must beat is B2 (seasonal naive) on MAE.
"""

from __future__ import annotations

import pandas as pd

from ed_ops.data_quality import build_primary_panel


def _prepare_history(panel: pd.DataFrame) -> pd.DataFrame:
    """Sort panel by site then month; add integer month + period index.

    Returns a copy with columns:
      TreatmentLocation, Month (YYYYMM int), month_idx (0-based per site),
      compliance_pct, NumberOfAttendancesAll
    """
    df = panel.copy()
    df["Month"] = df["Month"].astype(int)
    df = df.sort_values(["TreatmentLocation", "Month"]).reset_index(drop=True)
    # Per-site chronological index (0, 1, 2, ... within each site)
    df["month_idx"] = df.groupby("TreatmentLocation").cumcount()
    return df


def _attach_forecast_target(df: pd.DataFrame) -> pd.DataFrame:
    """Add `target_month`, `target_compliance` (the t+1 actual we will score
    against), and `prior_compliance` (the t actual, used for directional acc).

    Each output row represents a forecast made at month t for month t+1.
    Rows where t+1 does not exist in the data (end of each site's series) are
    dropped -- there is no ground truth to score against.
    """
    out = df.copy()
    # The 'next' row per site is the forecast target
    out["target_month"] = out.groupby("TreatmentLocation")["Month"].shift(-1)
    out["target_compliance"] = out.groupby("TreatmentLocation")["compliance_pct"].shift(-1)
    # prior_compliance == current compliance (the value at forecast time t)
    out["prior_compliance"] = out["compliance_pct"]
    # Drop rows with no target (last month per site)
    out = out.dropna(subset=["target_month", "target_compliance"]).copy()
    out["target_month"] = out["target_month"].astype(int)
    out["target_compliance"] = out["target_compliance"].astype(float)
    return out


def _restrict_to_partition(
    df: pd.DataFrame,
    partition_months: tuple[int, int],
    target_month_col: str = "target_month",
) -> pd.DataFrame:
    """Keep only rows whose forecast TARGET falls in the partition window.

    The forecast is MADE at t using only history through t, but we score it on
    the partition where t+1 lives. This is the leak-free way to evaluate: the
    features (history) precede the target, and the target is in the partition.
    """
    lo, hi = partition_months
    mask = (df[target_month_col] >= lo) & (df[target_month_col] <= hi)
    return df.loc[mask].copy()


# ---------------------------------------------------------------------------
# Baseline 1: persistence (forecast[t+1] = actual[t])
# ---------------------------------------------------------------------------


def baseline_persistence(panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """Forecast = this month's compliance (per site). Returns a frame with
    one row per forecastable (site, target_month), with a `prediction` column."""
    df = _attach_forecast_target(
        _prepare_history(panel if panel is not None else build_primary_panel())
    )
    df["prediction"] = df["prior_compliance"]
    return df


# ---------------------------------------------------------------------------
# Baseline 2: seasonal naive (forecast[t+1] = same calendar month last year)
# ---------------------------------------------------------------------------


def baseline_seasonal_naive(panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """Forecast = compliance from the same calendar month one year prior.

    For a forecast made at month t targeting month t+1, seasonal naive is the
    actual value at month (t+1) - 12 = t - 11. Implemented as lag-11 of the
    current row's compliance (NOT lag-12: that would give t-12, which is the
    wrong calendar month for forecasting t+1).

    If a site has insufficient history (< 12 months before the target), the
    forecast is unavailable (NaN) and that row is dropped -- we do not
    fabricate a substitute.
    """
    df = _attach_forecast_target(
        _prepare_history(panel if panel is not None else build_primary_panel())
    )
    # lag-11 within site: compliance at month (t-11) = same calendar month
    # as the target (t+1). Verified: target=202401 -> lag11 of row 202312
    # is the value at 202301 (Jan-2023), which is what we want.
    df["seasonal_compliance"] = df.groupby("TreatmentLocation")["compliance_pct"].shift(11)
    df["prediction"] = df["seasonal_compliance"]
    # Drop rows where the seasonal forecast is unavailable
    df = df.dropna(subset=["prediction"]).copy()
    df["prediction"] = df["prediction"].astype(float)
    return df


# ---------------------------------------------------------------------------
# Baseline 3: site expanding historical mean
# ---------------------------------------------------------------------------


def baseline_site_historical_mean(
    panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Forecast = mean of all prior compliance for that site, expanding.

    Uses an expanding-window mean computed BEFORE the forecast target, so
    only history through month t contributes. The first month per site has
    no prior history and is dropped.
    """
    df = _attach_forecast_target(
        _prepare_history(panel if panel is not None else build_primary_panel())
    )
    # Expanding mean EXCLUDING the current row: shift(1) then expanding mean.
    # This ensures forecast[t+1] = mean(actual[..t-1])... actually we want
    # mean(actual[..t]) = mean through current month. Use expanding on the
    # unshifted series with min_periods=1, then this row's value already
    # includes the current month -- so we take the value as-is.
    df["expanding_mean"] = df.groupby("TreatmentLocation")["compliance_pct"].transform(
        lambda s: s.expanding(min_periods=1).mean()
    )
    # The expanding mean at row t includes actual[t], which is known at
    # forecast time t. That is the forecast for t+1.
    df["prediction"] = df["expanding_mean"]
    return df


# ---------------------------------------------------------------------------
# Convenience: score all baselines on a partition
# ---------------------------------------------------------------------------

BASELINE_NAMES = ("persistence", "seasonal_naive", "site_historical_mean")


def run_all_baselines_on_partition(
    partition_months: tuple[int, int],
    panel: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build all three baselines and restrict each to the target partition.

    Returns {name: prediction_frame} where each frame has the columns needed
    by ed_ops.evaluation.evaluate: TreatmentLocation, target_month,
    target_compliance (actual), prior_compliance, prediction.
    """
    p = panel if panel is not None else build_primary_panel()
    out = {
        "persistence": _restrict_to_partition(baseline_persistence(p), partition_months),
        "seasonal_naive": _restrict_to_partition(baseline_seasonal_naive(p), partition_months),
        "site_historical_mean": _restrict_to_partition(
            baseline_site_historical_mean(p), partition_months
        ),
    }
    return out
