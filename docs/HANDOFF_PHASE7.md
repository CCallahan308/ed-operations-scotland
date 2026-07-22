# Phase 7: Reproducibility & Handoff

> Completed 2026-07-21. Every quality check passes; every doc claim is verified against code and artifacts.

## Verification sweep (all run, all pass)

| Check | Command | Result |
|---|---|---|
| Full test suite | `python -m pytest tests/ -v` | **92 passed** across 6 modules |
| Lint | `python -m ruff check src/ tests/ pipeline/` | All checks passed |
| Format | `python -m ruff format --check src/ tests/ pipeline/` | 16 files already formatted |
| Panel rebuilds from raw | `build_primary_panel()` | 7,022 rows, 35 sites (matches docs) |
| Split rebuilds deterministically | `build_temporal_split()` | seed=20260721, train=2160, val=510, holdout=360 |
| Frozen config integrity | compare current `build_frozen_candidate()` to `reports/candidate_a_config.json` | Exact match (weight 0.4, val MAE 2.5192) |

## Issues found and fixed in Phase 7

1. **Lint: 29 errors + 13 files needing reformat.** Applied `ruff check --fix` (26 auto-fixes) + `ruff format` (13 files), then 3 manual fixes (long line in `score_holdout.py`, unused `holdout_lo` and `split` vars in `test_model.py`). Final: 0 errors.
2. **`requirements.txt` was incomplete.** Phase 0 note said modeling deps would be added in Phase 4/5 — that never happened. Code imports `sklearn` (Phase 5) and `matplotlib` (Phase 5/6 figures) but neither was declared. Fixed: added `scikit-learn` (now pinned `>=1.6.1,<1.8`) and `matplotlib`; removed unused `black` (we use `ruff format`). Verified: third-party imports now exactly match declared deps (`numpy, pandas, pytest, sklearn` in tested code; `matplotlib` in analysis scripts).
3. **README was the Phase 0 version.** Rewrote to reflect the finished project: headline holdout result with the honest CI, full repo layout, reproduction commands, methodological discipline section, and all 7 phase-doc links.

## Documentation consistency audit

Every quantitative claim in the docs was verified against the actual artifacts:

| Claim | Source | Verified value |
|---|---|---|
| Activity CSV SHA-256 | DATA_SOURCE.md / config.py | `746a19c7...e84f6b0` ✓ |
| Panel: 7,022 rows, 35 sites | README / DATA_QUALITY.md | ✓ |
| Train median compliance 89.3 | SPLIT_DESIGN.md | ✓ |
| Holdout median compliance ~67 | SPLIT_DESIGN.md / HOLDOUT_PHASE6.md | ✓ |
| Validation MAE 2.519 | MODEL_PHASE5.md / candidate_a_config.json | 2.5192 ✓ |
| Ensemble weight 0.4 | MODEL_PHASE5.md / candidate_a_config.json | 0.4 ✓ |
| Holdout MAE 2.723 | HOLDOUT_PHASE6.md / holdout_evaluation.json | 2.7231 ✓ |
| Holdout 95% CI [2.505, 2.948] | HOLDOUT_PHASE6.md | [2.5047, 2.9477] ✓ |
| Holdout improvement +0.147 pp | HOLDOUT_PHASE6.md | 0.147 ✓ |
| Persistence holdout MAE 2.870 | HOLDOUT_PHASE6.md | 2.87 ✓ |
| 92 tests | README | ✓ |
| 5 raw CSVs | DATA_SOURCE.md | ✓ |

## Unresolved issues

None at blocker level. The following are documented limitations, not defects:

1. Holdout CI includes zero — a property of the data (12-month window, structural break), not a bug. Reported honestly in HOLDOUT_PHASE6.md.
2. `sql/` and `notebooks/` directories are empty placeholders for the v2 BI/dashboard layer — not part of the Phase 0–7 scope.
3. The stale `ed-operations-hong-kong/` directory (from the pre-pivot scaffold) is locked by OneDrive sync and could not be removed; flagged for manual cleanup. It contains no Scotland data and is not referenced by any Scotland code.

## Reproducibility statement

A clean-environment run from the recorded state reproduces:

- The primary panel (7,022 rows) from `data/raw/` via `build_primary_panel()`.
- The train/validation/holdout split (seed 20260721) via `build_temporal_split()`.
- The frozen Candidate A model (val MAE 2.5192) via `build_frozen_candidate()`.
- The holdout evaluation (MAE 2.7231) via `pipeline/score_holdout.py`.

Determinism is enforced by: fixed `RANDOM_SEED=20260721`, pinned dependency floors in `requirements.txt`, no learned state in the feature pipeline (Phase 4), and HGBR seed stability verified across 5 seeds (Phase 5 robustness check — identical MAE).

## Handoff

The project is complete to the bar defined in the operating rules. Final artifacts:

- **Code:** `src/ed_ops/` (7 modules) + `pipeline/score_holdout.py`
- **Tests:** `tests/` (6 modules, 92 tests, all green)
- **Docs:** `docs/` (7 phase deliverables + execution plan)
- **Reports:** `reports/` (configs, metrics, feature importance, 2 figures)
- **Data:** `data/raw/` (5 immutable PHS CSVs) + `data/processed/` (panel, manifest, summary)

Reproduction entrypoint: `pip install -r requirements.txt && python -m pytest tests/`.
