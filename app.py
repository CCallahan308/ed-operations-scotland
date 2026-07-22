"""ED Operations Analytics — NHS Scotland A&E Compliance Forecasting.

Streamlit dashboard. Thin wiring: all data/math lives in src/ed_ops/ and the
frozen reports/. The app only loads real artifacts and renders them.

Pages (scoped to what genuinely exists — no fabricated KPIs):
  1. Overview      — the honest headline result + holdout CI
  2. The data      — the cleaned panel and the structural break
  3. The split      — train/validation/holdout windows
  4. Forecast      — Candidate A vs persistence on the holdout
  5. Model         — frozen config, feature importance, limitations
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ed_ops import features as features_mod  # noqa: E402
from ed_ops.data_quality import build_primary_panel  # noqa: E402
from ed_ops.evaluation import evaluate  # noqa: E402
from ed_ops.model import train_candidate_a  # noqa: E402
from ed_ops.splits import build_temporal_split  # noqa: E402

st.set_page_config(
    page_title="NHS Scotland A&E Compliance Forecasting",
    page_icon="🏥",
    layout="wide",
)

REPORTS = Path(__file__).parent / "reports"


# ---------------------------------------------------------------------------
# Cached data loaders (rebuilt from raw; deterministic)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Building primary panel from raw...")
def get_panel() -> pd.DataFrame:
    return build_primary_panel()


@st.cache_data(show_spinner="Building temporal split...")
def get_split():
    return build_temporal_split()


@st.cache_resource(show_spinner="Training Candidate A (frozen config)...")
def get_candidate():
    # train_candidate_a returns (candidate, search_df); we only need the candidate.
    candidate, _ = train_candidate_a()
    return candidate


@st.cache_data
def get_holdout_payload() -> dict:
    return json.loads((REPORTS / "holdout_evaluation.json").read_text())


@st.cache_data
def get_feature_importance() -> pd.DataFrame:
    return pd.read_csv(REPORTS / "candidate_a_feature_importance.csv")


# ---------------------------------------------------------------------------
# Shared viz helpers
# ---------------------------------------------------------------------------

NAVY = "#0b2545"
ACCENT = "#d62828"
MUTED = "#6c757d"
GOOD = "#2a9d8f"


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
    """202401 -> 2024-01-01."""
    return pd.Timestamp(year=month_int // 100, month=month_int % 100, day=1)


# ---------------------------------------------------------------------------
# Page 1: Overview
# ---------------------------------------------------------------------------


def page_overview():
    st.title("NHS Scotland A&E Compliance Forecasting")
    st.caption(
        "1-month-ahead site-level forecast of 4-hour compliance %. "
        "Real Public Health Scotland open data. Candidate A = gradient-boosted tree "
        "+ persistence ensemble."
    )

    payload = get_holdout_payload()
    m = payload["candidate_a_holdout_metrics"]
    bm = payload["baseline_holdout_metrics"]

    st.markdown("### The result (honest)")
    st.markdown(
        "Candidate A **beats persistence on point estimate** but the improvement "
        "is **not statistically significant** on the 12-month holdout. Reported without hedging."
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card(
            "Candidate A — holdout MAE",
            f"{m['mae']:.2f} pp",
            f"95% CI [{payload['candidate_a_mae_95ci'][0]:.2f}, "
            f"{payload['candidate_a_mae_95ci'][1]:.2f}]",
            NAVY,
        )
    with c2:
        kpi_card(
            "Persistence baseline", f"{bm['persistence']['mae']:.2f} pp", "the bar to beat", MUTED
        )
    with c3:
        improvement = payload["improvement_vs_persistence_pp"]
        kpi_card(
            "Improvement vs bar",
            f"+{improvement:.2f} pp",
            "point estimate; CI includes zero",
            ACCENT,
        )
    with c4:
        kpi_card(
            "Directional accuracy",
            f"{m['directional_accuracy']:.0%}",
            "vs persistence's structural ~0%",
            GOOD,
        )

    st.markdown("")
    with st.expander("⚠️ Why this is a *qualified* positive — read before interpreting"):
        st.markdown(
            f"""
            - **Point-estimate improvement:** Candidate A beats persistence by **+{improvement:.2f} pp**
              on the holdout (wins {payload["by_month"] and sum(1 for r in payload["by_month"] if r["mae_ca"] < r["mae_pers"])}/12 months).
            - **Statistical significance:** the paired-bootstrap 95% CI on the improvement is
              **[{payload["improvement_95ci_pp"][0]:+.3f}, {payload["improvement_95ci_pp"][1]:+.3f}]** — it **includes zero**. We cannot rule out that the two are
              indistinguishable on a 12-month window.
            - **Structural break:** Scotland A&E compliance has fallen from ~97% (2007) to ~67% (2026)
              and is still declining. The model is evaluated on its ability to forecast *through* this
              regime change — the honest problem, but a hard one. Candidate A's bias grew from +0.14 pp
              (validation) to +0.66 pp (holdout) as the regime kept drifting.
            - **Failure mode:** the model smooths. It does not predict sharp one-month drops — and
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
    fig.update_layout(
        xaxis_title="Holdout month",
        yaxis_title="MAE (pp)",
        height=350,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### What this dashboard shows (and doesn't)")
    st.markdown(
        """
        **Shows:** the real artifacts the project produced — the cleaned panel, the temporal split,
        the holdout forecast-vs-actual, the baseline comparison, and the frozen model config.

        **Does not show:** patient-level data, intra-month nowcasting, causal intervention effects,
        or any KPI the underlying aggregate data cannot support. See `docs/REVIEW_HANDOFF.md` §5
        for the full list of explicit non-claims.
        """
    )


# ---------------------------------------------------------------------------
# Page 2: The data
# ---------------------------------------------------------------------------


def page_data():
    st.title("The data")
    panel = get_panel()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Site-months", f"{len(panel):,}", "Type-1 EDs only", NAVY)
    with c2:
        kpi_card("Sites", f"{panel['TreatmentLocation'].nunique()}", "Type-1 major A&E", NAVY)
    with c3:
        kpi_card(
            "Months",
            f"{panel['Month'].astype(int).nunique()}",
            f"{panel['Month'].astype(int).min()} → {panel['Month'].astype(int).max()}",
            NAVY,
        )
    with c4:
        kpi_card(
            "Compliance range",
            f"{panel['compliance_pct'].min():.0f}–{panel['compliance_pct'].max():.0f}%",
            f"median {panel['compliance_pct'].median():.1f}%",
            ACCENT,
        )

    st.markdown("### The structural break")
    st.markdown(
        "Scotland A&E 4-hour compliance has fallen monotonically for 19 years and is **still declining**. "
        "This is the dominant feature of the data and the dominant source of forecast error."
    )

    # Annual median compliance trend
    p = panel.copy()
    p["Month"] = p["Month"].astype(int)
    p["year"] = p["Month"] // 100
    annual = p.groupby("year")["compliance_pct"].median().reset_index()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=annual["year"],
            y=annual["compliance_pct"],
            mode="lines+markers",
            name="Median compliance",
            line=dict(color=ACCENT, width=3),
        )
    )
    fig.add_hline(y=95, line_dash="dot", line_color=MUTED, annotation_text="95% standard")
    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Median 4-hour compliance (%)",
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown(
        f"""
        - **2007–2017:** median ~{annual[annual["year"] <= 2017]["compliance_pct"].median():.0f}% (system near standard)
        - **2018–2019:** median ~{annual[(annual["year"] >= 2018) & (annual["year"] <= 2019)]["compliance_pct"].median():.0f}%
        - **2020–2022 (COVID):** median ~{annual[(annual["year"] >= 2020) & (annual["year"] <= 2022)]["compliance_pct"].median():.0f}%
        - **2023–2026:** median ~{annual[annual["year"] >= 2023]["compliance_pct"].median():.0f}% — **no recovery, still falling**

        The break is **2022→2023**, not 2020→2022. The model must forecast through this regime change.
        """
    )

    st.markdown("### Panel preview")
    st.dataframe(panel.head(20), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 3: The split
# ---------------------------------------------------------------------------


def page_split():
    st.title("The split")
    split = get_split()

    st.markdown(
        "Chronological (temporal) holdout — all sites in every partition, partitions differ only by "
        "time. This is the only defensible strategy for a forward-looking forecast on a time series."
    )

    parts = [
        ("Train", split.train, NAVY),
        ("Validation", split.validation, "#8d99ae"),
        ("Holdout", split.holdout, ACCENT),
    ]

    c1, c2, c3 = st.columns(3)
    for col, (name, part, color) in zip([c1, c2, c3], parts):
        with col:
            kpi_card(
                f"{name}  [{part.start_month}–{part.end_month}]",
                f"{len(part.df):,} rows",
                f"{part.df['TreatmentLocation'].nunique()} sites · "
                f"median {part.df['compliance_pct'].median():.1f}%",
                color,
            )

    st.markdown("### Compliance distribution by partition")
    st.markdown(
        "The ~22pp gap between train (median 89.3%) and holdout (median ~67%) is the structural "
        "break made concrete. The model must extrapolate, not interpolate."
    )

    fig = go.Figure()
    for name, part, color in parts:
        fig.add_trace(
            go.Box(y=part.df["compliance_pct"], name=name, marker_color=color, boxpoints=False)
        )
    fig.update_layout(
        yaxis_title="4-hour compliance (%)",
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Leakage controls")
    st.markdown(
        """
        | ID | Control | Status |
        |---|---|---|
        | L1 | No target column or its count-components in features | ✅ enforced by test |
        | L2 | All lags ≤ month t; rolling windows exclude current month | ✅ enforced by test |
        | L3 | Chronological split, no key overlap | ✅ enforced by test |
        | L5 | Holdout scored exactly once | ✅ enforced procedurally |

        88 invariant tests guard these. See `docs/SPLIT_DESIGN.md`.
        """
    )


# ---------------------------------------------------------------------------
# Page 4: Forecast
# ---------------------------------------------------------------------------


def page_forecast():
    st.title("Forecast: Candidate A vs persistence")
    candidate = get_candidate()
    split = get_split()

    ff = features_mod.FeatureBuilder().build()
    lo, hi = split.windows["holdout"]
    holdout = ff[(ff["target_month"] >= lo) & (ff["target_month"] <= hi)].copy()
    holdout["pred_ca"] = candidate.predict(holdout)
    holdout["pred_pers"] = holdout["prior_compliance"]
    holdout["date"] = holdout["target_month"].apply(month_to_date)

    m_ca = evaluate(holdout, pred_col="pred_ca")
    m_pers = evaluate(holdout, pred_col="pred_pers")

    c1, c2 = st.columns(2)
    with c1:
        kpi_card(
            "Candidate A — holdout MAE",
            f"{m_ca.mae:.2f} pp",
            f"bias {m_ca.mean_error:+.2f} pp · dir acc {m_ca.directional_accuracy:.0%}",
            NAVY,
        )
    with c2:
        kpi_card(
            "Persistence — holdout MAE",
            f"{m_pers.mae:.2f} pp",
            f"bias {m_pers.mean_error:+.2f} pp · dir acc {m_pers.directional_accuracy:.0%}",
            MUTED,
        )

    st.markdown("### Predicted vs actual (holdout)")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=holdout["target_compliance"],
            y=holdout["pred_ca"],
            mode="markers",
            name="Candidate A",
            marker=dict(color=NAVY, size=6, opacity=0.5),
        )
    )
    lims = [holdout["target_compliance"].min(), holdout["target_compliance"].max()]
    fig.add_trace(
        go.Scatter(
            x=lims,
            y=lims,
            mode="lines",
            name="perfect",
            line=dict(color=ACCENT, dash="dash", width=1.5),
        )
    )
    fig.update_layout(
        xaxis_title="Actual compliance (t+1)",
        yaxis_title="Predicted",
        height=420,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### By site (select to inspect)")
    site = st.selectbox(
        "Site",
        sorted(holdout["TreatmentLocation"].unique()),
        index=0,
    )
    site_df = holdout[holdout["TreatmentLocation"] == site].sort_values("date")
    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(
            x=site_df["date"],
            y=site_df["target_compliance"],
            mode="lines+markers",
            name="Actual",
            line=dict(color="#000", width=2.5),
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=site_df["date"],
            y=site_df["pred_ca"],
            mode="lines+markers",
            name="Candidate A",
            line=dict(color=NAVY, width=2),
        )
    )
    fig2.add_trace(
        go.Scatter(
            x=site_df["date"],
            y=site_df["pred_pers"],
            mode="lines+markers",
            name="Persistence",
            line=dict(color=MUTED, width=2, dash="dash"),
        )
    )
    fig2.update_layout(
        xaxis_title="Month",
        yaxis_title="Compliance (%)",
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### Worst errors (the model's failure mode)")
    st.markdown(
        "The largest errors are **sharp one-month drops** neither model anticipates — "
        "exactly the high-stakes months."
    )
    holdout["abs_err_ca"] = (holdout["pred_ca"] - holdout["target_compliance"]).abs()
    worst = holdout.nlargest(10, "abs_err_ca")[
        [
            "TreatmentLocation",
            "target_month",
            "target_compliance",
            "pred_ca",
            "pred_pers",
            "abs_err_ca",
        ]
    ].rename(
        columns={
            "TreatmentLocation": "Site",
            "target_month": "Month",
            "target_compliance": "Actual",
            "pred_ca": "Candidate A",
            "pred_pers": "Persistence",
            "abs_err_ca": "|error|",
        }
    )
    st.dataframe(worst, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 5: Model
# ---------------------------------------------------------------------------


def page_model():
    st.title("Model")
    candidate = get_candidate()
    fi = get_feature_importance()
    payload = get_holdout_payload()

    st.markdown("### Frozen configuration")
    cfg = candidate.config
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("Model family", "Tree + persistence", "ensemble", NAVY)
    with c2:
        kpi_card(
            "Ensemble weight",
            f"{cfg.ensemble_weight_ca}",
            f"{cfg.ensemble_weight_ca}·tree + {1 - cfg.ensemble_weight_ca:.1f}·persistence",
            NAVY,
        )
    with c3:
        kpi_card(
            "Features",
            f"{len(candidate.feature_columns)}",
            f"fit on {candidate.fit_row_count:,} train rows",
            NAVY,
        )

    st.markdown("**Hyperparameters** (selected on validation only, D018)")
    hp_cols = st.columns(5)
    for col, (k, v) in zip(
        hp_cols,
        [
            ("max_depth", cfg.max_depth),
            ("learning_rate", cfg.learning_rate),
            ("max_iter", cfg.max_iter),
            ("l2_regularization", cfg.l2_regularization),
            ("min_samples_leaf", cfg.min_samples_leaf),
        ],
    ):
        col.metric(k, str(v))

    st.markdown("### Feature importance (permutation, on validation)")
    st.markdown(
        "`f_compliance_lag1` dominates — the model leans on persistence, which is *why* "
        "the ensemble formalizes that relationship rather than fighting it."
    )
    top = fi.head(12).iloc[::-1]  # reverse for horizontal bar
    fig = go.Figure()
    colors = [ACCENT if i == len(top) - 1 else NAVY for i in range(len(top))]
    fig.add_trace(
        go.Bar(x=top["importance_mean"], y=top["feature"], orientation="h", marker_color=colors)
    )
    fig.update_layout(
        xaxis_title="Δ MAE when shuffled (pp)",
        height=450,
        margin=dict(l=180, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Limitations (explicit)")
    for lim in payload["limitations"]:
        st.markdown(f"- {lim}")

    st.markdown("")
    st.info(
        "**Recommendation** (`docs/HOLDOUT_PHASE6.md`): treat Candidate A as a *complement* "
        "to persistence, not a replacement — show both forecasts plus the directional flag. "
        "Re-evaluate on a 24+ month holdout to tighten the CI."
    )


# ---------------------------------------------------------------------------
# Nav
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
choice = st.sidebar.radio("Page", list(PAGES.keys()), label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.markdown(
    "**Status:** model complete · holdout scored once\n\n"
    "**Bar:** persistence MAE 2.87 pp\n\n"
    "**Result:** +0.15 pp (CI includes zero)"
)
PAGES[choice]()
