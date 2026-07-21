# Phase 1: Problem Framing

> Locked 2026-07-21. This document is the Phase 1 deliverable. It is self-contained: a reviewer or PhD consultant can read it without chat history. Any change to the target, horizon, or metrics requires a new decision-log entry and an update here.

## Decision problem

NHS Scotland is held to a standard that **≥ 95% of A&E patients should be seen, treated, admitted, or discharged within 4 hours of arrival** (the "4-hour standard" / STP). Performance is reported at site and board level, monthly, by Public Health Scotland. Sites that breach attract political, regulatory, and operational pressure, and breaches correlate with worse patient outcomes.

**The recurring decision (built backward from):** each month, NHS board operations and site clinical leads must decide where to focus capacity support — staffing rotations, escalation beds, flow interventions — for the **next** month, given current demand signals.

**The gap this project addresses:** boards currently react to breaches after they happen. A forward-looking, per-site estimate of next-month compliance would let capacity support be **proactive rather than reactive**, and would surface *which* sites are deteriorating before they breach.

## Primary user / decision-maker

- **Primary:** NHS board operations / unscheduled-care performance leads (decide where to allocate capacity support next month).
- **Secondary:** site clinical leads (anticipate their own site's pressure), and PHS-style analysts (monitoring and decomposition).

## Analytical / predictive question

> *Given site-level A&E activity and breach history through month t, what is the expected 4-hour compliance percentage for each treatment location in month t+1?*

## Target specification

| Item | Specification |
|---|---|
| **Primary target** | `PercentageWithin4HoursEpisode` for the site-month, restricted to `AttendanceCategory = "All"` (single headline number per site-month). |
| **Type** | Regression on a bounded [0, 100] outcome. Reported as percentage points. |
| **Unit of analysis** | One row = one (TreatmentLocation × Month). DepartmentType and AttendanceCategory are reduced to a single headline series per site per month (see "Panel reduction"). |
| **Prediction horizon** | 1 month ahead (t+1), given information through end of month t. |
| **Decision horizon** | Monthly (the prediction drives next-month capacity allocation). |

### Panel reduction (must be done before split)

The raw activity file has multiple rows per (site × month): one per (DepartmentType × AttendanceCategory) combination. For the primary target panel we collapse to one headline row per (site × month):

- Keep `DepartmentType` in {Type 1, Type 2, Type 3} as a site-level descriptor where applicable, but the headline compliance series is the **all-department, all-category** number for that site-month.
- Retain disaggregated series (Type 1 only; Unplanned only) as **secondary targets** and candidate features, never as the primary target.
- Re-aggregation must use raw counts (`NumberWithin4HoursEpisode` / `NumberOfAttendancesEpisode` × 100), not averages of percentages, to avoid size-bias. Phase 2 will add an invariant test for this.

## In-scope and out-of-scope

**In scope**
- Forecasting site-month 4-hour compliance % across NHS Scotland treatment locations.
- Decomposing historical breach pressure by site, board, department type, attendance category, age, deprivation, referral source, and temporal pattern (the BI + BA layers).
- Honest evaluation against naive and seasonal-naive baselines using temporal cross-validation with a frozen holdout.

**Out of scope (explicit non-claims)**
- Patient-level risk prediction. The source is site-month aggregate; no individual patient is ever modeled.
- Causal claims about *what intervention will reduce breaches*. The model predicts, it does not recommend a treatment effect. Any "what-if" framing is descriptive scenario analysis, not a causal estimate.
- Cross-national generalization. The model is for NHS Scotland; transfer to England/Wales/NI/HK is out of scope and untested.
- Real-time (intra-month) nowcasting. Horizon is fixed at one calendar month ahead.

## Metrics & baseline

**Primary metric:** MAE in percentage points between predicted and actual site-month compliance. Chosen because it is on the same scale as the decision (a 3-pp error is operationally interpretable) and is robust to outliers.

**Secondary metrics**
- RMSE (penalizes large errors more — operationally meaningful because a single catastrophic month matters).
- Directional accuracy: did the model correctly predict improvement vs deterioration vs the prior month.
- Per-site MAE distribution (equity of accuracy across large and small sites).
- Calibration of prediction intervals (coverage of nominal 80%/90% intervals), if a probabilistic model is used.

**Minimum acceptable baseline (must beat to justify complexity)**
1. **Persistence:** next-month compliance = this-month compliance (per site).
2. **Seasonal naive:** next-month compliance = same calendar month one year ago (per site). This captures the dominant annual cycle and is the *real* bar.
3. **Site historical mean:** each site's long-run mean compliance.

The Candidate A model must beat **seasonal naive** on MAE in temporal CV to be worth deploying. If it does not, the honest recommendation is to retain the seasonal-naive forecast and report that result.

**Cost of errors (operational interpretation, recorded for Phase 6 threshold/cost framing)**
- **False alarm** (predict breach, none materializes): wasted escalation capacity, mild staff fatigue.
- **Miss** (predict compliance, breach materializes): unprepared site, worse patient outcomes, regulatory exposure.
- Misses are materially more costly than false alarms. This asymmetry will inform any secondary classification framing and the choice of prediction-interval coverage.

## Leakage risks (enumerated for Phase 3 enforcement)

| # | Risk | Source | Mitigation |
|---|---|---|---|
| L1 | **Target leakage** — any column derived from the t+1 outcome enters features | `PercentageWithin4Hours*`, `NumberWithin4Hours*`, `NumberOver4Hours*`, `NumberOver8/12Hours*` for the prediction month | Strict feature allow-list; invariant test asserts none of these column names appear in the feature matrix |
| L2 | **Time leakage** — features use information not yet available at forecast time | Any same-month (t+1) column; rolling stats computed with centered windows | All rolling/lag features use data ≤ month t only; as-of join enforced in code |
| L3 | **Group/entity leakage** — same site appears in both train and holdout with overlapping temporal context | Site-level autocorrelation | Site-disjoint *or* temporal holdout (Phase 3 will pick temporal holdout with all sites in train, holdout = most recent N months — see split note) |
| L4 | **Preprocessing leakage** — imputers/scalers/encoders fit on all data | Convenience fitting | All learned transforms fit on training partition only; enforced by pipeline architecture |
| L5 | **Hyperparameter selection on holdout** | Tuning against the final test set | Hyperparameters selected on temporal validation folds only; holdout scored once in Phase 6 |
| L6 | **Look-ahead in external enrichment** | Holidays/weather indexed late | External features carry their own timestamp and are joined with as-of logic |
| L7 | **Disaggregated-target leakage** | Type-1-only or Unplanned-only compliance for month t+1 leaking via features | Disaggregated series may appear only as **lagged** features (≤ month t) |

## Assumptions & non-claims

1. The published `PercentageWithin4HoursEpisode` for `AttendanceCategory = "All"` is the operationally correct headline compliance number. To be sanity-checked against PHS published headline figures in Phase 2.
2. Site identity is stable across the series (no silent re-coding of `TreatmentLocation`). Phase 2 will audit code changes.
3. One-month-ahead is the decision-relevant horizon; shorter (weekly) and longer (3-month) horizons are deferred.
4. COVID-era months (2020-2022) are retained but treated as a known structural break; the model must be robust to their inclusion or their exclusion, tested in Phase 5 sensitivity.
5. **Non-claim:** the model does not identify the causal effect of any intervention. Any scenario/simulation output is conditional projection, not a counterfactual.
6. **Non-claim:** the model is not a clinical triage tool and must not be used for individual patient management.

## Phase 1 → Phase 2 handoff

Phase 2 (data integrity and profiling) will:
- Implement raw-data integrity checks for all 5 downloaded CSVs against the SHAs and schemas in `DATA_SOURCE.md` and `src/ed_ops/config.py`.
- Profile nulls, duplicates, ranges, quality-flag codes, and temporal coverage per file.
- Build the cleaned site-month panel using the **count-ratio re-aggregation rule** above, with an invariant test guarding against averaging percentages.
- Document every cleaning decision with condition / count affected / treatment / justification / validation, per the operating rules.
