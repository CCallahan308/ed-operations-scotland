# Phase 2: Data Quality Audit & Cleaning Rules

> Completed 2026-07-21. Every cleaning decision below states the condition found, the count affected, the treatment applied, the justification, and how it was validated. Automated tests in `tests/test_data_quality.py` guard against regression.

## Files audited

| File | Rows | Coverage | Grain |
|---|---|---|---|
| `nhs_scotland_ae_activity_monthly.csv` | 39,583 | 2007-07 → 2026-05 (227 mo) | site × month × dept × category |
| `nhs_scotland_ae_demographics.csv` | 136,322 | 2018-01 → 2026-04 (100 mo) | site × month × age × sex × deprivation |
| `nhs_scotland_ae_when.csv` | 615,758 | 2018-01 → 2026-04 (100 mo) | site × month × day × hour × in/out |
| `nhs_scotland_ae_referral.csv` | 150,547 | 2018-01 → 2026-04 (100 mo) | site × month × age × referral |
| `nhs_scotland_ae_multiple_attendances.csv` | 22 | annual (YearEnd) | board × year × repeat-bucket |

All five SHAs verified against `src/ed_ops/config.py::SOURCE_PROVENANCE`.

## Core numeric invariant (verified)

For every row in the activity file: `NumberWithin4HoursAll + NumberOver4HoursAll == NumberOfAttendancesAll`. **Tested on all 39,583 rows: 0 failures, max abs diff = 0.** The published `PercentageWithin4HoursAll` may carry small rounding artifacts (≤0.1pp on 3 rows) but the underlying counts reconcile exactly. This makes the count ratio the ground truth for recomputing the target.

## Findings and treatments

### F001 — Episode fields null for Type 3 (and some Type 1) rows
- **Condition:** `NumberOfAttendancesEpisode` and all Episode-derived columns (`*Within4HoursEpisode`, `*Over4HoursEpisode`, `*Over8/12HoursEpisode`) are null, with QF code `z` (PHS convention: "not applicable").
- **Affected:** 16,894 rows (42.7%). Breakdown: 16,594 are Type 3 departments; 300 are Type 1 at sites without episode reporting.
- **Treatment:** Restrict the primary modeling panel to **Type 1 sites where Episode fields are populated**, `AttendanceCategory = "All"`. Episode grain is the operationally meaningful one (one ED visit = one episode) and Type 1 major EDs are where the 4-hour standard bite is real.
- **Justification:** QF `z` means the field does not exist for that row, not that data is missing. Type 3 (minor injury units) do not report the 4h/8h/12h episode breakdown. Including them would require fabricating episode data.
- **Validation:** `test_episode_nulls_match_F001_count` asserts exactly 16,894 nulls all carrying `z`; `test_only_type1_all_category` asserts the panel row count matches the Type-1-All population.

### F002 — Duplicate keys with inconsistent values at G405H-201505
- **Condition:** Site `G405H`, month `201505`, Type 1 has duplicate key rows for both `All` and `Unplanned` categories. Within each duplicate pair, attendance values disagree: 4990 vs 137.
- **Affected:** 4 rows, 2 duplicate key combinations.
- **Treatment:** Quarantine site-month `G405H-201505` from the primary panel. Do **not** pick a row.
- **Justification:** Cannot determine the authoritative row from the data alone. Picking one would be a fabrication. Excluding 1 site-month out of ~7,000 Type-1 site-months is negligible coverage loss and preserves integrity.
- **Validation:** `test_duplicate_keys_match_F002` asserts the exact duplicate structure; `test_quarantined_site_months_excluded` asserts none appear in the panel.

### F003 — Invalid counts (within > total) at W106H-202505
- **Condition:** Site `W106H`, month `202505`, Type 3 reports `within4=96 > total=69`, `over4=-27` (negative), `PercentageWithin4HoursAll=139.1` (>100).
- **Affected:** 2 rows.
- **Treatment:** Quarantine site-month `W106H-202505`. Do **not** clip to 100; clipping would hide the underlying inconsistency.
- **Justification:** Negative count and >100% percentage indicate a PHS publication error, not a bounded-percentage artifact. Quarantine is the only honest treatment without an authoritative source to reconcile against. (W106H is Type 3 anyway, so it would be excluded by F001 regardless.)
- **Validation:** `test_invalid_counts_match_F003` asserts exactly 2 rows with `within > total`; `test_quarantined_site_months_excluded`.

### F004 — Constant Country column
- **Condition:** `Country` is constant (`S92000003` = Scotland) across all 39,583 rows.
- **Affected:** 39,583 rows.
- **Treatment:** Drop `Country` from the cleaned panel.
- **Justification:** A constant column carries no information for modeling or analysis.
- **Validation:** `test_country_constant_F004`.

### F005 — Published percentage artifacts (where counts are valid)
- **Condition:** `PercentageWithin4HoursAll` exceeds 100 in a small number of rows where the underlying counts are valid (`within4 ≤ total`).
- **Affected:** 0 rows after F003 quarantine (monitored).
- **Treatment:** For all panel rows, recompute the compliance percentage from counts: `compliance_pct = NumberWithin4HoursAll / NumberOfAttendancesAll * 100`, rounded to 2dp.
- **Justification:** Published percentages can carry rounding/aggregation artifacts. The count ratio is the ground truth; recomputing removes artifacts without discarding valid rows. This also enforces the count-ratio rule from `PROBLEM_FRAMING.md` (never average percentages).
- **Validation:** `test_recomputed_pct_matches_count_ratio` asserts exact equality between `compliance_pct` and the count ratio.

## Companion-file quality (demographics, when, referral)

- **Duplicate keys:** 0 in all three files (verified on natural keys including all breakdown columns).
- **Null attendance counts:** 0 in all three.
- **QF codes:** `:` marks suppressed/low-count breakdown cells (small denominators) in demographics and referral. These rows still carry a valid `NumberOfAttendances` and remain usable; the flag is preserved, not dropped.
- **Coverage:** all three companion files span 2018-01 → 2026-04 only (100 months), narrower than the activity core (2007-07 → 2026-05). Enrichment features derived from these files therefore begin in 2018-01; pre-2018 history is usable only for core-only baselines and long-series seasonality (D010).

## Primary panel output

| | |
|---|---|
| File | `data/processed/primary_panel_type1.parquet` |
| Rows | 7,022 site-months |
| Sites | 35 Type-1 EDs |
| NHS boards | 14 |
| Months | 227 (2007-07 → 2026-05) |
| Columns | `Month`, `HBT`, `TreatmentLocation`, `NumberOfAttendancesAll`, `NumberWithin4HoursAll`, `NumberOver4HoursAll`, `compliance_pct` |
| Target range | `compliance_pct`: 36.8 – 100.0 (median 94.4) |
| Attendance range | 212 – 11,920 per site-month (median 3,572) |
| Preview | `data/processed/primary_panel_preview.csv` (first 8 rows) |

## Reproduction

```bash
cd ed-operations-scotland
python -m pytest tests/test_data_quality.py -v          # 21 tests, all must pass
python -c "import sys; sys.path.insert(0,'src'); from ed_ops.data_quality import build_primary_panel; p=build_primary_panel(); print(p.shape)"
```

The panel is rebuilt from raw by `build_primary_panel()`; the parquet is a cached artifact, not a source of truth.
