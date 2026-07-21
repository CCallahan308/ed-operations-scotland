"""Phase 4: Evaluation protocol and metrics.

Implements the metrics defined in docs/PROBLEM_FRAMING.md:
  - Primary: MAE in percentage points (operationally interpretable)
  - Secondary: RMSE, directional accuracy, per-site MAE distribution

All metrics computed on the SAME validation partition so Candidate A and every
baseline are directly comparable. The holdout is NOT touched here; it is scored
exactly once in Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Metrics:
    """Evaluation metrics for one model on one partition.

    All error metrics are in compliance-percentage-points. The target
    `compliance_pct` is bounded [0, 100]; predictions are clipped to [0, 100]
    before scoring so the metric reflects operational error, not numerical
    overshoot.
    """

    n: int
    mae: float  # mean absolute error (pp) -- PRIMARY
    rmse: float  # root mean squared error (pp)
    directional_accuracy: float  # fraction of rows where predicted direction
    # (up/down vs prior month) matches actual
    median_abs_error: float
    p90_abs_error: float
    mean_error: float  # signed; positive = over-prediction bias
    per_site_mae_median: float  # equity: median of per-site MAE
    per_site_mae_iqr: float  # equity: IQR of per-site MAE

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "directional_accuracy": round(self.directional_accuracy, 4),
            "median_abs_error": round(self.median_abs_error, 4),
            "p90_abs_error": round(self.p90_abs_error, 4),
            "mean_error": round(self.mean_error, 4),
            "per_site_mae_median": round(self.per_site_mae_median, 4),
            "per_site_mae_iqr": round(self.per_site_mae_iqr, 4),
        }

    def summary(self, name: str = "") -> str:
        header = f"[{name}]" if name else "[metrics]"
        return (
            f"{header}  n={self.n}  "
            f"MAE={self.mae:.2f}pp  RMSE={self.rmse:.2f}pp  "
            f"dir_acc={self.directional_accuracy:.1%}  "
            f"bias={self.mean_error:+.2f}pp  "
            f"per_site_mae[median={self.per_site_mae_median:.2f}, IQR={self.per_site_mae_iqr:.2f}]"
        )


def evaluate(
    predictions: pd.DataFrame,
    *,
    target_col: str = "target_compliance",
    pred_col: str = "prediction",
    prior_col: str = "prior_compliance",
    site_col: str = "TreatmentLocation",
    clip_predictions: bool = True,
    direction_tolerance_pp: float = 0.5,
) -> Metrics:
    """Compute Metrics for a prediction frame.

    Parameters
    ----------
    predictions : DataFrame
        Must contain: `site_col`, `target_col` (the actual t+1 value we score
        against), `pred_col` (the forecast), and `prior_col` (the actual t
        value, used as the directional-change reference). One row per
        (site, forecast month).
    target_col : str
        Default 'target_compliance' (NOT 'compliance_pct' -- that column is
        the prior-month value, not the forecast target).
    clip_predictions : bool
        If True, clip predictions to [0, 100] before scoring. The target is
        bounded; unclipped numeric overshoot is not operationally meaningful.
    direction_tolerance_pp : float
        Changes smaller than this (in pp) are treated as 'no change' for
        directional accuracy. Compliance moves almost every month at the
        raw level; tiny movements are noise, not signal.

    Returns
    -------
    Metrics
    """
    df = predictions.copy()
    if clip_predictions:
        df[pred_col] = df[pred_col].clip(lower=0.0, upper=100.0)

    actual = df[target_col].astype(float).to_numpy()
    pred = df[pred_col].astype(float).to_numpy()
    prior = df[prior_col].astype(float).to_numpy()

    err = pred - actual
    abs_err = np.abs(err)

    # Directional accuracy with tolerance: changes within +/- tol count as
    # 'flat'. A forecast is directionally correct if its signed direction
    # matches the actual signed direction.
    actual_change = actual - prior
    pred_change = pred - prior
    actual_dir = np.where(
        np.abs(actual_change) <= direction_tolerance_pp, 0, np.sign(actual_change)
    )
    pred_dir = np.where(np.abs(pred_change) <= direction_tolerance_pp, 0, np.sign(pred_change))
    dir_correct = pred_dir == actual_dir
    dir_acc = float(dir_correct.mean())

    # Per-site MAE distribution (equity)
    per_site = df.assign(_abs_err=abs_err).groupby(site_col)["_abs_err"].mean()

    return Metrics(
        n=len(df),
        mae=float(abs_err.mean()),
        rmse=float(np.sqrt((err**2).mean())),
        directional_accuracy=dir_acc,
        median_abs_error=float(np.median(abs_err)),
        p90_abs_error=float(np.percentile(abs_err, 90)),
        mean_error=float(err.mean()),
        per_site_mae_median=float(per_site.median()),
        per_site_mae_iqr=float(per_site.quantile(0.75) - per_site.quantile(0.25)),
    )


def compare_models(results: dict[str, Metrics]) -> pd.DataFrame:
    """Return a comparison table of models -> metrics, sorted by MAE ascending.

    `results` maps a model name to its Metrics on the same partition.
    """
    rows = [v.as_dict() | {"model": k} for k, v in results.items()]
    df = pd.DataFrame(rows).set_index("model")
    return df.sort_values("mae")
