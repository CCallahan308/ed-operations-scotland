# Code Review: ed-operations-scotland

> Manual review performed 2026-07-21 (CodeRabbit CLI not installed; project is not a git repo, so the AI-review skill could not run). All source/test files read; findings below are severity-grouped with file:line references.

## Summary

The project is methodologically sound and the test suite (85 tests) is genuinely catching real bugs — three were caught and fixed during development (target-column bug, seasonal-naive lag bug, manifest coverage bug). The leakage discipline is the strongest part: every phase has invariant tests, and the holdout was scored exactly once with the frozen config verified.

Five findings, ordered by severity. **One real bug (latent, not currently triggered), two quality issues worth fixing, two informational notes.** No critical security or data-integrity defects.

---

## Critical
*None.*

---

## Warning

### W1 — `CandidateAConfig` dataclass defaults don't match the frozen Phase 5 config
**Location:** `src/ed_ops/model.py:107-111`
**Severity:** Warning (latent bug — not triggered in current code paths, but a real footgun)

The dataclass defaults are:
```python
max_depth: int = 5
learning_rate: float = 0.05      # Phase 5 selected: 0.03
max_iter: int = 400              # Phase 5 selected: 500
l2_regularization: float = 0.5   # Phase 5 selected: 1.0
min_samples_leaf: int = 30       # Phase 5 selected: 40
```

The frozen Phase 5 selection (D018, recorded in `reports/candidate_a_config.json`) is `learning_rate=0.03, max_iter=500, l2_regularization=1.0, min_samples_leaf=40`. The defaults match the *Phase 4 grid's mid-value*, not the selected config.

**Why it matters:** `train_candidate_a()` passes the selected values explicitly when constructing `CandidateAConfig`, so the *trained* model is correct. But anyone who constructs `CandidateAConfig()` directly — for a notebook, a retrain experiment, or a fresh `CandidateA(config=CandidateAConfig(), ...)` — silently gets a different, weaker model. This is exactly the kind of stale-defaults defect that survives for months because "the tests pass."

**Fix:** Update the dataclass defaults to the frozen Phase 5 values, OR remove the defaults entirely (force callers to pass them). Add a test that asserts `CandidateAConfig()` defaults equal the frozen config in `reports/candidate_a_config.json`.

### W2 — `clean_activity_to_panel` quarantine check uses row-wise `apply` (slow + fragile)
**Location:** `src/ed_ops/data_quality.py:241-244`
**Severity:** Warning (performance + correctness smell)

```python
bad_mask = out.apply(
    lambda r: (r["TreatmentLocation"], r["Month"]) in QUARANTINED_SITE_MONTHS,
    axis=1,
)
```

Row-wise `apply` on 39,583 rows is ~100× slower than a vectorized merge/tuple-set lookup. More importantly, the tuple membership test depends on dtype: `Month` is read as string (`dtype=str`), so `("G405H", "201505")` matches; but if a future caller loads with `dtype={"Month": int}`, the quarantine silently stops matching (the set has `"201505"`, the row has `201505`).

**Fix:** Vectorize with an explicit string cast, and add a dtype assertion at the top of `clean_activity_to_panel`:
```python
assert df["Month"].dtype == object, "Month must be string; quarantine relies on it"
bad_mask = (
    out["TreatmentLocation"].isin({s for s, _ in QUARANTINED_SITE_MONTHS})
    & out["Month"].isin({m for _, m in QUARANTINED_SITE_MONTHS})
)
```
(The isin-on-each-column version is a conservative superset; a true tuple-match needs a merge. For 2 quarantined pairs the difference is negligible, but the dtype fragility is the real concern.)

---

## Info

### I1 — `evaluate()` `direction_tolerance_pp` default is undocumented in the metrics output
**Location:** `src/ed_ops/evaluation.py:73, 110-120`

The 0.5pp tolerance for "no change" in directional accuracy is reasonable, but it's a hidden parameter that affects the reported `directional_accuracy` metric. A reader comparing this project's `dir_acc=48.6%` to another model's `dir_acc` at tolerance=0 would be misled.

**Fix (minor):** Record `direction_tolerance_pp` in `Metrics` (or at least note it in the metric's docstring shown in reports). Not a bug; a transparency improvement.

### I2 — `_assert_no_overlap` iterates rows with `iterrows()` (slow)
**Location:** `src/ed_ops/splits.py:155-163, 222-245`

Two functions iterate panel rows with `iterrows()` to detect cross-partition key overlap and build the manifest. On 7,022 rows this is fine (~ms), but it's the wrong tool — a `set` of tuples built from `df[cols].itertuples()` or a `merge` would be cleaner and scale better. Same pattern in `build_split_manifest` (lines 222-245).

**Fix (optional):** Replace with vectorized set operations. Low priority given current data size.

### I3 — `f_attendance_yoy_pct` uses lag-13 but isn't documented as such
**Location:** `src/ed_ops/features.py:115-119`

The YoY attendance feature computes `(lag1 - lag13) / lag13` — lag-13 is "13 months ago," which is one month *before* the same-month-last-year. This is intentional (the feature compares prior month to ~one-year-prior-month, capturing demand trajectory), but it's not called out in the feature table in `docs/BASELINES_AND_FEATURES.md`, which lists only "YoY attendance change (demand growth)" without the lag detail.

**Fix (minor):** Add a one-line note in the feature doc table: `f_attendance_yoy_pct = (attendance[t-1] - attendance[t-13]) / attendance[t-13]`.

---

## What the review confirmed is correct

These were checked and are **not** bugs despite initial suspicion:

- **Seasonal-naive lag-11** (`baselines.py:115`): verified on real data — for target 2024-01 it predicts 65.51 (the Jan-2023 value), correctly. The off-by-one was fixed in Phase 4 and a regression test pins it.
- **Rolling-window `shift(1)` excludes current month** (`features.py:104-109`): verified — no target leakage from the rolling features.
- **`min_periods=max(1, w//2)`** allows partial windows for early site months; no leak (shift excludes current), just noisier early estimates. Acceptable.
- **Holdout freeze integrity**: `train_candidate_a()` passes selected params explicitly; the trained model matches `reports/candidate_a_config.json` exactly (verified in Phase 6 pre-scoring and Phase 7 sweep).
- **Count identity** (`within4 + over4 == total`): holds on all 39,583 raw rows; enforced by invariant test.
- **Target-column leakage guard**: `check_feature_leakage` correctly flags any bare compliance column; regression test pins the default `target_col="target_compliance"`.

## Recommended fix priority

1. **W1** (stale `CandidateAConfig` defaults) — fix now; add a regression test. ~10 minutes.
2. **W2** (quarantine dtype fragility) — fix now; the silent-no-match failure mode is dangerous. ~15 minutes.
3. **I1, I3** (documentation transparency) — batch into one docs pass. ~10 minutes.
4. **I2** (iterrows performance) — defer; not a current problem at this data size.
