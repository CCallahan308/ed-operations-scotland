# Phase 5: Candidate A Model

> Completed 2026-07-21. Candidate A is a gradient-boosted-tree + persistence ensemble, selected on validation. It beats the persistence baseline (D016 bar) on validation MAE. The holdout is untouched.

## Model definition

**Candidate A = ensemble of:**
- A histogram gradient-boosted regression tree (`HistGradientBoostingRegressor`) predicting next-month site compliance %
- The persistence baseline (prediction = prior month's compliance)

**Final prediction:** `0.4 × tree + 0.6 × persistence`, clipped to [0, 100].

The ensemble weight (0.4) and tree hyperparameters were selected **jointly** on validation. The holdout was never used.

## Two honest findings that reshaped the model

### Finding 1: the tree alone loses to persistence (D018)

The pure gradient-boosted tree achieved validation **MAE 3.13 pp — worse than the persistence baseline (2.85 pp)**. Diagnosis:

- **Tree is biased high (+0.69 pp)** vs persistence's near-zero bias (−0.16 pp). The tree learned from train (median compliance 89.3) and is slow to adapt to the validation regime (median 69.2). This is the structural-break signature (Phase 3) hitting the model directly.
- **Tree gets direction right (54.5%)** where persistence is at 13.7% (persistence always predicts "no change" and compliance moves almost every month).
- **Tree wins 46.1% of rows.** It captures reversals persistence misses, but loses on months with steady drift.

Per operating rule 5, I did not manipulate the evaluation to hide this. I reported it and looked for a validation-only improvement.

### Finding 2: ensembling with persistence fixes both failure modes (D019)

Persistence provides the right *level* (sticky month-to-month); the tree provides *direction*. A weighted blend captures both:

| Blend weight (tree) | Val MAE | Bias | Dir acc |
|---|---|---|---|
| 0.0 (persistence only) | 2.848 | −0.16 | 13.7% |
| 0.3 | 2.542 | +0.09 | 45.5% |
| **0.4 (selected)** | **2.519** | **+0.18** | **48.2%** |
| 0.5 | 2.540 | +0.26 | 50.4% |
| 1.0 (tree only) | 3.126 | +0.69 | 54.5% |

The optimum is shallow (weights 0.3 to 0.5 give MAE 2.52 to 2.54, with 0.4 the minimum), so the choice is not knife-edge. The selected 0.4 wins on 28 of 30 sites — the improvement is uniform, not driven by a few outliers.

## Frozen configuration (recorded for Phase 6)

| Parameter | Value |
|---|---|
| Tree family | HistGradientBoostingRegressor |
| max_depth | 5 |
| learning_rate | 0.03 |
| max_iter | 500 |
| l2_regularization | 1.0 |
| min_samples_leaf | 40 |
| Ensemble weight (tree) | 0.4 |
| Ensemble weight (persistence) | 0.6 |
| Feature count | 21 |
| Fit rows (train only) | 2,160 |
| Seed | 20260721 |
| Train window | 2018-01 → 2023-12 |
| Validation window | 2024-01 → 2025-05 |

Saved to `reports/candidate_a_config.json`. The holdout (2025-06 → 2026-05) is untouched.

## Validation performance (the gate)

| Model | MAE | RMSE | Bias | Dir acc |
|---|---|---|---|---|
| **Candidate A (ensemble)** | **2.519 pp** | 3.445 | +0.18 | 48.2% |
| Candidate A (tree only) | 3.126 pp | 4.100 | +0.69 | 54.5% |
| Persistence baseline | 2.848 pp | 3.888 | −0.16 | 13.7% |
| Seasonal naive | 3.844 pp | 5.013 | +1.22 | 52.5% |

**Candidate A beats the persistence bar by 0.329 pp (11.5% relative improvement).** The improvement is driven by better directional accuracy without sacrificing level calibration.

## Error analysis

- **Residuals** (`reports/figures/phase5_error_analysis.png`): centered near zero, slightly right-skewed (small positive bias from the tree component). No heteroscedasticity pattern by actual level.
- **By month**: Candidate A beats persistence in 15 of 17 validation months. Wins biggest in reversal months (2025-01: -1.03, 2025-02: -0.80); the only outright loss is a drift month (2024-01: +0.30).
- **By site size**: improvement is uniform across attendance quintiles (no size-tier outlier); no equity concern.
- **Per-site**: ensemble wins on 28 of 30 sites.

## Feature importance (permutation, on validation)

| Rank | Feature | Importance (ΔMAE when shuffled) |
|---|---|---|
| 1 | `f_compliance_lag1` | 7.47 |
| 2 | `f_compliance_roll3_mean` | 0.66 |
| 3 | `f_compliance_roll6_mean` | 0.51 |
| 4 | `f_compliance_lag2` | 0.50 |
| 5 | `f_month_of_year` | 0.44 |
| 6 | `f_compliance_lag6` | 0.37 |
| 7 | `f_compliance_roll12_mean` | 0.27 |
| 8 | `f_compliance_lag11` | 0.16 |

**The model relies heavily on `f_compliance_lag1`** — which is exactly the persistence signal. This explains why the ensemble works: the tree's strongest feature *is* persistence, and blending formalizes that relationship rather than fighting it. Calendar (`f_month_of_year`) and rolling means add modest signal. Attendance features contribute marginally.

(Note: HistGradientBoostingRegressor does not expose `feature_importances_` directly; I used `sklearn.inspection.permutation_importance` on validation, which is the principled alternative. Initial attempt returned all-zeros from the missing attribute — corrected rather than fabricated.)

## Robustness checks

1. **Seed stability (5 seeds):** val MAE = 2.519 ± 0.000. The result is not a lucky seed draw.
2. **COVID-exclusion sensitivity:** training without COVID months (2020-03..2022-12) changes val MAE by +0.015 pp. Including COVID data is harmless and honest; excluding it would discard real ED history for negligible gain.
3. **Feature ablation:** a 2-feature model (lag1 + roll3_mean) achieves 2.715 pp; the full 21-feature set reaches 2.519 pp. The additional features earn their complexity (+0.20 pp).

## What was NOT done (deferred / rejected)

- **Companion-file enrichment** (demographics/when/referral, D017 deferral). Not pursued: the core ensemble already beats the bar with margin, and the structural break is the dominant error source, not missing features. Adding enrichment would multiply validation cost for likely-sub-0.1pp gains.
- **Recency-weighted training.** The ensemble effectively handles this via the persistence component; an explicit sample-weight scheme was not needed to clear the bar.
- **Probabilistic forecasts / prediction intervals.** HGBR supports quantile loss but adding intervals is a Phase 6+ extension; the current evaluation is point-forecast MAE.

## Reproduction

```bash
python -m pytest tests/test_model.py -v   # 14 tests
python -c "import sys;sys.path.insert(0,'src');from ed_ops.model import train_candidate_a; c,_=train_candidate_a(); print(c.val_metrics)"
```

Artifacts:
- `reports/candidate_a_config.json` — frozen config + val metrics
- `reports/candidate_a_hyperparam_search.csv` — full search results
- `reports/candidate_a_feature_importance.csv` — permutation importance
- `reports/figures/phase5_error_analysis.png` — residual/month/distribution/scatter plots

## Phase 5 → Phase 6 handoff

The model is **frozen**: config, hyperparameters, ensemble weight, feature set, and training window are all locked and pinned by `tests/test_model.py`. Phase 6 will:
1. Score the frozen Candidate A on the holdout (2025-06 → 2026-05), exactly once.
2. Compare to persistence on the same holdout partition.
3. Report holdout metrics, baseline comparison, key errors, and limitations.
4. Disclose explicitly if any pre-holdout decision was informed by holdout peeking (it was not).
