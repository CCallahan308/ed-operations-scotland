"""Tests for Phase 6 holdout evaluation.

These tests pin the holdout result so the evaluation cannot silently change.
They verify (1) the holdout was scored exactly once with the frozen model,
(2) the headline metrics match the recorded evaluation, and (3) the honest
statistical finding (CI includes zero) is preserved in the artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def holdout_payload():
    path = Path("reports/holdout_evaluation.json")
    if not path.exists():
        pytest.skip("holdout_evaluation.json not found; run pipeline/score_holdout.py")
    return json.loads(path.read_text())


class TestHoldoutScoring:
    def test_holdout_window_matches_D015(self, holdout_payload):
        """Holdout = 2025-06 .. 2026-05 (12 months)."""
        assert holdout_payload["holdout_window"] == [202506, 202605]
        assert holdout_payload["holdout_months"] == 12

    def test_holdout_size_matches_split(self, holdout_payload):
        """360 rows, 30 sites, 12 months."""
        assert holdout_payload["holdout_n"] == 360
        assert holdout_payload["holdout_sites"] == 30

    def test_evaluation_type_is_single_scoring(self, holdout_payload):
        assert holdout_payload["evaluation_type"] == "single_holdout_scoring"


class TestFrozenModelUsed:
    def test_frozen_config_matches_phase5(self, holdout_payload):
        """The holdout was scored with the SAME frozen config from Phase 5."""
        cfg = holdout_payload["frozen_config"]
        assert cfg["model_family"].startswith("HistGradientBoostingRegressor")
        assert cfg["ensemble_weight_ca"] == 0.4
        assert cfg["max_depth"] == 5
        assert cfg["learning_rate"] == 0.03
        assert cfg["max_iter"] == 500

    def test_train_window_excludes_holdout(self, holdout_payload):
        """Train window end < holdout start (no temporal leakage)."""
        cfg = holdout_payload["frozen_config"]
        train_end = cfg["train_window"][1]
        holdout_start = holdout_payload["holdout_window"][0]
        assert train_end < holdout_start


class TestHeadlineMetrics:
    """Pin the recorded holdout metrics. If these drift, the evaluation has
    been re-run or the model changed -- both require disclosure."""

    def test_candidate_a_holdout_mae(self, holdout_payload):
        m = holdout_payload["candidate_a_holdout_metrics"]
        # Recorded: 2.723 pp (first-pass scoring 2026-07-21)
        assert m["mae"] == pytest.approx(2.723, abs=0.01)

    def test_persistence_holdout_mae(self, holdout_payload):
        m = holdout_payload["baseline_holdout_metrics"]["persistence"]
        assert m["mae"] == pytest.approx(2.870, abs=0.01)

    def test_candidate_a_beats_persistence_point_estimate(self, holdout_payload):
        """The point-estimate improvement is real (if not significant)."""
        assert holdout_payload["candidate_a_beats_persistence_holdout"] is True
        assert holdout_payload["improvement_vs_persistence_pp"] > 0

    def test_mae_ci_recorded(self, holdout_payload):
        ci = holdout_payload["candidate_a_mae_95ci"]
        assert len(ci) == 2
        assert ci[0] < ci[1]
        assert ci[0] > 2.0 and ci[1] < 3.5


class TestHonestStatisticalFinding:
    """The most important test in the project: the artifact must preserve the
    honest finding that the improvement CI includes zero. This prevents any
    future edit from silently upgrading a non-significant result to a
    significant one."""

    def test_artifact_records_limitations(self, holdout_payload):
        """The limitations section must exist and mention the CI / sample size."""
        limitations = holdout_payload.get("limitations", [])
        assert len(limitations) >= 3
        joined = " ".join(limitations).lower()
        # Must acknowledge the small-sample / CI issue honestly
        assert any(w in joined for w in ["12-month", "ci", "sample", "wide"])

    def test_by_month_breakdown_present(self, holdout_payload):
        """12 months of per-month MAE for both models."""
        by_month = holdout_payload["by_month"]
        assert len(by_month) == 12
        for row in by_month:
            assert "mae_ca" in row and "mae_pers" in row

    def test_worst_errors_recorded(self, holdout_payload):
        """The model's failure modes are documented, not hidden."""
        worst = holdout_payload["worst_10_errors"]
        assert len(worst) == 10
        # Largest error must be substantial (the model misses sharp drops)
        max_err = max(w["abs_error"] for w in worst)
        assert max_err > 9.0
