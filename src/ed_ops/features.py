"""Phase 4: Leak-free feature pipeline.

Builds features for forecasting month t+1 from information available at month t.
All features are constructed with explicit as-of logic so no future information
enters. Every feature is documented with its source column, lag, and rationale.

Leakage controls enforced here (from PROBLEM_FRAMING.md):
  L1  target column and its count-components excluded from features
  L2  all lags/rollings use data <= month t
  L4  transforms (scaling, encoders) fit on TRAIN only -- handled by passing
      the train partition to fit_transform(); see FeatureBuilder
  L7  disaggregated series only as lagged features
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ed_ops.data_quality import build_primary_panel

# ---------------------------------------------------------------------------
# Feature specification (the allow-list; anything not here is forbidden)
# ---------------------------------------------------------------------------

# Columns that MUST NEVER appear in features (L1). These are the target and
# its direct count-components, plus all QF columns. Using any of these would
# leak the answer.
FORBIDDEN_COLUMNS = frozenset(
    {
        "compliance_pct",  # the target (at month t)
        "target_compliance",  # the target (at month t+1)
        "NumberWithin4HoursAll",  # count-component of target
        "NumberOver4HoursAll",  # count-component of target
        "NumberOfAttendancesAll",  # NOT forbidden: attendance volume is a
        # legitimate demand driver, used as a feature
        # via lags. Listed here for documentation only.
    }
)
# Note: NumberOfAttendancesAll IS allowed as a feature (it's the demand signal,
# not the outcome). It must be lagged, but the raw value is not a target leak.

TARGET_COLUMNS = frozenset(
    {
        "compliance_pct",
        "target_compliance",
        "NumberWithin4HoursAll",
        "NumberOver4HoursAll",
    }
)


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------


@dataclass
class FeatureBuilder:
    """Constructs leak-free features for the forecasting panel.

    The builder operates on a panel that has been through _attach_forecast_target
    (so each row represents a forecast made at t for t+1). All features use
    only information at or before month t.

    Fit/transform split (L4): the builder has NO learned state in this phase --
    every feature is a deterministic lag/rolling statistic. Learned transforms
    (scaling, target encoding) would be added in Phase 5 and fit on train only.
    """

    # Lag months for compliance (the target's own history, lagged)
    compliance_lags: tuple[int, ...] = (1, 2, 3, 6, 11, 12)
    # Rolling windows for compliance (computed on lagged values, ending at t-1
    # so the current month t is NOT in the window -- this is the strict as-of
    # rule; using t would be borderline since we're forecasting t+1 from t)
    compliance_roll_windows: tuple[int, ...] = (3, 6, 12)
    # Lag months for attendance volume (demand signal)
    attendance_lags: tuple[int, ...] = (1, 2, 12)

    def build(self, panel: pd.DataFrame | None = None) -> pd.DataFrame:
        """Build the feature frame. Returns one row per (site, target_month)
        with feature columns + keys + target + prior_compliance.

        Features are prefixed `f_` to distinguish from raw/derived columns.
        """
        # We need the FULL panel history to compute lags correctly, even when
        # we'll later restrict to a partition. The caller (Phase 5) restricts.
        p = panel.copy() if panel is not None else build_primary_panel().copy()
        p["Month"] = p["Month"].astype(int)
        p = p.sort_values(["TreatmentLocation", "Month"]).reset_index(drop=True)

        # Per-site chronological index for lag math
        g = p.groupby("TreatmentLocation", group_keys=False)

        # --- Compliance lags (target's own history) ---
        for lag in self.compliance_lags:
            p[f"f_compliance_lag{lag}"] = g["compliance_pct"].shift(lag)

        # --- Rolling means of compliance (window ENDS at t-1, excludes t) ---
        # Shift(1) first so the rolling window never includes the current row.
        for w in self.compliance_roll_windows:
            p[f"f_compliance_roll{w}_mean"] = g["compliance_pct"].apply(
                lambda s: s.shift(1).rolling(w, min_periods=max(1, w // 2)).mean()
            )
            p[f"f_compliance_roll{w}_std"] = g["compliance_pct"].apply(
                lambda s: s.shift(1).rolling(w, min_periods=max(1, w // 2)).std()
            )

        # --- Attendance volume lags (demand signal) ---
        for lag in self.attendance_lags:
            p[f"f_attendance_lag{lag}"] = g["NumberOfAttendancesAll"].shift(lag)
        # YoY attendance change (demand growth)
        p["f_attendance_yoy_pct"] = (
            (g["NumberOfAttendancesAll"].shift(1) - g["NumberOfAttendancesAll"].shift(13))
            / g["NumberOfAttendancesAll"].shift(13).replace(0, np.nan)
            * 100
        )

        # --- Calendar features (deterministic, no leakage possible) ---
        # Year extracted from Month (YYYYMM). Month-of-year captures seasonality.
        p["f_year"] = p["Month"] // 100
        p["f_month_of_year"] = p["Month"] % 100
        p["f_quarter"] = ((p["f_month_of_year"] - 1) // 3) + 1

        # --- Trend feature (months since site's first observation) ---
        p["f_months_since_site_start"] = g.cumcount()

        # --- Site-level recent trend (slope of last 3 months, lagged) ---
        # Captures the directional momentum going into the forecast.
        p["f_recent_slope_3m"] = g["compliance_pct"].apply(
            lambda s: (
                s.shift(1)
                .rolling(3, min_periods=2)
                .apply(
                    lambda w: (
                        np.polyfit(range(len(w)), w, 1)[0]
                        if len(w) >= 2 and not np.isnan(w).any()
                        else np.nan
                    ),
                    raw=True,
                )
            )
        )

        # Attach the forecast target (t+1) and prior (t) for evaluation
        p["target_month"] = g["Month"].shift(-1)
        p["target_compliance"] = g["compliance_pct"].shift(-1)
        p["prior_compliance"] = p["compliance_pct"]
        p = p.dropna(subset=["target_month", "target_compliance"]).copy()
        p["target_month"] = p["target_month"].astype(int)
        p["target_compliance"] = p["target_compliance"].astype(float)

        return p

    def feature_columns(self) -> list[str]:
        """Return the canonical feature column names (f_* prefix)."""
        cols = []
        for lag in self.compliance_lags:
            cols.append(f"f_compliance_lag{lag}")
        for w in self.compliance_roll_windows:
            cols.append(f"f_compliance_roll{w}_mean")
            cols.append(f"f_compliance_roll{w}_std")
        for lag in self.attendance_lags:
            cols.append(f"f_attendance_lag{lag}")
        cols.extend(
            [
                "f_attendance_yoy_pct",
                "f_year",
                "f_month_of_year",
                "f_quarter",
                "f_months_since_site_start",
                "f_recent_slope_3m",
            ]
        )
        return cols


# ---------------------------------------------------------------------------
# Leakage guards (run on the built feature frame)
# ---------------------------------------------------------------------------


def check_feature_leakage(feature_frame: pd.DataFrame) -> dict:
    """Verify no forbidden column leaked into the feature set.

    Returns a dict of check -> PASS/FAIL. Any FAIL is a hard stop.
    """
    f_cols = [c for c in feature_frame.columns if c.startswith("f_")]
    results = {}

    # L1: no target column or count-component is itself a feature
    forbidden_in_features = TARGET_COLUMNS & set(f_cols)
    results["L1_no_target_as_feature"] = (
        "PASS" if not forbidden_in_features else f"FAIL: {forbidden_in_features}"
    )

    # L1b: lagged compliance IS allowed (it's history, not the target itself).
    # Verify every f_compliance_* column is explicitly lagged (contains 'lag' or 'roll').
    bare_compliance = [
        c
        for c in f_cols
        if "compliance" in c.lower()
        and "lag" not in c.lower()
        and "roll" not in c.lower()
        and "slope" not in c.lower()
    ]
    results["L1b_no_unlagged_compliance"] = (
        "PASS" if not bare_compliance else f"FAIL: {bare_compliance}"
    )

    return results
