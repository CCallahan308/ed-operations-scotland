# ED Operations Analytics - NHS Scotland A&E Compliance Forecasting

[![CI](https://github.com/CCallahan308/ed-operations-scotland/actions/workflows/ci.yml/badge.svg)](https://github.com/CCallahan308/ed-operations-scotland/actions/workflows/ci.yml)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Data: OGL v3.0](https://img.shields.io/badge/data-OGL%20v3.0-lightgrey.svg)](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
[![Code style: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://docs.astral.sh/ruff/)

> Forecast next-month site-level 4-hour compliance % across NHS Scotland A&E departments, so operations teams can target capacity support before a site slips rather than after.

**Status:** Phases 0-7 complete plus a post-audit hardening pass. Holdout scored once. 111 tests, CI green on Python 3.11 and 3.12.

## Headline result (honest)

Candidate A is a gradient-boosted-tree + persistence ensemble. Scored once on the held-out
12 months (2025-06 -> 2026-05, n=360 site-months, 30 Type-1 sites):

| Model | Holdout MAE | RMSE | 95% CI on MAE | Notes |
|---|---|---|---|---|
| **Candidate A** | **2.72 pp** | 3.48 | [2.50, 2.95] | beats persistence on the point estimate |
| Persistence (lag-1) | 2.87 pp | 3.67 | - | the real bar |
| Seasonal naive (lag-11) | 4.12 pp | 5.42 | - | biased high by the structural break |
| Site historical mean | 19.51 pp | 22.22 | - | shows how far the regime has moved |

**Candidate A beats persistence by +0.15 pp, but the paired-bootstrap 95% CI on that
improvement is [-0.006, +0.299] and includes zero. The gain is directionally real and not
statistically significant on a 12-month window.** That is the finding, reported without
hedging. See [`docs/HOLDOUT_PHASE6.md`](docs/HOLDOUT_PHASE6.md).

The model also improves on validation (MAE 2.52 pp vs persistence 2.85 pp, 2024-01 -> 2025-05),
and beats persistence in 7 of the 12 holdout months, with its largest margins in the final
three. Neither fact rescues the confidence interval.

## What this is

A portfolio flagship blending Business Intelligence, Business Analytics, and Data Science on
**real Public Health Scotland A&E open data** (site-month grain, 2007-07 -> 2026-05, 103
treatment locations, 4h/8h/12h breach statistics).

The recurring decision: *each month, NHS board operations must decide where to focus capacity
support for the next month.* This project forecasts site-level compliance so that decision can
be made ahead of the month rather than after it.

## What this demonstrates

- **Leakage-safe time-series ML** - chronological split, as-of features, a holdout scored once,
  and a frozen config that is loaded rather than re-searched, so the result reproduces across
  machines.
- **Honest evaluation** - three baselines, paired-bootstrap confidence intervals, and a
  null-leaning result reported as a null-leaning result.
- **Analytics engineering / SQL** - a DuckDB star-schema layer (fact + dimensions + count-ratio
  aggregations) reconciled to the Python pipeline row-for-row
  ([`docs/BI_DATA_MODEL.md`](docs/BI_DATA_MODEL.md)).
- **BI / dashboarding** - a deployed Streamlit app rendered from committed artifacts, with
  honest KPI framing and no fabricated numbers.
- **Engineering discipline** - pinned dependencies, CI on two Python versions, 111 tests, and a
  committed fixture so the suite runs without the dataset.

## Live demo

The dashboard runs on Streamlit Community Cloud: **[hosted demo](https://ed-operations-scotland-capstone.streamlit.app/)**

Five pages, all computed from the actual model and data:
**Overview** (headline + holdout CI), **The data** (panel + structural break), **The split**
(train/validation/holdout + leakage controls), **Forecast** (Candidate A vs persistence, by-site
drilldown, worst errors), and **Model** (frozen config, feature importance, limitations).

Run it locally:

```bash
python -m streamlit run app.py
```

Screenshots: `reports/figures/dashboard_*.png`.

## Quickstart (clone and run)

```bash
# 1. Clone and enter
git clone https://github.com/CCallahan308/ed-operations-scotland.git
cd ed-operations-scotland

# 2. Create an isolated environment (Python 3.11+ recommended; 3.10 works)
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 3. Install pinned dependencies
pip install -r requirements-dev.txt  # full pipeline, tests, SQL layer
#   ...or: pip install -r requirements.txt   (dashboard only, no ML/SQL stack)

# 4. Fetch the real dataset (~5 MB, Public Health Scotland, OGL v3.0)
python scripts/fetch_data.py         # add --all for the optional companion files
#    ...or skip this step: the suite runs a committed 5-site fixture
#    (tests/fixtures/activity_sample.csv), so pytest works with no download.

# 5. Run the tests
python -m pytest tests/ -q
#    with full data : 111 passed
#    fixture only   : 37 passed, 74 skipped (full-data tests need step 4)

# 6. (optional) Regenerate the holdout evaluation from raw (needs step 4)
PYTHONPATH=src python pipeline/score_holdout.py

# 7. Launch the dashboard
python -m streamlit run app.py
```

**Reproducibility.** Dependencies are pinned (`scikit-learn>=1.6.1,<1.8`). The model
configuration is frozen in `reports/candidate_a_config.json` and loaded at scoring time, so no
hyperparameter search runs during evaluation and the holdout result is stable across machines.
`scripts/fetch_data.py` verifies every download against the SHA-256 recorded in
`src/ed_ops/config.py` (the 2026-07-21 snapshot); a mismatch means Public Health Scotland has
revised the dataset since then. Every metrics artifact carries its own provenance block (Python
version, scikit-learn version, source SHA-256, random seed, UTC timestamp).

## Data provenance

- Source: [Monthly A&E Activity and Waiting Times - Public Health Scotland](https://www.opendata.nhs.scot/dataset/monthly-accident-and-emergency-activity-and-waiting-times)
- License: UK Open Government Licence v3.0
- Local: `data/raw/nhs_scotland_ae_*.csv` (5 files, gitignored; SHA-256 in [`DATA_SOURCE.md`](DATA_SOURCE.md))
- Modeling panel: 7,022 Type-1 site-months, 35 sites, 227 months
- Split: train 2018-01 -> 2023-12 | validation 2024-01 -> 2025-05 | holdout 2025-06 -> 2026-05

## Repository layout

```
ed-operations-scotland/
|-- app.py              # Streamlit dashboard (thin view over committed artifacts)
|-- .github/workflows/  # ci.yml (ruff + pytest on push/PR, Python 3.11 and 3.12)
|-- .streamlit/         # theme config for deployment
|-- data/
|   |-- raw/            # PHS exports (gitignored; fetch via scripts/fetch_data.py)
|   |-- external/       # reserved for holidays/weather (not used in v1)
|   \-- processed/      # rebuilt artifacts (gitignored; reproducible)
|-- docs/               # phase deliverables, BI data model, review handoff, execution log
|-- notebooks/          # 01_data_exploration.ipynb (reproducible EDA)
|-- pipeline/           # score_holdout.py (one-shot holdout scoring)
|-- reports/            # frozen config, metrics, feature importance, dashboard_data.json
|-- scripts/            # fetch_data.py, run_sql.py, build_dashboard_data.py
|-- sql/                # DuckDB analytics layer (fact + dims + aggregations + validations)
|-- src/ed_ops/         # config, data_quality, splits, baselines, features, model, evaluation, dashboard_data
\-- tests/              # 111 tests across 10 modules (fixture-runnable; full-data tests skip)
```

## SQL / BI layer

`sql/` is a runnable DuckDB analytics layer that rebuilds the model from the raw CSV
independently of the Python code: a `fact_site_month` fact table, `dim_site` / `dim_board` /
`dim_calendar` dimensions, count-ratio aggregations (`agg_by_month`, `agg_by_board_month`,
`agg_annual_median`, `agg_by_site`), and data-quality gates. Aggregations use
`SUM(within4)/SUM(total)`, never an average of percentages. `scripts/run_sql.py` runs the gates
and reconciles the SQL fact table to `build_primary_panel` row-for-row (7,022 rows; compliance
within 0.01 pp of the Python value). See [`docs/BI_DATA_MODEL.md`](docs/BI_DATA_MODEL.md).

```bash
python scripts/run_sql.py            # full dataset
python scripts/run_sql.py --fixture  # committed fixture, no download
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request against Python 3.11 and 3.12:
`ruff check`, `ruff format --check`, and `pytest`. CI uses only the committed fixture (no data
download, no secrets), so it reports the fixture-only result (37 passed, 74 skipped). Reproduce
the CI checks locally:

```bash
ruff check src/ tests/ pipeline/ app.py scripts/
ruff format --check src/ tests/ pipeline/ app.py scripts/
pytest tests/ -q
```

## Methodological discipline

- **Leakage audit at every phase** - tests enforce raw-data integrity, count identities,
  no-target-in-features (L1), all-lags-<=-t (L2), chronological split (L3), and
  no-holdout-in-training (L5).
- **Honest baselines** - three baselines including seasonal naive. The bar turned out to be
  persistence (validation MAE 2.85 pp; 2.87 pp on the holdout), not seasonal naive as originally
  framed, and the framing was corrected rather than kept.
- **Honest reporting of a negative-leaning result** - when Candidate A's tree alone lost to
  persistence (Phase 5), it was reported, not tuned away. When the holdout improvement failed to
  reach significance (Phase 6), the CI was published, not buried.
- **Documented structural break** - NHS Scotland A&E compliance fell from ~97% (2007) to ~67%
  (2026) and is still declining. The model is evaluated on its ability to forecast *through*
  that regime change, which is the honest version of the problem.

## Key documentation

| Doc | Purpose |
|---|---|
| [`docs/REVIEW_HANDOFF.md`](docs/REVIEW_HANDOFF.md) | **Review board handoff** - what to challenge, what's defensible, success criteria. *Start here for external review.* |
| [`docs/EXECUTION_LOG.md`](docs/EXECUTION_LOG.md) | Authoritative execution record (Phases 0-7, decisions D001-D021) |
| [`docs/PROBLEM_FRAMING.md`](docs/PROBLEM_FRAMING.md) | Phase 1: decision, target, metrics, leakage surface, non-claims |
| [`docs/DATA_QUALITY.md`](docs/DATA_QUALITY.md) | Phase 2: findings F001-F005, cleaning rules |
| [`docs/SPLIT_DESIGN.md`](docs/SPLIT_DESIGN.md) | Phase 3: structural-break analysis, leakage controls |
| [`docs/BASELINES_AND_FEATURES.md`](docs/BASELINES_AND_FEATURES.md) | Phase 4: baselines, feature spec, two bug-fix findings |
| [`docs/MODEL_PHASE5.md`](docs/MODEL_PHASE5.md) | Phase 5: model spec, error analysis, robustness |
| [`docs/HOLDOUT_PHASE6.md`](docs/HOLDOUT_PHASE6.md) | Phase 6: holdout result, CI, limitations, recommendation |
| [`docs/BI_DATA_MODEL.md`](docs/BI_DATA_MODEL.md) | DuckDB star schema and Python reconciliation |
| [`DATA_SOURCE.md`](DATA_SOURCE.md) | Source URLs, licence terms, file-level SHA-256 |

## Known limitations

1. The 12-month holdout is small (n=360); the improvement CI includes zero.
2. The structural break (train median 89% vs holdout median 67%) dominates error, and the model
   extrapolates a trend rather than modeling its cause.
3. Point forecasts only; no prediction intervals are produced or evaluated.
4. Site-month aggregate, so it cannot inform individual patient triage.
5. Not validated for generalization outside NHS Scotland or the 30 Type-1 holdout sites.
6. No causal claims. The model predicts; it does not estimate intervention effects.

## Deploying your own instance

The dashboard is a thin view over committed artifacts (`reports/dashboard_data.json`,
`reports/holdout_evaluation.json`): it renders with **no raw data and no model fit at launch**,
so it deploys cleanly and starts fast. Regenerate the artifacts after any model or data change
with `python scripts/build_dashboard_data.py`.

1. Fork this repository.
2. At https://share.streamlit.io, create an app pointing at `app.py` on `main`.
3. No secrets and no data upload are required.

## License

Code: [MIT](LICENSE). Data: UK Open Government Licence v3.0, (c) Public Health Scotland.
This project is not affiliated with, endorsed by, or produced for NHS Scotland or Public Health
Scotland.
