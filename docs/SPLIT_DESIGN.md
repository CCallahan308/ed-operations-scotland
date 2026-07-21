# Phase 3: Split & Experimental Design

> Completed 2026-07-21. This document records the split strategy, the structural-break finding that reshaped it, leakage controls, and partition manifests.

## Split strategy: chronological (temporal) holdout

The split is **chronological**: all sites appear in every partition, partitions differ only by time window. This is the only defensible strategy because:

1. The outcome (`compliance_pct`) is a time series per site.
2. The decision is forward-looking (forecast next month).
3. There is a strong ongoing temporal trend (below).

**Rejected alternatives:**
- *Random/stratified split:* violates temporal independence; site-months are autocorrelated.
- *Site-disjoint (leave-sites-out):* would test geographic generalization, but the decision is about *time*, not *place*. Within-site temporal variance (72% of total) dominates between-site variance (22%); a site-disjoint split would answer the wrong question.
- *K-fold CV:* inappropriate for time series; leaks future into past.

## Structural-break finding (critical)

Profile of annual median compliance:

| Period | Median compliance | Mean |
|---|---|---|
| 2007-2017 (pre-split) | 96.7 | 95.5 |
| 2018-2019 | 92.6 | 91.0 |
| 2020-2022 (COVID era) | 88.8 | 83.5 |
| 2023-2024 | 71.2 | 72.3 |
| 2025-2026 | 67.7 | 70.0 |

**The system has not recovered from COVID.** Compliance fell ~25pp from 2018 to 2026 and is still declining at the end of the series. The 2022→2023 transition is the dominant break, not 2020→2022.

**Consequence:** a model trained on 2018-2022 (median ~88%) would be trained on a regime that no longer exists; it would be systematically biased high in the 2024+ holdout (median ~69%). The split windows must account for this.

## Chosen windows (D015)

| Partition | Window | Months | Sites | Rows | Compliance median |
|---|---|---|---|---|---|
| train | 2018-01 → 2023-12 | 72 | 30 | 2,160 | 89.3 |
| validation | 2024-01 → 2025-05 | 17 | 30 | 510 | 69.2 |
| holdout | 2025-06 → 2026-05 | 12 | 30 | 360 | 66.9 |
| pre_split (held aside) | 2007-07 → 2017-12 | 126 | 35 | 3,992 | 96.7 |

**Rationale for the train window (2018-2023):**
- Starts at 2018-01 because companion enrichment features (demographics/when/referral) only exist from 2018-01 (D010). Training earlier would force a core-only feature set.
- Ends at 2023-12 so the validation period (2024+) is entirely in the new low-compliance regime, forcing the model to be evaluated on the regime that actually exists today.
- Includes COVID (2020-2022) honestly: COVID months are real ED history, not outliers to be excluded. The model must handle them. Phase 5 will run a sensitivity check excluding COVID to quantify their influence.

**Rationale for the validation window (2024-01 → 2025-05):**
- 17 months in the current regime; used for hyperparameter selection and model comparison. This is the period whose distribution most closely resembles the holdout.

**Rationale for the holdout window (2025-06 → 2026-05):**
- 12 months, the most recent complete year. Pristine: never touched during model development. Scored exactly once in Phase 6.

**pre_split (2007-2017):**
- Held aside, not discarded. Available for an optional long-history core-only baseline (Phase 4) to test whether more history helps or hurts given the regime change.

## Residual distribution-shift risk (recorded honestly)

Even with this split, train (median 89.3) and validation+holdout (median ~68) are in different regimes. The model must learn to extrapolate the trend. Three mitigations will be explored in Phase 4/5:

1. **Trend features:** explicit time trend and recent-rolling compliance features so the model can track the drift.
2. **Recency-weighted training:** optionally weight recent train months more heavily (Phase 5 hyperparameter).
3. **Honest reporting:** if the model cannot bridge the gap, we report that result. The seasonal-naive baseline will face the same gap, so the *relative* comparison remains fair.

This is recorded as a limitation in the Phase 6 evaluation: the model is evaluated on its ability to forecast in a regime shift, which is harder than stationary forecasting. That is the honest problem.

## Leakage controls

Enforced in `src/ed_ops/splits.py` and tested in `tests/test_splits.py`:

| ID | Control | Status |
|---|---|---|
| L3a | Chronological ordering: train.end < val.start < holdout.start | ✅ PASS |
| L3b | No (site, month) in more than one partition | ✅ PASS |
| L3c | Every holdout site also appears in train | ✅ PASS |
| L1 | No target column or count-components in features | enforced Phase 4 (feature allow-list) |
| L2 | All feature lags ≤ month t | enforced Phase 4 (as-of construction) |
| L4 | Preprocessing fit on train only | enforced Phase 4 (pipeline architecture) |
| L5 | Holdout never used for selection | enforced Phase 6 (single scoring) |
| L6 | External enrichment as-of joined | enforced Phase 4 |
| L7 | Disaggregated series only as lagged features | enforced Phase 4 |

## Reproducibility

- Seed: `RANDOM_SEED = 20260721` (in `src/ed_ops/config.py`), recorded in every Split instance.
- Partition manifest: `data/processed/split_manifest.csv` (one row per panel row, 7,022 rows, labeled train/validation/holdout/pre_split).
- Partition summary: `data/processed/split_summary.csv`.
- Reconstruction: `from ed_ops.splits import build_temporal_split; split = build_temporal_split()`.

```bash
python -m pytest tests/test_splits.py -v   # 15 tests, all must pass
```
