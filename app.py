"""ED Operations Analytics - NHS Scotland A&E Compliance Forecasting.

Streamlit dashboard. A thin view over committed artifacts: it reads
reports/dashboard_data.json and reports/holdout_evaluation.json and renders them.
It needs neither the raw dataset nor a model fit at launch, so it deploys cleanly
(regenerate the artifacts with scripts/build_dashboard_data.py after any change).

Pages (scoped to what genuinely exists - no fabricated KPIs):
  1. Overview  - the honest headline result + holdout CI
  2. The data  - the cleaned panel and the structural break
  3. The split - train/validation/holdout windows
  4. Forecast  - Candidate A vs persistence on the holdout
  5. Model     - frozen config, feature importance, limitations
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="NHS Scotland A&E Compliance Forecasting",
    page_icon="\U0001f3e5",
    layout="wide",
)

REPORTS = Path(__file__).parent / "reports"

NAVY = "#0b2545"
ACCENT = "#d62828"
MUTED = "#6c757d"


# ---------------------------------------------------------------------------
# Artifact loaders (committed JSON; no raw data or model fit required)
# ---------------------------------------------------------------------------


@st.cache_data
def load_json(name: str) -> dict | None:
    path = REPORTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def kpi_card(label: str, value: str, sub: str = "", color: str = NAVY):
    st.markdown(
        f"""
        <div style="border-left:4px solid {color}; padding:8px 14px; margin-bottom:10px;
                    background:#f8f9fa; border-radius:4px;">
          <div style="font-size:0.8rem; color:{MUTED}; text-transform:uppercase;
                      letter-spacing:0.04em;">{label}</div>
          <div style="font-size:1.7rem; font-weight:700; color:{color}; line-height:1.1;">{value}</div>
          <div style="font-size:0.78rem; color:{MUTED};">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def month_to_date(month_int: int) -> pd.Timestamp:
    return pd.Timestamp(year=month_int // 100, month=month_int % 100, day=1)


def _base_layout(fig: go.Figure, **kw) -> go.Figure:
    kw.setdefault("margin", dict(l=10, r=10, t=30, b=10))
    fig.update_layout(**kw)
    return fig


# ---------------------------------------------------------------------------
# Page 1: Overview
# ---------------------------------------------------------------------------


def page_overview(data: dict, payload: dict):
    st.title("NHS Scotland A&E Compliance Forecasting")
    st.caption(
        "1-month-ahead site-level forecast of 4-hour compliance %. "
        "Real Public Health Scotland open data. Candidate A = gradient-boosted tree "
        "+ persistence ensemble."
    )

    m = payload["candidate_a_holdout_metrics"]
    bm = payload["baseline_holdout_metrics"]
    improvement = payload["improvement_vs_persistence_pp"]
    ci = payload["candidate_a_mae_95ci"]
    imp_ci = payload.get("improvement_95ci_pp")
    dir_ca = m["directional_accuracy"] * 100
    dir_seasonal = bm["seasonal_naive"]["directional_accuracy"] * 100

    st.markdown("### The result (honest)")
    st.markdown(
        "Candidate A **beats persistence on point estimate** but the improvement "
        "is **not statistically significant** on the 12-month holdout. Reported without hedging."
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card(
            "Candidate A - holdout MAE",
            f"{m['mae']:.2f} pp",
            f"95% CI [{ci[0]:.2f}, {ci[1]:.2f}]",
            NAVY,
        )
    with c2:
        kpi_card(
            "Persistence baseline", f"{bm['persistence']['mae']:.2f} pp", "the bar to beat", MUTED
        )
    with c3:
        kpi_card(
            "Improvement vs bar",
            f"+{improvement:.2f} pp",
            "point estimate; CI includes zero",
            ACCENT,
        )
    with c4:
        # Honest framing: directional accuracy is near chance and BELOW seasonal
        # naive, so it is shown neutrally, not as a success metric.
        kpi_card(
            "Directional accuracy",
            f"{dir_ca:.1f}%",
            f"near chance; below seasonal-naive ({dir_seasonal:.0f}%)",
            MUTED,
        )

    st.markdown("")
    wins = sum(1 for r in payload["by_month"] if r["mae_ca"] < r["mae_pers"])
    imp_ci_txt = f"**[{imp_ci[0]:+.3f}, {imp_ci[1]:+.3f}]**" if imp_ci else "including zero"
    with st.expander("Why this is a *qualified* positive - read before interpreting"):
        st.markdown(
            f"""
            - **Point-estimate improvement:** Candidate A beats persistence by **+{improvement:.2f} pp**
              on the holdout (wins {wins}/12 months).
            - **Statistical significance:** the paired-bootstrap 95% CI on the improvement is
              {imp_ci_txt} - it **includes zero**. We cannot rule out that the two are
              indistinguishable on a 12-month window.
            - **Directional skill is near chance:** {dir_ca:.1f}%, below the seasonal-naive
              baseline ({dir_seasonal:.0f}%). The model's advantage is level calibration, not direction.
            - **Failure mode:** the model smooths. It does not predict sharp one-month drops - and
              those are the highest-stakes months.

            See `docs/HOLDOUT_PHASE6.md` for the full evaluation.
            """
        )

    st.divider()
    st.markdown("### Holdout: monthly MAE")
    by_month = pd.DataFrame(payload["by_month"])
    by_month["date"] = by_month["target_month"].apply(month_to_date)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=by_month["date"],
            y=by_month["mae_ca"],
            mode="lines+markers",
            name="Candidate A",
            line=dict(color=NAVY, width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=by_month["date"],
            y=by_month["mae_pers"],
            mode="lines+markers",
            name="Persistence",
            line=dict(color=MUTED, width=2, dash="dash"),
        )
    )
    fig.add_annotation(
        x=by_month["date"].iloc[-1],
        y=by_month["mae_ca"].iloc[-1],
        text="lines track closely: improvement CI includes zero",
        showarrow=True,
        arrowhead=2,
        ax=-40,
        ay=-40,
        font=dict(size=11, color=MUTED),
    )
    _base_layout(
        fig,
        xaxis_title="Holdout month",
        yaxis_title="MAE (pp)",
        height=350,
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### What this dashboard shows (and doesn't)")
    st.markdown(
        """
        **Shows:** the real artifacts the project produced - the cleaned panel, the temporal split,
        the holdout forecast-vs-actual, the baseline comparison, and the frozen model config.

        **Does not show:** patient-level data, intra-month nowcasting, causal intervention effects,
        or any KPI the underlying aggregate data cannot support. See `docs/REVIEW_HANDOFF.md` for
        the full list of explicit non-claims.
        """
    )


# ---------------------------------------------------------------------------
# Page 2: The data
# ---------------------------------------------------------------------------


def page_data(data: dict, payload: dict):
    st.title("The data")
    s = data["panel_summary"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Site-months", f"{s['rows']:,}", "Type-1 EDs only", NAVY)
    with c2:
        kpi_card("Sites", f"{s['sites']}", "Type-1 major A&E", NAVY)
    with c3:
        kpi_card("Months", f"{s['months']}", f"{s['month_min']} -> {s['month_max']}", NAVY)
    with c4:
        kpi_card(
            "Compliance range",
            f"{s['compliance_min']:.0f}-{s['compliance_max']:.0f}%",
            f"median {s['compliance_median']:.1f}%",
            ACCENT,
        )

    st.markdown("### The structural break")
    st.markdown(
        "Scotland A&E 4-hour compliance has fallen for 19 years and is **still declining**. "
        "This is the dominant feature of the data and the dominant source of forecast error."
    )
    annual = pd.DataFrame(data["annual_median"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=annual["year"],
            y=annual["median_compliance"],
            mode="lines+markers",
            name="Median compliance",
            line=dict(color=ACCENT, width=3),
        )
    )
    fig.add_hline(y=95, line_dash="dot", line_color=MUTED, annotation_text="95% standard")
    fig.add_annotation(
        x=2022.5,
        y=float(annual[annual["year"] >= 2023]["median_compliance"].max()),
        text="2022->2023 break",
        showarrow=True,
        arrowhead=2,
        ax=40,
        ay=-30,
        font=dict(size=11, color=ACCENT),
    )
    _base_layout(fig, xaxis_title="Year", yaxis_title="Median 4-hour compliance (%)", height=380)
    st.plotly_chart(fig, use_container_width=True)

    def med(lo, hi):
        sub = annual[(annual["year"] >= lo) & (annual["year"] <= hi)]["median_compliance"]
        return sub.median() if len(sub) else float("nan")

    st.markdown(
        f"""
        - **2007-2017:** median ~{med(2007, 2017):.0f}% (system near standard)
        - **2018-2019:** median ~{med(2018, 2019):.0f}%
        - **2020-2022 (COVID):** median ~{med(2020, 2022):.0f}%
        - **2023-2026:** median ~{med(2023, 2026):.0f}% - **no recovery, still falling**

        The break is **2022->2023**, not 2020->2022. The model must forecast through it.
        """
    )
    st.markdown("### Panel preview")
    st.dataframe(pd.DataFrame(data["panel_preview"]), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 3: The split
# ---------------------------------------------------------------------------


def page_split(data: dict, payload: dict):
    st.title("The split")
    st.markdown(
        "Chronological (temporal) holdout - all sites in every partition, partitions differ only by "
        "time. This is the only defensible strategy for a forward-looking forecast on a time series."
    )
    colors = {"train": NAVY, "validation": "#8d99ae", "holdout": ACCENT}
    cols = st.columns(3)
    for col, part in zip(cols, data["split_summary"]):
        with col:
            kpi_card(
                f"{part['partition'].title()}  [{part['start_month']}-{part['end_month']}]",
                f"{part['n_rows']:,} rows",
                f"{part['n_sites']} sites · median {part['compliance_median']:.1f}%",
                colors.get(part["partition"], NAVY),
            )

    st.markdown("### Compliance distribution by partition")
    st.markdown(
        "The gap between train (median ~89%) and holdout (median ~67%) is the structural break made "
        "concrete. The model must extrapolate, not interpolate."
    )
    fig = go.Figure()
    for part in data["split_summary"]:
        name = part["partition"]
        fig.add_trace(
            go.Box(
                y=data["split_box"][name],
                name=name.title(),
                marker_color=colors.get(name, NAVY),
                boxpoints=False,
            )
        )
    _base_layout(fig, yaxis_title="4-hour compliance (%)", height=380, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Leakage controls")
    st.markdown(
        """
        | ID | Control | Status |
        |---|---|---|
        | L1 | No target column or its count-components in features | enforced by test |
        | L2 | All lags <= month t; rolling windows exclude current month | enforced by test |
        | L3 | Chronological split, no key overlap | enforced by test |
        | L5 | Holdout scored exactly once | enforced procedurally |

        See `docs/SPLIT_DESIGN.md` and `tests/`.
        """
    )


# ---------------------------------------------------------------------------
# Page 4: Forecast
# ---------------------------------------------------------------------------


def page_forecast(data: dict, payload: dict):
    st.title("Forecast: Candidate A vs persistence")
    hf = pd.DataFrame(data["holdout_forecast"])
    if hf.empty:
        st.info("No holdout forecast in the artifact. Run `scripts/build_dashboard_data.py`.")
        return
    hf["date"] = hf["month"].apply(month_to_date)
    m = payload["candidate_a_holdout_metrics"]
    bm = payload["baseline_holdout_metrics"]["persistence"]

    c1, c2 = st.columns(2)
    with c1:
        kpi_card(
            "Candidate A - holdout MAE",
            f"{m['mae']:.2f} pp",
            f"bias {m['mean_error']:+.2f} pp · dir acc {m['directional_accuracy'] * 100:.1f}% (near chance)",
            NAVY,
        )
    with c2:
        kpi_card(
            "Persistence - holdout MAE",
            f"{bm['mae']:.2f} pp",
            f"bias {bm['mean_error']:+.2f} pp · always predicts 'no change'",
            MUTED,
        )

    st.markdown("### Predicted vs actual (holdout)")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hf["actual"],
            y=hf["pred_ca"],
            mode="markers",
            name="Candidate A",
            marker=dict(color=NAVY, size=6, opacity=0.5),
        )
    )
    lims = [float(hf["actual"].min()), float(hf["actual"].max())]
    fig.add_trace(
        go.Scatter(
            x=lims,
            y=lims,
            mode="lines",
            name="perfect",
            line=dict(color=ACCENT, dash="dash", width=1.5),
        )
    )
    fig.add_annotation(
        x=lims[0] + 3,
        y=lims[0] + 12,
        text="model smooths: predictions sit above actual on sharp drops",
        showarrow=False,
        font=dict(size=11, color=MUTED),
        xanchor="left",
    )
    _base_layout(fig, xaxis_title="Actual compliance (t+1)", yaxis_title="Predicted", height=420)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### By site (select to inspect)")
    site = st.selectbox("Site", sorted(hf["site"].unique()), index=0, label_visibility="collapsed")
    sd = hf[hf["site"] == site].sort_values("date")
    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(
            x=sd["date"],
            y=sd["actual"],
            mode="lines+markers",
            name="Actual",
            line=dict(color="#000", width=2.5),
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=sd["date"],
            y=sd["pred_ca"],
            mode="lines+markers",
            name="Candidate A",
            line=dict(color=NAVY, width=2),
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=sd["date"],
            y=sd["pred_pers"],
            mode="lines+markers",
            name="Persistence",
            line=dict(color=MUTED, width=2, dash="dash"),
        )
    )
    _base_layout(
        fig2,
        xaxis_title="Month",
        yaxis_title="Compliance (%)",
        height=380,
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### Worst errors (the model's failure mode)")
    st.markdown(
        "The largest errors are **sharp one-month drops** neither model anticipates - "
        "exactly the high-stakes months."
    )
    hf["abs_err_ca"] = (hf["pred_ca"] - hf["actual"]).abs()
    worst = (
        hf.nlargest(10, "abs_err_ca")[
            ["site", "month", "actual", "pred_ca", "pred_pers", "abs_err_ca"]
        ]
        .round(2)
        .rename(
            columns={
                "site": "Site",
                "month": "Month",
                "actual": "Actual",
                "pred_ca": "Candidate A",
                "pred_pers": "Persistence",
                "abs_err_ca": "|error|",
            }
        )
    )
    st.dataframe(worst, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 5: Model
# ---------------------------------------------------------------------------


def page_model(data: dict, payload: dict):
    st.title("Model")
    cfg = data["frozen_config"]
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("Model family", "Tree + persistence", "ensemble", NAVY)
    with c2:
        w = cfg["ensemble_weight_ca"]
        kpi_card("Ensemble weight", f"{w}", f"{w}·tree + {1 - w:.1f}·persistence", NAVY)
    with c3:
        kpi_card(
            "Features",
            f"{len(data['feature_importance'])}",
            "permutation importance on validation",
            NAVY,
        )

    st.markdown(
        "**Hyperparameters** (selected on validation, then frozen and loaded - not re-searched)"
    )
    hp = st.columns(5)
    for col, k in zip(
        hp, ["max_depth", "learning_rate", "max_iter", "l2_regularization", "min_samples_leaf"]
    ):
        col.metric(k, str(cfg[k]))

    st.markdown("### Feature importance (permutation, on validation)")
    st.markdown(
        "`f_compliance_lag1` dominates - the model leans on persistence, which is *why* the "
        "ensemble formalizes that relationship rather than fighting it."
    )
    fi = pd.DataFrame(data["feature_importance"]).head(12).iloc[::-1]
    bar_colors = [ACCENT if i == len(fi) - 1 else NAVY for i in range(len(fi))]
    fig = go.Figure(
        go.Bar(x=fi["importance_mean"], y=fi["feature"], orientation="h", marker_color=bar_colors)
    )
    _base_layout(
        fig,
        xaxis_title="delta MAE when shuffled (pp)",
        height=450,
        margin=dict(l=180, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Limitations (explicit)")
    for lim in payload["limitations"]:
        st.markdown(f"- {lim}")
    st.info(
        "**Recommendation** (`docs/HOLDOUT_PHASE6.md`): treat Candidate A as a *complement* to "
        "persistence, not a replacement - show both forecasts plus the directional flag. "
        "Re-evaluate on a 24+ month holdout to tighten the CI."
    )


# ---------------------------------------------------------------------------
# Nav + robust missing-artifact state
# ---------------------------------------------------------------------------

PAGES = {
    "Overview": page_overview,
    "The data": page_data,
    "The split": page_split,
    "Forecast": page_forecast,
    "Model": page_model,
}

st.sidebar.title("NHS Scotland A&E")
st.sidebar.caption("4-hour compliance forecasting")

data = load_json("dashboard_data.json")
payload = load_json("holdout_evaluation.json")

if data is None or payload is None:
    st.error(
        "Dashboard artifacts are missing or unreadable.\n\n"
        "Expected `reports/dashboard_data.json` and `reports/holdout_evaluation.json`.\n\n"
        "Regenerate them (requires the dataset via `scripts/fetch_data.py`):\n"
        "```\nPYTHONPATH=src python pipeline/score_holdout.py\n"
        "python scripts/build_dashboard_data.py\n```"
    )
    st.stop()

choice = st.sidebar.radio("Page", list(PAGES.keys()), label_visibility="collapsed")
st.sidebar.divider()
_imp = payload["improvement_vs_persistence_pp"]
st.sidebar.markdown(
    "**Status:** model complete · holdout scored once\n\n"
    f"**Bar:** persistence MAE {payload['baseline_holdout_metrics']['persistence']['mae']:.2f} pp\n\n"
    f"**Result:** +{_imp:.2f} pp (CI includes zero)"
)
PAGES[choice](data, payload)
