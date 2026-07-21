"""Tests for Phase 5 Candidate A model.

These tests pin the model's frozen behavior so the configuration cannot
silently drift before the Phase 6 holdout scoring. They also verify the
no-holdout-leakage discipline (L5): training uses train + validation only.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ed_ops import features as features_mod
from ed_ops import model as model_mod
from ed_ops.splits import DEFAULT_SPLIT_WINDOWS, build_temporal_split


@pytest.fixture(scope="module")
def candidate():
    """Train Candidate A once for all tests in this module."""
    c, _ = model_mod.train_candidate_a()
    return c


# ---------------------------------------------------------------------------
# Frozen configuration (D018/D019 decisions)
# ---------------------------------------------------------------------------


class TestFrozenConfig:
    """Pin the configuration that was selected on validation. Any change here
    requires a new decision-log entry before re-freezing."""

    def test_model_family_is_ensemble(self, candidate):
        assert "ensemble" in candidate.config.model_family.lower()

    def test_selected_hyperparams_match_D018(self, candidate):
        """D018: joint search winner = max_depth=5, learning_rate=0.03,
        max_iter=500, l2_regularization=1.0, min_samples_leaf=40.

        Selected jointly with the ensemble weight on validation. This deeper/
        slower tree blends better with persistence than the shallower tree
        that won the tree-only search. Top-5 candidates span MAE 2.509-2.526
        (robust, not knife-edge)."""
        c = candidate.config
        assert c.max_depth == 5
        assert c.learning_rate == 0.03
        assert c.max_iter == 500
        assert c.l2_regularization == 1.0
        assert c.min_samples_leaf == 40

    def test_config_defaults_match_frozen_phase5(self):
        """REGRESSION GUARD (W1 fix): CandidateAConfig() defaults must equal the
        frozen Phase 5 config, so anyone constructing the config directly gets
        the same model train_candidate_a() produces. Previously the defaults
        were stale (lr=0.05, iter=400, l2=0.5, leaf=30) -- a latent footgun."""
        from ed_ops.model import CandidateAConfig

        c = CandidateAConfig()
        assert c.max_depth == 5
        assert c.learning_rate == 0.03
        assert c.max_iter == 500
        assert c.l2_regularization == 1.0
        assert c.min_samples_leaf == 40
        assert c.ensemble_weight_ca == 0.4
        assert c.l2_regularization == 1.0
        assert c.min_samples_leaf == 40

    def test_selected_ensemble_weight_match_D019(self, candidate):
        """D019: ensemble weight w_ca=0.4 (Candidate A) + 0.6 persistence."""
        assert candidate.config.ensemble_weight_ca == 0.4

    def test_seed_recorded(self, candidate):
        from ed_ops.config import RANDOM_SEED

        assert candidate.config.random_seed == RANDOM_SEED

    def test_train_window_matches_D015(self, candidate):
        assert candidate.config.train_window == DEFAULT_SPLIT_WINDOWS["train"]

    def test_feature_count_is_21(self, candidate):
        assert len(candidate.feature_columns) == 21


# ---------------------------------------------------------------------------
# No holdout leakage (L5)
# ---------------------------------------------------------------------------


class TestNoHoldoutLeakage:
    """Training must use only train + validation. The holdout partition
    (2025-06 onwards) must not influence the model in any way."""

    def test_fit_row_count_matches_train_only(self, candidate):
        """The model is fit on TRAIN rows only (validation is held out for
        selection, never fit). Train window = 2018-01..2023-12."""
        # Build the train feature frame to count expected rows
        split = build_temporal_split()
        ff = features_mod.FeatureBuilder().build()
        lo, hi = split.windows["train"]
        train_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)]
        assert candidate.fit_row_count == len(train_ff)

    def test_holdout_target_months_not_in_fit(self, candidate):
        """The holdout starts at 2025-06. The fit row count must be smaller
        than train+val+holdout combined (a sanity check that holdout data
        did not get swept into fitting)."""
        # fit count = train only (~2160). Train+val+holdout would be much larger.
        assert candidate.fit_row_count < 3000

    def test_predictions_are_bounded(self, candidate):
        """All predictions must be in [0, 100] (target domain)."""
        split = build_temporal_split()
        ff = features_mod.FeatureBuilder().build()
        lo, hi = split.windows["validation"]
        val_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)]
        preds = candidate.predict(val_ff)
        assert (preds >= 0).all() and (preds <= 100).all()


# ---------------------------------------------------------------------------
# Validation performance (the bar)
# ---------------------------------------------------------------------------


class TestValidationPerformance:
    """Candidate A (ensemble) must beat the persistence baseline on validation
    MAE. This is the gate defined in D016."""

    def test_beats_persistence_mae(self, candidate):
        """D016 bar: persistence MAE 2.848 on validation. Candidate A ensemble
        must be lower. (D020: actual = 2.510.)"""
        from ed_ops.evaluation import evaluate

        split = build_temporal_split()
        ff = features_mod.FeatureBuilder().build()
        lo, hi = split.windows["validation"]
        val_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)].copy()
        val_ff["prediction"] = candidate.predict(val_ff)
        m = evaluate(val_ff)
        assert m.mae < 2.848, f"Candidate A MAE {m.mae:.3f} did not beat persistence bar 2.848"

    def test_val_metrics_recorded_in_candidate(self, candidate):
        m = candidate.val_metrics
        assert m["mae"] < 2.848
        # Sanity: n=510 (validation partition size)
        assert m["n"] == 510


# ---------------------------------------------------------------------------
# Ensemble mechanics
# ---------------------------------------------------------------------------


class TestEnsembleMechanics:
    def test_predict_equals_weighted_blend(self, candidate):
        """Final prediction must equal w*tree + (1-w)*persistence, clipped."""
        split = build_temporal_split()
        ff = features_mod.FeatureBuilder().build()
        lo, hi = split.windows["validation"]
        val_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)]
        tree = candidate.predict_tree(val_ff)
        pers = candidate.predict_persistence(val_ff)
        w = candidate.config.ensemble_weight_ca
        expected = np.clip(w * tree + (1 - w) * pers, 0.0, 100.0)
        actual = candidate.predict(val_ff)
        np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_persistence_component_uses_prior_compliance(self, candidate):
        """The persistence component must equal prior_compliance exactly
        (no drift, no learned offset)."""
        split = build_temporal_split()
        ff = features_mod.FeatureBuilder().build()
        lo, hi = split.windows["validation"]
        val_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)]
        pers = candidate.predict_persistence(val_ff)
        np.testing.assert_allclose(pers, val_ff["prior_compliance"].to_numpy(float))


# ---------------------------------------------------------------------------
# Config persistence (Phase 6 freeze prerequisite)
# ---------------------------------------------------------------------------


class TestConfigPersistence:
    def test_save_config_writes_valid_json(self, candidate, tmp_path):
        path = candidate.save_config(tmp_path / "test_config.json")
        payload = json.loads(path.read_text())
        assert "config" in payload
        assert payload["config"]["model_family"].startswith("HistGradientBoostingRegressor")
        assert payload["config"]["ensemble_weight_ca"] == 0.4
        assert "val_metrics" in payload
        assert len(payload["feature_columns"]) == 21
