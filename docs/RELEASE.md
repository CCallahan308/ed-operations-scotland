# Release Checklist and Portfolio Packaging

## Pre-release verification (run 2026-07-22, on a fresh `git clone`)

| Check | Result |
|---|---|
| Fresh clone in a temp directory | PASS |
| Raw data absent on clone (gitignored), quickstart documents fetch/fixture | PASS |
| Fixture-mode `pytest` (no dataset) | PASS - 37 passed, 74 skipped |
| Full-data workflow (fetch -> score_holdout -> run_sql -> build_dashboard_data -> pytest) | PASS - 111 passed |
| Regenerated artifacts match committed (deterministic, seed-stable) | PASS - metrics, CIs, by-month all identical |
| `ruff check` / `ruff format --check` | PASS |
| CI config reviewed (`.github/workflows/ci.yml`, Python 3.11/3.12) | PASS (validated locally; run on push) |
| SQL layer reconciles to the Python pipeline | PASS - 7,022 rows, gates 0, compliance within 0.01 pp |
| Dashboard renders headless (all 5 pages) | PASS - `tests/test_app_smoke.py` |
| README links resolve; commands and metrics accurate | PASS |
| No secrets, no local file paths, no ignored-but-required artifacts | PASS |

**Blocked (require the maintainer's accounts, not a code issue):**
- Pushing to GitHub (enables the live CI run and the CI badge).
- Deploying the dashboard to Streamlit Community Cloud (enables the live demo link).

## Positioning (factual)

> Leakage-safe time-series forecasting for NHS Scotland A&E operations, with
> reproducible evaluation, baseline comparisons, uncertainty reporting, and an
> honest holdout result.

The model does **not** beat the baseline at statistical significance (the
improvement's 95% CI includes zero); the copy below reflects that.

## GitHub repository description (<160 chars)

Leakage-safe forecasting of NHS Scotland A&E 4-hour compliance: chronological holdout, honest (null-leaning) evaluation, DuckDB BI layer, Streamlit dashboard.

## GitHub topics

`data-science` · `time-series-forecasting` · `analytics-engineering` · `duckdb` · `streamlit`

## LinkedIn Featured - title

NHS Scotland A&E Compliance Forecasting - leakage-safe ML with an honest holdout

## LinkedIn Featured - description (~140 words)

I built a site-level, one-month-ahead forecast of NHS Scotland A&E 4-hour
compliance on 19 years of real Public Health Scotland data. The emphasis is
evaluation rigor, not a leaderboard number: a chronological train/validation/holdout
split, as-of features with enforced leakage controls, three baselines, and a holdout
scored exactly once. The result is honest - a gradient-boosted-tree + persistence
ensemble beats the persistence baseline on point estimate (MAE 2.72 vs 2.87 pp), but
the improvement's 95% confidence interval includes zero, so I report it as not
statistically significant. The project ships a DuckDB star-schema BI layer reconciled
to the Python pipeline, a deploy-ready Streamlit dashboard, pinned dependencies, CI,
and 111 tests. Tech: Python, scikit-learn, pandas, DuckDB, Plotly, Streamlit.

## Resume bullet

Built a leakage-safe, reproducible NHS A&E compliance forecaster (Python,
scikit-learn, DuckDB, Streamlit): chronological holdout scored once, bootstrap
confidence intervals, a SQL BI layer reconciled to the pipeline, CI, and 111 tests;
reported the honest null-leaning result rather than overclaiming a win.
