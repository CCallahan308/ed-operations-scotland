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

    # Search over (tree params, ensemble weight)
    search_rows = []
    best_mae = float("inf")
    best_params = None
    best_weight = None
    best_model = None

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

            if m.mae < best_mae:
                best_mae = m.mae
                best_params = params
                best_weight = w
                best_model = model

    search_df = pd.DataFrame(search_rows).sort_values("val_mae").reset_index(drop=True)

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
