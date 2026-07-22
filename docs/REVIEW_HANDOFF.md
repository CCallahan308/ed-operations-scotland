# Review Handoff: NHS Scotland A&E Compliance Forecasting

> **Audience:** A review board of PhD-level data scientists and senior business analysts.
>
> **Purpose of this document:** to give the review board everything needed to (a) scrutinize the methodology, (b) reproduce or challenge specific claims, and (c) judge the business framing and decision-readiness — without reading the agent conversation log.
>
> **How to read it:** the project is honest about a *qualified-positive* result. The headline model beats the baseline on point estimate but **not** at statistical significance on the 12-month holdout. This document does not market the project; it surfaces exactly what is and isn't defensible.

---

## 1. The one-paragraph summary

We built a 1-month-ahead site-level forecast of NHS Scotland A&E 4-hour compliance %, on real Public Health Scotland open data (7,022 Type-1 site-months, 2007-07 → 2026-05). The deliverable model is a gradient-boosted-tree + persistence ensemble. On a frozen, never-touched 12-month holdout (2025-06 → 2026-05) it achieves **MAE 2.72 pp** vs the persistence baseline's 2.87 pp — a **+0.15 pp point-estimate improvement, but the paired-bootstrap 95% CI on the improvement [−0.006, +0.299] includes zero**, so the improvement is directionally favorable but not statistically distinguishable from the baseline at this sample size. The dominant error source is a structural break: Scotland A&E compliance has fallen monotonically from ~97% (2007) to ~67% (2026) and is still declining; the model is evaluated on its ability to forecast *through* this regime change, which is the honest problem but also a hard one.

---

## 2. What the review board should challenge

These are the load-bearing decisions and findings we most want scrutinized. Each has a documented rationale; a strong review will pressure-test the rationale, not just the code.

| # | Decision / finding | Why it deserves challenge | Where the evidence lives |
|---|---|---|---|
| **Q1** | **Target = next-month compliance % at site-month grain (D007).** | Aggregate site-month cannot inform patient-level triage or within-month surge response. Is the chosen grain actually the decision a board makes, or a constraint of the data? | `docs/PROBLEM_FRAMING.md` §Target, §Non-claims |
| **Q2** | **Pivot from Hong Kong HA snapshot data to NHS Scotland (D005).** | The HK dataset was a 3-field real-time snapshot; the pivot was forced by data availability. Reviewers should confirm NHS Scotland is the right alternative, not just the available one. | `docs/EXECUTION_LOG.md` D004–D005 |
| **Q3** | **Train window 2018-01 → 2023-12 (D015).** | We deliberately trained on the recent regime rather than the full 2007+ history, because the pre-2020 regime (median ~95%) no longer exists. This discards 10 years of data. Is that the right tradeoff? | `docs/SPLIT_DESIGN.md` §Chosen windows |
| **Q4** | **The bar is persistence (MAE 2.85), not seasonal naive (D016).** | PROBLEM_FRAMING.md anticipated seasonal naive as the bar; the evidence said otherwise because compliance is strongly autocorrelated and seasonal naive is biased high by the structural break. A reviewer may want to verify this reframing. | `docs/BASELINES_AND_FEATURES.md` §Finding 2 |
| **Q5** | **Candidate A is an ensemble with persistence (D019), not the tree alone.** | The tree alone *lost* to persistence (MAE 3.10 vs 2.85). The ensemble (0.4 tree + 0.6 persistence) was selected on validation. A reviewer should ask: is this a genuine model or a slight perturbation of the baseline? | `docs/MODEL_PHASE5.md` §Two honest findings |
| **Q6** | **The non-significant holdout result (D021).** | The point-estimate improvement is real (+0.15 pp) but the CI includes zero. We report it without hedging. A reviewer must judge whether the project succeeds given this. | `docs/HOLDOUT_PHASE6.md` §The honest statistical finding |
| **Q7** | **Structural-break handling is deferred, not solved.** | The model degrades more than the baseline across the regime change (bias grew from +0.14 pp on validation to +0.66 pp on holdout). We mitigated via the ensemble, we did not solve the break. | `docs/HOLDOUT_PHASE6.md` §Why the improvement shrank |
| **Q8** | **No causal claims.** | The model predicts; it does not estimate the effect of any intervention (staffing, beds, flow). The "decision support" framing is conditional projection, not counterfactual. | `docs/PROBLEM_FRAMING.md` §Non-claims |

---

## 3. The decision problem (for the business analysts)

**The recurring decision:** each month, NHS board operations leads must decide where to focus next month's capacity support — staffing rotations, escalation beds, flow interventions — given current demand signals.

**The honest gap this project fills:** boards currently react to breaches *after* they happen. A forward-looking per-site estimate of next-month compliance would let capacity support be proactive.

**What the model delivers operationally:**

1. A site-level 1-month-ahead compliance forecast at MAE ~2.7 pp — interpretable as "the model's typical monthly miss is under 3 percentage points per site."
2. Directional signal: it correctly predicts up-vs-down vs the prior month on ~48% of holdout rows (vs persistence's structural ~0%, since persistence always predicts "no change"). This is the *only* respect in which it clearly beats the baseline.
3. A complement to, not a replacement for, persistence. We explicitly recommend showing both forecasts plus the directional flag in any operational tool.

**What it does NOT deliver, and the business framing must be honest about:**

- It does not predict sharp one-month drops — and those are exactly the high-stakes months. The worst-5 holdout errors are all sharp reversals the model smoothed over (A111H May-2026: actual 57.7, predicted 68.8; abs error 11.1 pp).
- It does not quantify the effect of any intervention. It cannot answer "if we add 5 nurses, what's the compliance lift?" — only "given current trajectory, what compliance do we expect?"
- It is site-month aggregate. It cannot be used for individual patient triage or intra-month nowcasting.

**Reviewer question for the BA board:** *given that the holdout improvement is not statistically significant, is this model ready for operational use, or should it be retained as a research artifact pending a longer evaluation window?* Our recommendation (in `HOLDOUT_PHASE6.md`) is the former — deploy as complement to persistence, re-evaluate at 24+ months.

---

## 4. The methodology (for the data scientists)

### 4.1 Data and panel construction
- **Source:** Public Health Scotland *Monthly A&E Activity and Waiting Times* (UK OGL v3.0). SHA-256 provenance recorded for all 5 raw files.
- **Panel:** 7,022 Type-1 site-months, 35 sites, 227 months (2007-07 → 2026-05). One row per (site × month).
- **Cleaning (5 documented findings F001–F005):** restricted to Type-1 (the population where the 4h episode grain is reported and the policy bite is real); quarantined 2 unrecoverable site-months (G405H-201505 duplicate keys, W106H-202505 invalid counts); recomputed compliance % from counts (`within4 / total × 100`) rather than trusting published percentages, which carried ≤139.1% artifacts.
- **Core invariant verified:** `within4 + over4 == total` holds exactly on all 39,583 raw rows. This is the dataset's numeric ground truth.

### 4.2 Experimental design
- **Split:** chronological, all sites in every partition (D014). train 2018-01..2023-12 (2,160 rows), validation 2024-01..2025-05 (510), holdout 2025-06..2026-05 (360). Pre-2018 history (3,992 rows) held aside as `pre_split`.
- **Leakage controls (L1–L7):** no target column or its count-components in features (L1); all lags ≤ month t, rolling windows exclude current month via `shift(1)` (L2); chronological split with no key overlap (L3); no learned state in the feature pipeline (L4 satisfied trivially); holdout scored exactly once (L5); external enrichment not used (L6 n/a); disaggregated series not used (L7 n/a).
- **Each leakage control has an invariant test.** 111 tests total, all green.

### 4.3 Model
- **Family:** `HistGradientBoostingRegressor` (sklearn) blended with persistence: `pred = 0.4 × tree + 0.6 × prior_compliance`, clipped to [0, 100].
- **Selection:** joint search over 5 tree hyperparameter sets × 3 ensemble weights on validation only. Selected: `max_depth=5, learning_rate=0.03, max_iter=500, l2_reg=1.0, min_samples_leaf=40, weight=0.4`. The top candidates cluster within ~0.01 pp of each other, so the ranking among them is not stable across scikit-learn versions; the selected config is frozen to `reports/candidate_a_config.json` and loaded for all scoring rather than re-derived at runtime.
- **Features (21):** compliance lags (1,2,3,6,11,12); rolling mean/std (3,6,12); attendance lags (1,2,12); YoY attendance; calendar (year, month, quarter); months-since-site-start; 3-month momentum slope. All leak-free (L1/L1b guards PASS). Permutation importance shows `f_compliance_lag1` dominates (7.47 ΔMAE) — the model leans on persistence, which is why the ensemble formalizes that relationship.

### 4.4 Evaluation
- **Primary metric:** MAE in percentage points.
- **Validation:** Candidate A MAE 2.519 vs persistence 2.848 (+0.329 pp, 11.5% relative).
- **Holdout (scored once):** Candidate A MAE **2.7231** [bootstrap 95% CI 2.505, 2.948] vs persistence **2.870** (+0.147 pp).
- **Paired bootstrap (10,000 resamples of per-row persistence − CandidateA abs-error difference):** mean +0.147 pp, **95% CI [−0.006, +0.299] — includes zero.**

### 4.5 Robustness checks performed
1. **Seed stability** — 5 seeds → identical MAE 2.519 (HGBR is effectively deterministic here). Not a lucky draw.
2. **COVID-exclusion sensitivity** — retraining without 2020-03..2022-12 changes validation MAE by +0.015 pp. Including COVID is harmless and honest.
3. **Feature ablation** — 2-feature model (lag1 + roll3) gets 2.715; the full 21-feature set earns its complexity (+0.20 pp).
4. **Per-site equity** — ensemble wins on 28/30 validation sites; improvement is uniform across attendance quintiles.

---

## 5. What we explicitly do not claim

A reviewer who finds any of these claimed anywhere in the project should flag it as a defect:

1. **No patient-level prediction.** The source is site-month aggregate; no individual patient is modeled.
2. **No causal claims.** The model predicts compliance; it does not estimate the effect of any intervention. Any "what-if" framing is conditional projection, not counterfactual.
3. **No cross-national generalization.** Validated only on NHS Scotland, 30 Type-1 sites.
4. **No intra-month / real-time nowcasting.** Horizon is fixed at one calendar month ahead.
5. **No claim of statistical significance for the holdout improvement.** The CI includes zero; we say so.
6. **No clinical use.** Not a triage tool; must not be used for individual patient management.

---

## 6. How to reproduce (and how to challenge reproduction)

```bash
cd ed-operations-scotland
pip install -r requirements.txt
python -m pytest tests/ -v          # 111 tests; every leakage invariant is here
PYTHONPATH=src python pipeline/score_holdout.py   # re-scores the holdout (a reused evaluation if run again)
```

**Specific reproducibility claims a reviewer can verify in minutes:**
- Raw data SHA-256 matches `src/ed_ops/config.py::SOURCE_PROVENANCE` → confirms the data hasn't been touched.
- `build_primary_panel()` rebuilds the 7,022-row panel from raw, deterministically.
- `build_temporal_split()` rebuilds the train/val/holdout partitions with seed 20260721.
- `build_frozen_candidate()` reproduces val MAE 2.5192 exactly under the pinned scikit-learn range; the frozen config is loaded, not re-selected.
- `reports/candidate_a_config.json` is the frozen config; `reports/holdout_evaluation.json` is the one-pass holdout result.

**Specific things a reviewer can challenge:**
- Re-run `score_holdout.py` with a *different* holdout window (e.g. shift by 6 months) — does the qualified-positive finding hold, or is it an artifact of this particular 12-month window?
- Re-fit excluding the ensemble (weight=1.0) — confirm the tree alone loses to persistence (D018).
- Add the deferred companion enrichment (demographics/when/referral) — does it materially change the holdout result, or is the structural break the binding constraint as we claim (D020)?

---

## 7. Documentation map

The review board should read these in this order; each is self-contained.

| Priority | Doc | What it proves / frames |
|---|---|---|
| 1 | `docs/PROBLEM_FRAMING.md` | The decision, the target, the leakage surface, the non-claims. *Start here.* |
| 2 | `docs/HOLDOUT_PHASE6.md` | The honest result, the CI, the recommendation. *The thing being reviewed.* |
| 3 | `docs/MODEL_PHASE5.md` | The model, the two findings (tree loses; ensemble fixes), robustness. |
| 4 | `docs/SPLIT_DESIGN.md` | The structural break that drives everything, and the split that accounts for it. |
| 5 | `docs/BASELINES_AND_FEATURES.md` | Why the bar is persistence, the two bug-fix findings. |
| 6 | `docs/DATA_QUALITY.md` | The 5 cleaning findings; the count-identity ground truth. |
| 7 | `docs/CODE_REVIEW.md` | The most recent internal review (2 warnings found and fixed). |
| 8 | `docs/EXECUTION_LOG.md` | The full execution record: 21 decisions (D001–D021), 36 validation-ledger entries. Read if you want the audit trail. |

---

## 8. Reviewer-facing success criteria

We propose the review board judge the project against these criteria. We do not assert all are met; we assert each is *honestly addressed*.

| Criterion | Status | Evidence |
|---|---|---|
| Real business problem, not generic EDA | ✅ Met | Recurring monthly capacity-allocation decision (PROBLEM_FRAMING.md) |
| Honest baseline the model must beat | ✅ Met | Persistence at MAE 2.85 (D016); reframed from seasonal naive on evidence |
| Leakage-safe methodology | ✅ Met | L1–L7 controls, 88 invariant tests, holdout scored once |
| Honest reporting of a non-ideal result | ✅ Met | Non-significant holdout CI reported without hedging (D021) |
| Reproducible end-to-end | ✅ Met | Deterministic rebuild from raw; pinned deps; 111 tests |
| Decision-ready output | ⚠️ Partial | Forecasts interpretable; but improvement not significant and sharp drops missed |
| Statistically significant improvement over baseline | ❌ Not met | CI [−0.006, +0.299] includes zero on 12-month holdout |
| Causal / intervention insight | ❌ Out of scope (by design) | Explicitly disclaimed; aggregate data cannot support causal claims |

---

## 9. The question we most want the board to answer

> *Given (a) a directionally favorable but non-significant holdout improvement, (b) a structural break that is the binding constraint and is not solvable with this data, and (c) a model whose strongest feature is the persistence signal it blends with — should this project ship as a complement-to-persistence operational tool (our recommendation), or be retained as a research artifact pending a longer evaluation window and richer data?*

Either answer is defensible. We've designed the project so the board can reach its own conclusion from the evidence, not from our framing.
