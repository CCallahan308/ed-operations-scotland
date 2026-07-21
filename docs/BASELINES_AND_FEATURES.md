# Phase 4: Baselines & Feature Pipeline

> Completed 2026-07-21. Records the three honest baselines (with real validation metrics), the leak-free feature pipeline, and two material findings that reshaped the work.

## Two material findings (both reshaped the plan)

### Finding 1: Two baseline bugs caught and fixed by tests

The initial baseline implementation had two real bugs, both caught by the test suite before any metric was reported:

1. **`evaluate()` default `target_col` bug.** The default was `compliance_pct` (the t value), not `target_compliance` (the t+1 actual being forecast). With the wrong default, persistence scored MAE=0.00 — a tell-tale leakage signal. Fixed: default is now `target_compliance`. A regression test (`test_scores_against_target_not_prior`) pins this.

2. **Seasonal-naive off-by-one lag.** The code used `lag12` of the current row (Month=t), giving the value at t-12. For forecasting t+1, the correct seasonal lookback is t-11 (the same calendar month as t+1). Verified on real data: A111H forecast for 2024-01 was incorrectly 64.59 (Dec-2022 value) instead of 65.51 (Jan-2023 value). Fixed: uses `shift(11)`. A regression test (`test_seasonal_naive_forecasts_same_calendar_month_last_year`) pins this.

Both bugs would have silently distorted every downstream metric. The tests now guard against recurrence.

### Finding 2: The honest bar is persistence, not seasonal-naive

PROBLEM_FRAMING.md anticipated the bar would be seasonal-naive. The evidence says otherwise:

| Baseline | MAE (validation) | RMSE | Directional acc | Bias |
|---|---|---|---|---|
| **persistence** | **2.85 pp** | 3.89 | 13.7% | -0.16 pp |
| seasonal naive | 3.84 pp | 5.01 | 52.5% | +1.22 pp |
| site historical mean | 19.26 pp | 22.20 | 45.1% | +19.24 pp |

**The bar Candidate A must beat is persistence at 2.85 pp MAE.** Persistence wins because:
- Compliance is strongly autocorrelated month-to-month (a site at 70% this month is likely near 70% next month).
- Seasonal naive is *biased high* (+1.22 pp) because the structural break (Phase 3) means last-year's-same-month reflects a higher-compliance regime that no longer exists.
- Site historical mean is catastrophic (+19 pp bias) because it averages in the pre-2022 high-compliance era.

Directional accuracy tells the same story: seasonal naive gets direction right 52.5% of the time (it captures the seasonal swing), while persistence is at 13.7% because it always predicts "no change" and compliance moves almost every month.

This is recorded as D016 — the bar is persistence, not seasonal-naive.

## Feature pipeline

21 features built with strict as-of logic. Verified leak-free by `check_feature_leakage()` (L1, L1b both PASS) and by 11 feature tests.

| Group | Features | Source | Lag rule |
|---|---|---|---|
| Compliance lags | `f_compliance_lag{1,2,3,6,11,12}` | `compliance_pct` | shift(lag), uses t-lag and earlier |
| Compliance rolling | `f_compliance_roll{3,6,12}_{mean,std}` | `compliance_pct` | shift(1).rolling(w) — window ends at t-1, never includes t |
| Attendance lags | `f_attendance_lag{1,2,12}` | `NumberOfAttendancesAll` | shift(lag) |
| Demand growth | `f_attendance_yoy_pct` | attendance | (lag1 - lag13)/lag13 × 100 |
| Calendar | `f_year`, `f_month_of_year`, `f_quarter` | Month | deterministic, no leakage possible |
| Trend | `f_months_since_site_start` | per-site cumcount | monotone, captures drift |
| Momentum | `f_recent_slope_3m` | `compliance_pct` | linear slope of last 3 lagged months |

**Validation null rate: 0% on all 21 features.** Every forecastable validation row has a complete feature vector — no imputation needed for the core panel.

### Why these features

- **Lag structure (1,2,3,6,11,12):** short lags capture autocorrelation (the persistence signal); lag-11 is the seasonal-naive lookback; lag-12 captures year-over-year level.
- **Rolling means/stds (3,6,12):** local level and volatility going into the forecast.
- **Attendance as demand signal:** breach pressure correlates with volume; YoY growth captures demand regime.
- **Calendar:** monthly seasonality (winter pressure) and trend.
- **Recent slope:** explicit momentum to help the model extrapolate the downtrend (Phase 3 structural break).

### What was NOT added (deferred to Phase 5 if needed)

- Companion-file enrichment features (demographics, when, referral). Available from 2018-01; would add age-mix, deprivation, hour-of-arrival, referral-source signals. Deferred because the core features are leak-free and fully populated; enrichment is a Phase 5 lever if the core model underfits.
- Target encoding of site identity. The 30 train sites are sparse for high-cardinality encoding; deferred unless the model needs site-specific offsets.
- External enrichment (holidays, weather). Same logic — a Phase 5 lever, not a Phase 4 foundation.

## Leakage controls enforced in this phase

| ID | Control | Where enforced | Status |
|---|---|---|---|
| L1 | No target column as feature | `check_feature_leakage` + test | ✅ PASS |
| L1b | All compliance-derived features are lagged/rolled | `check_feature_leakage` + test | ✅ PASS |
| L2 | All lags ≤ month t; rolling windows exclude current month | construction + test `test_rolling_window_excludes_current_month` | ✅ PASS |
| L4 | Transforms fit on train only | no learned state in Phase 4 (deterministic features only); Phase 5 will fit scalers/encoders on train | ✅ (n/a this phase) |
| L7 | Disaggregated series only as lagged features | no disaggregated series used yet | ✅ (n/a this phase) |

## Reproduction

```bash
python -m pytest tests/test_baselines.py tests/test_features.py -v   # 23 tests
python -c "import sys;sys.path.insert(0,'src');from ed_ops.baselines import run_all_baselines_on_partition; from ed_ops.splits import build_temporal_split; from ed_ops import evaluation; s=build_temporal_split(); [print(evaluation.evaluate(p).summary(n)) for n,p in run_all_baselines_on_partition(s.windows['validation']).items()]"
```

Baseline metrics artifact: `reports/baseline_metrics_validation.json`.
