"""Precompute the dashboard artifact so the Streamlit app is a thin, deploy-safe view.

`build_dashboard_data()` runs the pipeline once (needs the raw data) and returns a
plain dict with everything the dashboard renders: panel summary + preview, the
annual-median structural-break series, the split summary + per-partition compliance
distributions, the holdout forecast (per-row actual / Candidate A / persistence),
feature importance, and the frozen config. `scripts/build_dashboard_data.py` writes
it to reports/dashboard_data.json, which is committed. The app loads that JSON and
needs neither the raw dataset nor a model fit at launch.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import sklearn

from ed_ops import features as features_mod
from ed_ops.config import REPORTS_DIR
from ed_ops.data_quality import build_primary_panel
from ed_ops.model import build_frozen_candidate
from ed_ops.splits import build_temporal_split

DASHBOARD_DATA_PATH = REPORTS_DIR / "dashboard_data.json"


def build_dashboard_data() -> dict:
    panel = build_primary_panel()
    p = panel.copy()
    p["m"] = p["Month"].astype(int)
    p["year"] = p["m"] // 100

    panel_summary = {
        "rows": int(len(p)),
        "sites": int(p["TreatmentLocation"].nunique()),
        "boards": int(p["HBT"].nunique()),
        "months": int(p["m"].nunique()),
        "month_min": int(p["m"].min()),
        "month_max": int(p["m"].max()),
        "compliance_min": float(p["compliance_pct"].min()),
        "compliance_max": float(p["compliance_pct"].max()),
        "compliance_median": float(p["compliance_pct"].median()),
    }
    panel_preview = panel.head(20).to_dict("records")
    annual_median = [
        {"year": int(y), "median_compliance": float(v)}
        for y, v in p.groupby("year")["compliance_pct"].median().items()
    ]

    split = build_temporal_split(panel=panel)
    split_summary, split_box = [], {}
    for part in (split.train, split.validation, split.holdout):
        split_summary.append(
            {
                "partition": part.name,
                "start_month": int(part.start_month),
                "end_month": int(part.end_month),
                "n_months": int(part.df["Month"].astype(int).nunique()),
                "n_sites": int(part.df["TreatmentLocation"].nunique()),
                "n_rows": int(len(part.df)),
                "compliance_median": float(part.df["compliance_pct"].median()),
            }
        )
        split_box[part.name] = [round(float(x), 2) for x in part.df["compliance_pct"].tolist()]

    candidate = build_frozen_candidate(split=split)
    ff = features_mod.FeatureBuilder().build(panel=panel)
    lo, hi = split.windows["holdout"]
    ho = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)].copy()
    ho["pred_ca"] = candidate.predict(ho)
    holdout_forecast = [
        {
            "site": r.TreatmentLocation,
            "month": int(r.target_month),
            "actual": round(float(r.target_compliance), 2),
            "pred_ca": round(float(r.pred_ca), 2),
            "pred_pers": round(float(r.prior_compliance), 2),
        }
        for r in ho.itertuples()
    ]

    fi = pd.read_csv(REPORTS_DIR / "candidate_a_feature_importance.csv")
    feature_importance = [
        {"feature": row.feature, "importance_mean": round(float(row.importance_mean), 4)}
        for row in fi.itertuples()
    ]

    return {
        "panel_summary": panel_summary,
        "panel_preview": panel_preview,
        "annual_median": annual_median,
        "split_summary": split_summary,
        "split_box": split_box,
        "holdout_forecast": holdout_forecast,
        "feature_importance": feature_importance,
        "frozen_config": candidate.config.to_dict(),
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
            "scikit_learn": sklearn.__version__,
            "python": platform.python_version(),
        },
    }


def write_dashboard_data(path: Path | None = None) -> Path:
    path = path or DASHBOARD_DATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_dashboard_data(), indent=2))
    return path


def load_dashboard_data(path: Path | None = None) -> dict:
    path = path or DASHBOARD_DATA_PATH
    return json.loads(Path(path).read_text())
