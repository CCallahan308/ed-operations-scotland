# BI Data Model (DuckDB analytics layer)

The `sql/` layer rebuilds the analytical model directly from the raw Public Health
Scotland CSV using DuckDB, independently of the Python pipeline, and is reconciled
against it (see `scripts/run_sql.py` and `tests/test_sql_layer.py`).

## Grain

| Object | Grain | Rows (full data) |
|---|---|---|
| `raw_activity` (source) | site x month x department-type x attendance-category | 39,583 |
| `fact_site_month` (fact) | **one row per (TreatmentLocation x Month)**, Type 1 / AttendanceCategory 'All' | 7,022 |

The fact grain is the decision grain: an NHS board acts on a site's compliance for a
month. `fact_site_month` applies the same rules as `build_primary_panel`: Type-1 /
'All' filter, the two quarantined site-months excluded (F002, F003), and compliance
recomputed from counts.

## Star schema

```
              dim_calendar (month_id -> year, month_of_year, quarter, month_start)
                     |
   dim_board --- fact_site_month --- dim_site (site_id -> board_id)
   (board_id)   measures: attendances, within_4h, over_4h, compliance_pct
```

- **dim_site** - `site_id` (TreatmentLocation) with its `board_id` (HBT). 35 sites.
- **dim_board** - `board_id` (NHS board / HBT). 14 boards.
- **dim_calendar** - `month_id` (YYYYMM) decomposed to year, month-of-year, quarter, and a real date.

## Metric definitions

- **compliance_pct (row level)** = `within_4h / attendances * 100`, recomputed from
  counts, never the published percentage.
- **compliance_pct (aggregated)** = `SUM(within_4h) / SUM(attendances) * 100`
  (count-ratio re-aggregation). Aggregations **never average per-site percentages**,
  which would be size-biased. See `agg_by_month`, `agg_by_board_month`, `agg_by_site`.
- **median compliance (annual)** = `MEDIAN(compliance_pct)` across site-months in the
  year (`agg_annual_median`) - the structural-break series shown on the dashboard's
  "The data" page.

## Data-quality gates (`sql/validations.sql`, all must be 0)

| Gate | Rule |
|---|---|
| `count_identity_violations` | `within_4h + over_4h = attendances` on every row |
| `pct_range_violations` | `compliance_pct` within `[0, 100]` |
| `duplicate_grain_violations` | `(site, month)` unique |
| `null_key_violations` | no null site / month / attendances |

## Reconciliation

`scripts/run_sql.py` asserts the SQL fact table matches `build_primary_panel`
row-for-row: identical row count (7,022), identical keys and counts, and
`compliance_pct` within 0.01 pp (DuckDB rounds halves away from zero, pandas rounds
half-to-even; the underlying counts are identical). On the committed fixture the
match is exact.

## Run it

```bash
python scripts/run_sql.py            # full dataset
python scripts/run_sql.py --fixture  # committed 5-site fixture (no download)
```
