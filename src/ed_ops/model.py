"""Phase 5: Candidate A model.

Candidate A is a histogram gradient-boosted regression tree (sklearn
HistGradientBoostingRegressor) trained to predict next-month site-level
4-hour compliance %.

Why this model:
  - Handles the mixed feature types (continuous lags, calendar integers,
    trend) without manual scaling.
  - Native NaN handling lets us keep rows with short rolling-window history
    instead of imputing or dropping (relevant for the COVID-era boundary).
  - Captures interactions (e.g. recent slope x seasonal lag) that linear
    models miss and that may help bridge the structural break.
  - Fast, deterministic with a fixed seed, reproducible.

Selection protocol (leakage-safe):
  - Hyperparameters selected EXCLUSIVELY on the validation partition.
  - Train partition is used for fitting; validation for scoring/selection.
  - Holdout is never touched in this phase (L5).

The model is wrapped in a class so the frozen configuration (Phase 6) is
explicit and the artifact is self-describing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ed_ops import features as features_mod
from ed_ops.config import RANDOM_SEED, REPORTS_DIR
from ed_ops.evaluation import evaluate
from ed_ops.splits import (
    DEFAULT_SPLIT_WINDOWS,
    Split,
    build_temporal_split,
)

# ---------------------------------------------------------------------------
# Default hyperparameter grid (Phase 5 search space)
# ---------------------------------------------------------------------------
# Modest grid; selected by validation MAE. Each candidate is fit on TRAIN
# and scored on VALIDATION only. The holdout is never used here.

DEFAULT_PARAM_GRID: list[dict] = [
    # Baseline-ish: shallow, conservative
    {
        "max_depth": 3,
        "learning_rate": 0.05,
        "max_iter": 200,
        "l2_regularization": 1.0,
        "min_samples_leaf": 50,
    },
    # Medium
    {
        "max_depth": 4,
        "learning_rate": 0.05,
        "max_iter": 300,
        "l2_regularization": 0.5,
        "min_samples_leaf": 30,
    },
    {
        "max_depth": 5,
        "learning_rate": 0.05,
        "max_iter": 400,
        "l2_regularization": 0.5,
        "min_samples_leaf": 30,
    },
    # Deeper, slower learning
    {
        "max_depth": 5,
        "learning_rate": 0.03,
        "max_iter": 500,
        "l2_regularization": 1.0,
        "min_samples_leaf": 40,
    },
    # Very shallow (close to a trend + mean shift model)
    {
        "max_depth": 2,
        "learning_rate": 0.05,
        "max_iter": 300,
        "l2_regularization": 1.0,
        "min_samples_leaf": 50,
    },
]


@dataclass
class CandidateAConfig:
    """Frozen configuration for Candidate A. Recorded at freeze time (Phase 6).

    Candidate A is an ENSEMBLE: a weighted blend of a gradient-boosted
    regression tree and the persistence baseline. The blend weight was
    selected on validation (D019): w_ca=0.4 (Candidate A) + 0.6 persistence.
    This ensemble beat both components on validation MAE and wins on 28/30
    sites (robust, not a knife-edge).
    """

    # Model family
    model_family: str = "HistGradientBoostingRegressor + persistence ensemble"
    # Hyperparameters. Defaults ARE the frozen Phase 5 selection (D018) so that
    # CandidateAConfig() constructs the same model train_candidate_a() produces.
    # If these are changed, update tests/test_model.py::test_selected_hyperparams_match_D018
    # and reports/candidate_a_config.json together.
    max_depth: int = 5
    learning_rate: float = 0.03
    max_iter: int = 500
    l2_regularization: float = 1.0
    min_samples_leaf: int = 40
    # Ensemble weight (selected on validation, D019): w*CA + (1-w)*persistence
    ensemble_weight_ca: float = 0.4
    # Feature spec
    feature_builder_params: dict = field(
        default_factory=lambda: {
            "compliance_lags": (1, 2, 3, 6, 11, 12),
            "compliance_roll_windows": (3, 6, 12),
            "attendance_lags": (1, 2, 12),
        }
    )
    # Reproducibility
    random_seed: int = RANDOM_SEED
    # Training data window
    train_window: tuple = DEFAULT_SPLIT_WINDOWS["train"]
    validation_window: tuple = DEFAULT_SPLIT_WINDOWS["validation"]

    def to_dict(self) -> dict:
        d = asdict(self)
        # Tuples -> lists for JSON
        d["feature_builder_params"] = {k: list(v) for k, v in self.feature_builder_params.items()}
        d["train_window"] = list(self.train_window)
        d["validation_window"] = list(self.validation_window)
        return d


@dataclass
class CandidateA:
    """A trained Candidate A model + its frozen config.

    Final prediction = ensemble_weight_ca * boosted_tree + (1 - w) * persistence,
    where persistence = prior_compliance (the t value, available at forecast
    time). Both components are computed on the same feature frame.
    """

    config: CandidateAConfig
    model: HistGradientBoostingRegressor
    feature_columns: list[str]
    val_metrics: dict  # metrics on validation (selection partition)
    fit_row_count: int

    def predict_tree(self, feature_frame: pd.DataFrame) -> np.ndarray:
        """Raw gradient-boosted-tree prediction (component 1). Clips to [0,100]."""
        X = feature_frame[self.feature_columns].to_numpy()
        return np.clip(self.model.predict(X), 0.0, 100.0)

    def predict_persistence(self, feature_frame: pd.DataFrame) -> np.ndarray:
        """Persistence prediction (component 2) = prior_compliance."""
        return feature_frame["prior_compliance"].to_numpy(dtype=float)

    def predict(self, feature_frame: pd.DataFrame) -> np.ndarray:
        """Final ensemble prediction. Clips to [0, 100]."""
        w = self.config.ensemble_weight_ca
        tree = self.predict_tree(feature_frame)
        pers = self.predict_persistence(feature_frame)
        return np.clip(w * tree + (1 - w) * pers, 0.0, 100.0)

    def save_config(self, path: Path | None = None) -> Path:
        """Persist the frozen config + validation metrics as JSON."""
        if path is None:
            path = REPORTS_DIR / "candidate_a_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": self.config.to_dict(),
            "feature_columns": self.feature_columns,
            "val_metrics": self.val_metrics,
            "fit_row_count": self.fit_row_count,
        }
        path.write_text(json.dumps(payload, indent=2))
        return path


# ---------------------------------------------------------------------------
# Training + selection
# ---------------------------------------------------------------------------


def _restrict_to_target_window(ff: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    """Keep rows whose forecast TARGET month is in [lo, hi]."""
    mask = (ff["target_month"] >= lo) & (ff["target_month"] <= hi)
    return ff.loc[mask].copy()


def train_candidate_a(
    split: Split | None = None,
    param_grid: list[dict] | None = None,
    feature_builder: features_mod.FeatureBuilder | None = None,
    ensemble_weight_grid: tuple[float, ...] = (0.3, 0.4, 0.5),
) -> tuple[CandidateA, pd.DataFrame]:
    """Train Candidate A: search the param grid AND ensemble weight on
    validation, return the best model + a DataFrame of all candidates'
    validation metrics.

    The ensemble blends the boosted tree with persistence:
        pred = w * tree + (1-w) * prior_compliance
    Both w and the tree hyperparameters are selected on validation only.

    Returns
    -------
    (best_candidate, search_results_df)
    """
    if split is None:
        split = build_temporal_split()
    if param_grid is None:
        param_grid = DEFAULT_PARAM_GRID
    if feature_builder is None:
        feature_builder = features_mod.FeatureBuilder()

    # Build features on the FULL panel (lags need full history), then restrict
    # to train and validation target windows.
    ff = feature_builder.build()
    f_cols = feature_builder.feature_columns()

    train_lo, train_hi = split.windows["train"]
    val_lo, val_hi = split.windows["validation"]
    train_ff = _restrict_to_target_window(ff, train_lo, train_hi)
    val_ff = _restrict_to_target_window(ff, val_lo, val_hi)

    X_train = train_ff[f_cols].to_numpy()
    y_train = train_ff["target_compliance"].to_numpy()
    X_val = val_ff[f_cols].to_numpy()

    # Persistence predictions on validation (constant across tree candidates)
    pers_val = val_ff["prior_compliance"].to_numpy(dtype=float)

    # Search over (tree params, ensemble weight). Selection happens AFTER the
    # full sweep via select_config_deterministic (tolerance + simpler tie-break),
    # not a running argmin, so it is stable when the top candidates fall within
    # the tolerance of each other (they do: < 0.01 pp validation MAE apart).
    search_rows = []

    for params in param_grid:
        model = HistGradientBoostingRegressor(
            random_state=RANDOM_SEED,
            early_stopping=False,
            **params,
        )
        model.fit(X_train, y_train)
        tree_val = np.clip(model.predict(X_val), 0.0, 100.0)

        for w in ensemble_weight_grid:
            blend = np.clip(w * tree_val + (1 - w) * pers_val, 0.0, 100.0)
            val_pred_df = val_ff.copy()
            val_pred_df["prediction"] = blend
            m = evaluate(val_pred_df)

            row = {
                "params": params,
                "ensemble_weight_ca": w,
                "val_mae": m.mae,
                "val_rmse": m.rmse,
                "val_dir_acc": m.directional_accuracy,
                "val_bias": m.mean_error,
                "val_p90_abs_error": m.p90_abs_error,
            }
            search_rows.append(row)

    search_df = pd.DataFrame(search_rows).sort_values("val_mae").reset_index(drop=True)
    best_params, best_weight = select_config_deterministic(search_df)
    # Refit the selected tree (deterministic given the fixed seed) so the
    # returned model matches the selected hyperparameters exactly.
    best_model = HistGradientBoostingRegressor(
        random_state=RANDOM_SEED, early_stopping=False, **best_params
    )
    best_model.fit(X_train, y_train)

    # Build the frozen CandidateA with the best params + weight
    config = CandidateAConfig(
        max_depth=best_params["max_depth"],
        learning_rate=best_params["learning_rate"],
        max_iter=best_params["max_iter"],
        l2_regularization=best_params["l2_regularization"],
        min_samples_leaf=best_params["min_samples_leaf"],
        ensemble_weight_ca=best_weight,
    )
    # Final validation metrics using the selected ensemble
    best_val_pred_df = val_ff.copy()
    tree_val = np.clip(best_model.predict(X_val), 0.0, 100.0)
    best_val_pred_df["prediction"] = np.clip(
        best_weight * tree_val + (1 - best_weight) * pers_val, 0.0, 100.0
    )
    best_val_metrics = evaluate(best_val_pred_df).as_dict()

    candidate = CandidateA(
        config=config,
        model=best_model,
        feature_columns=f_cols,
        val_metrics=best_val_metrics,
        fit_row_count=len(X_train),
    )

    return candidate, search_df


# ---------------------------------------------------------------------------
# Deterministic selection + frozen-config loading (reproducibility)
# ---------------------------------------------------------------------------
# The top hyperparameter candidates are separated by < 0.01 pp validation MAE,
# so a plain argmin is not stable across scikit-learn versions (HistGradientBoosting
# binning changed at 1.6, reordering near-ties). Two mechanisms make scoring
# reproducible:
#   1. select_config_deterministic() turns the search into a stable choice:
#      within a tolerance of the best, prefer the SIMPLER model.
#   2. The chosen config is frozen to reports/candidate_a_config.json and loaded
#      by build_frozen_candidate(); holdout scoring and the dashboard fit that
#      frozen config instead of re-running the search.

FROZEN_CONFIG_PATH = REPORTS_DIR / "candidate_a_config.json"

# A candidate "ties" with the best if its validation MAE is within this many
# percentage points of the lowest. Among ties we prefer the simpler model.
SELECTION_TOLERANCE_PP = 0.05


def select_config_deterministic(
    search_df: pd.DataFrame, tolerance_pp: float = SELECTION_TOLERANCE_PP
) -> tuple[dict, float]:
    """Pick (tree params, ensemble weight) deterministically from a search.

    Among all candidates whose validation MAE is within ``tolerance_pp`` of the
    best, choose the SIMPLEST model by an explicit, documented ordering:
    shallower tree, fewer boosting iterations, larger min_samples_leaf, stronger
    L2, lower learning rate, then a lower tree weight (more persistence). Ties on
    all of those fall back to validation MAE. This is a total order, so the
    result does not depend on row order or floating-point argmin jitter.
    """
    best = float(search_df["val_mae"].min())
    near = [r for r in search_df.to_dict("records") if r["val_mae"] <= best + tolerance_pp]

    def simplicity_key(r: dict) -> tuple:
        p = r["params"]
        return (
            p["max_depth"],
            p["max_iter"],
            -p["min_samples_leaf"],
            -p["l2_regularization"],
            p["learning_rate"],
            r["ensemble_weight_ca"],
            r["val_mae"],
        )

    chosen = min(near, key=simplicity_key)
    return dict(chosen["params"]), float(chosen["ensemble_weight_ca"])


def load_frozen_config(path: Path | None = None) -> CandidateAConfig:
    """Load the frozen Candidate A configuration from JSON (the single source of
    truth). Holdout scoring and the dashboard use this, never a fresh search."""
    if path is None:
        path = FROZEN_CONFIG_PATH
    payload = json.loads(Path(path).read_text())
    c = payload["config"]
    return CandidateAConfig(
        max_depth=c["max_depth"],
        learning_rate=c["learning_rate"],
        max_iter=c["max_iter"],
        l2_regularization=c["l2_regularization"],
        min_samples_leaf=c["min_samples_leaf"],
        ensemble_weight_ca=c["ensemble_weight_ca"],
        feature_builder_params={k: tuple(v) for k, v in c["feature_builder_params"].items()},
        random_seed=c["random_seed"],
        train_window=tuple(c["train_window"]),
        validation_window=tuple(c["validation_window"]),
    )


def fit_candidate_from_config(
    config: CandidateAConfig,
    split: Split | None = None,
    feature_builder: features_mod.FeatureBuilder | None = None,
) -> CandidateA:
    """Fit Candidate A from an explicit frozen config, with NO hyperparameter
    search. Deterministic given the pinned scikit-learn, the seed, and the data.
    This is the reproducible scoring path used by the holdout pipeline and app."""
    if split is None:
        split = build_temporal_split()
    if feature_builder is None:
        feature_builder = features_mod.FeatureBuilder(
            compliance_lags=tuple(config.feature_builder_params["compliance_lags"]),
            compliance_roll_windows=tuple(config.feature_builder_params["compliance_roll_windows"]),
            attendance_lags=tuple(config.feature_builder_params["attendance_lags"]),
        )
    ff = feature_builder.build()
    f_cols = feature_builder.feature_columns()

    train_lo, train_hi = split.windows["train"]
    val_lo, val_hi = split.windows["validation"]
    train_ff = _restrict_to_target_window(ff, train_lo, train_hi)
    val_ff = _restrict_to_target_window(ff, val_lo, val_hi)

    model = HistGradientBoostingRegressor(
        random_state=config.random_seed,
        early_stopping=False,
        max_depth=config.max_depth,
        learning_rate=config.learning_rate,
        max_iter=config.max_iter,
        l2_regularization=config.l2_regularization,
        min_samples_leaf=config.min_samples_leaf,
    )
    model.fit(train_ff[f_cols].to_numpy(), train_ff["target_compliance"].to_numpy())

    candidate = CandidateA(
        config=config,
        model=model,
        feature_columns=f_cols,
        val_metrics={},
        fit_row_count=len(train_ff),
    )
    val_pred = val_ff.copy()
    val_pred["prediction"] = candidate.predict(val_ff)
    candidate.val_metrics = evaluate(val_pred).as_dict()
    return candidate


def build_frozen_candidate(path: Path | None = None, split: Split | None = None) -> CandidateA:
    """Load the frozen config and fit it. The canonical way to obtain the scored
    model for the holdout pipeline and the dashboard (no search at runtime)."""
    return fit_candidate_from_config(load_frozen_config(path), split=split)
