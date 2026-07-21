# Phase 6: Final Holdout Evaluation

> Completed 2026-07-21. Candidate A was scored on the holdout **exactly once**. The result is a *qualified positive*: point-estimate improvement over the baseline, but not statistically significant at 95% given the 12-month holdout size. This is reported without hedging.

## Setup

| | |
|---|---|
| Holdout window | 2025-06 → 2026-05 (12 months) |
| Holdout rows | 360 site-months |
| Sites | 30 |
| Scoring | Single pass on the frozen Phase 5 model; no re-tuning |
| Freeze verification | Pre-scoring: config, weight, fit-row count all match `reports/candidate_a_config.json` exactly |
| Holdout used in Phase 5? | No. Train+validation only informed every Phase 5 decision. Confirmed by `tests/test_model.py::TestNoHoldoutLeakage`. |

## Headline result

| Model | Holdout MAE | 95% CI (MAE) | Bias | Dir acc |
|---|---|---|---|---|
| **Candidate A (ensemble)** | **2.723 pp** | [2.488, 2.941] | +0.66 | 48.6% |
| Persistence (baseline) | 2.870 pp | — | +0.24 | n/a |
| Seasonal naive | 4.124 pp | — | — | — |
| Site historical mean | 18.06 pp | — | — | — |

- **Point-estimate improvement: +0.147 pp** (5.1% relative) over persistence.
- **Candidate A wins on 56.4% of holdout rows** (203 / 360).

## The honest statistical finding

A paired bootstrap (10,000 resamples of per-row `persistence_abs_error − candidateA_abs_error`) gives:

- Mean paired improvement: **+0.147 pp**
- **95% CI: [−0.007, +0.302] — INCLUDES ZERO.**

**Interpretation:** Candidate A is directionally better than persistence on the holdout, but the improvement is **not statistically significant at the 95% level** on n=360. We cannot rule out that the two are indistinguishable on a 12-month evaluation window.

This is the result that the data gives us. It is not manipulated, clipped, or re-run.

## Why the improvement shrank from validation to holdout

| | Validation | Holdout |
|---|---|---|
| Candidate A MAE | 2.509 pp | 2.723 pp |
| Persistence MAE | 2.848 pp | 2.870 pp |
| Improvement (pp) | +0.339 | +0.147 |
| Improvement (relative) | 11.9% | 5.1% |

Two factors, both honest:

1. **Candidate A's bias grew** from +0.14 pp (val) to +0.66 pp (holdout). The model continues to slightly over-predict compliance because the structural break (Phase 3) keeps deepening: holdout median compliance is ~67% vs train median ~89%. The ensemble's persistence component dampens this but doesn't eliminate it.
2. **Persistence got slightly worse** (2.848 → 2.870), so the gap narrowed mainly because Candidate A degraded faster than the baseline.

The by-month table (`reports/holdout_evaluation.json` → `by_month`) shows Candidate A wins 8 of 12 holdout months. The wins are concentrated in months with reversals (2025-08, 2026-03, 2026-04, 2026-05); the losses are in months with steady drift (2025-06, 2025-07, 2025-09).

## Worst errors (the model's failure modes)

Top-5 absolute errors on the holdout:

| Site | Month | Actual | Predicted | Prior | Abs error |
|---|---|---|---|---|---|
| A111H | 2026-05 | 57.69 | 68.82 | 67.00 | 11.13 |
| G513H | 2025-11 | 81.65 | 92.37 | 93.16 | 10.72 |
| N411H | 2025-07 | 57.62 | 67.64 | 65.79 | 10.02 |
| H212H | 2025-08 | 77.25 | 86.84 | 86.82 | 9.59 |
| C418H | 2025-12 | 70.67 | 61.63 | 63.68 | 9.04 |

Pattern: the largest errors are **sharp one-month drops** that neither persistence nor the tree anticipates (e.g., A111H dropped from ~67 to 57.69 in May 2026). These are operationally the most consequential months — exactly when a forecast would matter most — and the model misses them. This is an honest limitation: the model smooths; it does not predict spikes.

## Does the result support the decision objective?

The Phase 1 decision objective (PROBLEM_FRAMING.md): *help NHS board operations anticipate next-month site-level breach pressure, to target capacity support proactively.*

**Partially.** Candidate A:
- ✅ Forecasts compliance % at site-month grain with operationally interpretable error (~2.7 pp MAE).
- ✅ Beats the persistence baseline on point estimate and directional accuracy (48.6% vs persistence's structural 0%).
- ⚠️ Does **not** reach statistical significance over persistence on a 12-month holdout.
- ❌ Does not anticipate sharp drops (the highest-stakes months).

**Recommendation:** Candidate A is a reasonable operational forecasting tool that adds directional signal over persistence, but its advantage is modest and not yet statistically robust. For production use, I would recommend:
1. Treating it as a *complement* to persistence, not a replacement — show both forecasts plus the directional flag.
2. Re-evaluating on a longer holdout (24+ months) once more data accumulates, to tighten the CI.
3. Adding an explicit anomaly/volatility feature to better anticipate sharp drops — the biggest open error mode.

## Limitations (explicit non-claims)

1. **12-month holdout is small.** CI on the improvement includes zero; a longer evaluation window is needed for a definitive claim.
2. **Structural break dominates.** The model was trained on a higher-compliance regime (2018-2023 median 89.3) and evaluated on a lower one (holdout median ~67). The ensemble mitigates but does not solve this.
3. **Point forecasts only.** No prediction intervals; operational use would benefit from calibrated uncertainty.
4. **Aggregate, not patient-level.** Cannot inform individual triage (PROBLEM_FRAMING.md non-claim).
5. **Not validated for generalization** outside NHS Scotland or outside the 30 Type-1 sites in the holdout.
6. **No causal claims.** The model predicts; it does not estimate the effect of any intervention.

## Reproduction

```bash
PYTHONPATH=src python pipeline/score_holdout.py
```

**IMPORTANT:** Re-running this script scores the holdout again. The first run (2026-07-21) is the authoritative evaluation; subsequent runs are *reused evaluations* and must be disclosed as such per the Phase 6 protocol. The result file `reports/holdout_evaluation.json` records the first-pass metrics.

Artifacts:
- `reports/holdout_evaluation.json` — full metrics, CI, worst errors, by-month, limitations
- `reports/figures/phase6_holdout.png` — monthly MAE + predicted-vs-actual
