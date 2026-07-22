# ED Operations Analytics — NHS Scotland A&E Compliance Forecasting

> Forecast next-month site-level 4-hour compliance % across NHS Scotland A&E departments, to help operations teams target capacity support proactively.
>
> **Status:** Phases 0–7 complete. 92 tests green. Holdout evaluated once.

## Headline result (honest)

Candidate A is a gradient-boosted-tree + persistence ensemble. On the held-out 12 months (2025-06 → 2026-05):

| Model | Holdout MAE | 95% CI | Notes |
|---|---|---|---|
| **Candidate A** | **2.72 pp** | [2.50, 2.95] | beats persistence on point estimate |
| Persistence baseline | 2.87 pp | — | the bar |
| Seasonal naive | 4.12 pp | — | biased high by structural break |

**Candidate A beats persistence by +0.15 pp on the holdout, but the paired-bootstrap 95% CI on the improvement [-0.006, +0.299] includes zero — the gain is directionally real but not statistically significant on a 12-month evaluation window.** This is reported without hedging; see [`docs/HOLDOUT_PHASE6.md`](docs/HOLDOUT_PHASE6.md).

## What this is

A portfolio flagship blending Business Intelligence, Business Analytics, and Data Science on **real Public Health Scotland A&E open data** (site-month grain, 2007-07 → 2026-05, 103 treatment locations, 4h/8h/12h breach statistics).

The recurring decision: *each month, NHS board operations must decide where to focus capacity support for the next month.* This project forecasts site-level compliance to make that decision proactive rather than reactive.

## Data provenance

- Source: [Monthly A&E Activity and Waiting Times — Public Health Scotland](https://www.opendata.nhs.scot/dataset/monthly-accident-and-emergency-activity-and-waiting-times)
- License: UK Open Government Licence v3.0
- Local: `data/raw/nhs_scotland_ae_*.csv` (5 files, SHA-256 in [`DATA_SOURCE.md`](DATA_SOURCE.md))
- Modeling panel: 7,022 Type-1 site-months, 35 sites, 227 months

## Repository layout

```
ed-operations-scotland/
├── app.py            # Streamlit dashboard (5 pages, scoped to real artifacts)
├── data/
│   ├── raw/         # immutable PHS exports (5 CSVs; gitignored)
│   ├── external/    # reserved for holidays/weather (not used in v1)
│   └── processed/   # primary_panel_type1.parquet, split_manifest.csv
├── docs/            # 7 phase deliverables + execution plan + review handoff
├── pipeline/        # score_holdout.py (one-shot Phase 6 scoring)
├── reports/         # configs, metrics, figures (incl. dashboard screenshots)
├── sql/             # reserved (v2 BI layer)
├── src/ed_ops/      # config, data_quality, splits, baselines, features, model, evaluation
└── tests/           # 92 tests across 6 modules
```

## Dashboard

A Streamlit dashboard surfaces the real project artifacts across 5 pages:
**Overview** (honest headline + holdout CI), **The data** (panel + structural break),
**The split** (train/val/holdout + leakage controls), **Forecast** (Candidate A vs
persistence on holdout, by-site drilldown, worst errors), and **Model** (frozen config,
feature importance, limitations). No fabricated KPIs — every figure is computed from
the actual model and data.

```bash
python -m streamlit run app.py
```

Screenshots: `reports/figures/dashboard_*.png`.

## How to reproduce

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt

# Run the full test suite (92 tests)
python -m pytest tests/ -v

# Rebuild the primary panel from raw
python -c "import sys; sys.path.insert(0,'src'); from ed_ops.data_quality import build_primary_panel; build_primary_panel().to_parquet('data/processed/primary_panel_type1.parquet', index=False)"

# Re-score the holdout (NOTE: this is a reused evaluation if run again; see docs/HOLDOUT_PHASE6.md)
PYTHONPATH=src python pipeline/score_holdout.py
```

## Methodological discipline

This project follows the standard of a senior analytics professional:

- **Leakage audit at every phase** — 92 tests enforce raw-data integrity, count identities, no-target-in-features (L1), all-lags-≤-t (L2), chronological split (L3), and no-holdout-in-training (L5).
- **Honest baselines** — three baselines including seasonal naive; the actual bar turned out to be persistence (MAE 2.85 pp), not seasonal naive as originally framed.
- **Honest reporting of a negative-leaning result** — when Candidate A's tree alone lost to persistence (Phase 5), it was reported, not tuned away. When the holdout improvement failed to reach statistical significance (Phase 6), the CI was reported, not hidden.
- **Documented structural break** — NHS Scotland A&E compliance fell from ~97% (2007) to ~67% (2026) and is still declining. The model is evaluated on its ability to forecast *through* this regime change, which is the honest problem.

## Key documentation

| Doc | Purpose |
|---|---|
| [`docs/REVIEW_HANDOFF.md`](docs/REVIEW_HANDOFF.md) | **Review board handoff** — what to challenge, what's defensible, success criteria. *Start here for external review.* |
| [`docs/candidate_a_hong_kong_execution_plan.md`](docs/candidate_a_hong_kong_execution_plan.md) | Authoritative execution record (Phases 0–7, decisions D001–D021) |
| [`docs/PROBLEM_FRAMING.md`](docs/PROBLEM_FRAMING.md) | Phase 1: decision, target, metrics, leakage surface, non-claims |
| [`docs/DATA_QUALITY.md`](docs/DATA_QUALITY.md) | Phase 2: findings F001–F005, cleaning rules |
| [`docs/SPLIT_DESIGN.md`](docs/SPLIT_DESIGN.md) | Phase 3: structural-break analysis, leakage controls |
| [`docs/BASELINES_AND_FEATURES.md`](docs/BASELINES_AND_FEATURES.md) | Phase 4: baselines, feature spec, two bug-fix findings |
| [`docs/MODEL_PHASE5.md`](docs/MODEL_PHASE5.md) | Phase 5: model spec, error analysis, robustness |
| [`docs/HOLDOUT_PHASE6.md`](docs/HOLDOUT_PHASE6.md) | Phase 6: holdout result, CI, limitations, recommendation |

## Known limitations

1. 12-month holdout is small; the improvement CI includes zero.
2. Structural break (train median 89% vs holdout median 67%) dominates error; model extrapolates a trend.
3. Point forecasts only; no prediction intervals.
4. Site-month aggregate; cannot inform individual patient triage.
5. Not validated for generalization outside NHS Scotland or the 30 Type-1 holdout sites.
6. No causal claims — the model predicts; it does not estimate intervention effects.
