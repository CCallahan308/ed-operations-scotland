"""Phase 6: Final holdout evaluation (scored exactly once).

This script is run ONCE on the frozen Candidate A. It scores the holdout
partition (2025-06 .. 2026-05) and writes the result. Re-running it does not
constitute re-evaluation; the holdout has already been 'seen'. Any subsequent
holdout scoring is disclosed as a reused evaluation set per the protocol.

Discipline enforced:
  - The model is the frozen Phase 5 config (verified before scoring).
  - No hyperparameter, feature, or weight changes after this point.
  - Holdout is the most recent 12 months; this is the decision-relevant period.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn

from ed_ops import baselines
from ed_ops import config as ed_config
from ed_ops import features as features_mod
from ed_ops.evaluation import compare_models, evaluate
from ed_ops.model import build_frozen_candidate
from ed_ops.splits import build_temporal_split


def score_holdout_once(output_path: Path | None = None) -> dict:
    """Score Candidate A and all baselines on the holdout partition.

    Returns a payload with holdout metrics for every model + baseline
    comparison + key errors + limitations.
    """
    split = build_temporal_split()
    holdout_window = split.windows["holdout"]

    # Load the FROZEN config and fit it -- NO hyperparameter search at scoring
    # time. This is what makes the holdout reproducible: scoring cannot silently
    # re-select a different candidate across scikit-learn versions.
    candidate = build_frozen_candidate()

    # Build features on full panel, restrict to holdout TARGET months
    ff = features_mod.FeatureBuilder().build()
    lo, hi = holdout_window
    holdout_ff = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)].copy()

    # === Score Candidate A ===
    holdout_ff["prediction"] = candidate.predict(holdout_ff)
    m_ca = evaluate(holdout_ff)

    # === Score baselines on the same holdout ===
    baseline_preds = baselines.run_all_baselines_on_partition(holdout_window)
    baseline_metrics = {name: evaluate(preds) for name, preds in baseline_preds.items()}

    # Comparison table
    all_results = {"candidate_a": m_ca, **baseline_metrics}
    comparison = compare_models(all_results)

    # Key errors: the largest absolute errors
    holdout_ff["abs_error"] = (holdout_ff["prediction"] - holdout_ff["target_compliance"]).abs()
    worst = holdout_ff.nlargest(10, "abs_error")[
        [
            "TreatmentLocation",
            "target_month",
            "target_compliance",
            "prediction",
            "prior_compliance",
            "abs_error",
        ]
    ].to_dict("records")

    # Per-month breakdown
    by_month = (
        holdout_ff.assign(
            err_ca=lambda d: (d["prediction"] - d["target_compliance"]).abs(),
            err_pers=lambda d: (d["prior_compliance"] - d["target_compliance"]).abs(),
        )
        .groupby("target_month")
        .agg(
            n=("target_compliance", "count"),
            mae_ca=("err_ca", "mean"),
            mae_pers=("err_pers", "mean"),
            mean_actual=("target_compliance", "mean"),
        )
        .round(3)
        .reset_index()
        .to_dict("records")
    )

    # Bootstrap CI for Candidate A MAE (non-parametric, 10,000 resamples).
    rng = np.random.default_rng(20260721)
    abs_errors = (holdout_ff["prediction"] - holdout_ff["target_compliance"]).abs().to_numpy()
    boot_maes = [
        rng.choice(abs_errors, size=len(abs_errors), replace=True).mean() for _ in range(10000)
    ]
    ci_low, ci_high = np.percentile(boot_maes, [2.5, 97.5])

    # Paired bootstrap on the improvement over persistence, on the SAME rows:
    #   diff_i = |persistence_i - actual_i| - |candidate_i - actual_i|
    # positive => Candidate A is closer on row i. This is the load-bearing
    # statistic: if its 95% CI includes zero the improvement is NOT significant.
    pers_abs = (holdout_ff["prior_compliance"] - holdout_ff["target_compliance"]).abs().to_numpy()
    paired_diff = pers_abs - abs_errors
    improvement_mean = float(paired_diff.mean())
    boot_diff = [
        rng.choice(paired_diff, size=len(paired_diff), replace=True).mean() for _ in range(10000)
    ]
    imp_lo, imp_hi = np.percentile(boot_diff, [2.5, 97.5])

    payload = {
        "evaluation_type": "single_holdout_scoring",
        "holdout_window": list(holdout_window),
        "holdout_n": len(holdout_ff),
        "holdout_sites": int(holdout_ff["TreatmentLocation"].nunique()),
        "holdout_months": int(holdout_ff["target_month"].nunique()),
        "frozen_config": candidate.config.to_dict(),
        "provenance": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "activity_sha256": ed_config.SOURCE_PROVENANCE["activity_monthly"][0],
            "random_seed": ed_config.RANDOM_SEED,
            "scored_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        },
        "candidate_a_holdout_metrics": m_ca.as_dict(),
        "candidate_a_mae_95ci": [round(float(ci_low), 4), round(float(ci_high), 4)],
        "improvement_paired_mean_pp": round(improvement_mean, 4),
        "improvement_95ci_pp": [round(float(imp_lo), 4), round(float(imp_hi), 4)],
        "improvement_ci_includes_zero": bool(imp_lo <= 0.0 <= imp_hi),
        "baseline_holdout_metrics": {k: v.as_dict() for k, v in baseline_metrics.items()},
        "comparison_sorted_by_mae": comparison.reset_index().to_dict("records"),
        "candidate_a_beats_persistence_holdout": bool(
            m_ca.mae < baseline_metrics["persistence"].mae
        ),
        "improvement_vs_persistence_pp": round(baseline_metrics["persistence"].mae - m_ca.mae, 4),
        "worst_10_errors": worst,
        "by_month": by_month,
        "limitations": [
            "Holdout is the most recent 12 months only (n=360); CI is wide.",
            "Structural break (Phase 3) means holdout regime (median ~67%) "
            "differs from train (median ~89%); the model extrapolates a trend.",
            "Point-forecast MAE only; no prediction intervals evaluated.",
            "Site-month aggregate, not patient-level; cannot inform individual "
            "patient triage (per PROBLEM_FRAMING.md non-claims).",
        ],
    }

    if output_path is None:
        output_path = Path("reports/holdout_evaluation.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    p = score_holdout_once()
    m = p["candidate_a_holdout_metrics"]
    print("=== HOLDOUT EVALUATION (scored once) ===")
    print(
        f"holdout: {p['holdout_window']}  n={p['holdout_n']}  "
        f"sites={p['holdout_sites']}  months={p['holdout_months']}"
    )
    print(
        f"\nCandidate A: MAE={m['mae']:.3f}pp  [95% CI {p['candidate_a_mae_95ci']}]  "
        f"RMSE={m['rmse']:.3f}  bias={m['mean_error']:+.3f}  "
        f"dir_acc={m['directional_accuracy']:.1%}"
    )
    bm = p["baseline_holdout_metrics"]
    print(
        f"Persistence: MAE={bm['persistence']['mae']:.3f}pp  "
        f"bias={bm['persistence']['mean_error']:+.3f}"
    )
    print(f"Seasonal:    MAE={bm['seasonal_naive']['mae']:.3f}pp")
    print(
        f"\nCandidate A beats persistence on holdout: {p['candidate_a_beats_persistence_holdout']}"
    )
    print(f"Improvement: {p['improvement_vs_persistence_pp']:+.3f}pp")
    print("\nsaved: reports/holdout_evaluation.json")
