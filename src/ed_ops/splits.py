"""Phase 3: Split and experimental design.

Implements a chronological (temporal) split for the site-month forecasting
panel. All sites appear in every partition; partitions differ only by time
window. This is the only defensible strategy given:

  - The outcome (compliance_pct) is a time series per site.
  - The decision is forward-looking (forecast next month).
  - There is a strong, ongoing temporal trend (compliance falling ~20pp
    from 2018 to 2026, see docs/SPLIT_DESIGN.md).

Leakage controls (enforced by tests/test_splits.py):
  L1 no target column or its count-components in features
  L2 all feature lags/rollings use data <= month t only
  L3 chronological ordering: max(train month) < min(val month) < min(holdout month)
  L4 preprocessing/feature transforms fit on train only (Phase 4)
  L5 holdout never used for selection (Phase 6 single scoring)
  L6 external enrichment joined with as-of logic (Phase 4)
  L7 disaggregated series only as lagged features (Phase 4)

This module handles the partition construction and L3. L1/L2 are enforced in
the feature pipeline (Phase 4). L5 is enforced procedurally in Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ed_ops.config import RANDOM_SEED
from ed_ops.data_quality import build_primary_panel

# ---------------------------------------------------------------------------
# Split windows (see docs/SPLIT_DESIGN.md for justification)
# ---------------------------------------------------------------------------
# The default config below is the RECOMMENDED split (D015). It trains on the
# recent regime (post-COVID settlement) to match the current operational
# reality, reserving the most recent 12 months as a pristine holdout.
#
# IMPORTANT: an alternative TRAIN_LONG split (train 2007-2017, val 2018-2019,
# holdout 2020+) was considered and rejected because the pre-2020 regime
# (median compliance ~95%) is structurally different from the post-2022
# regime (median ~70%). A model trained on 2007-2017 would be trained on a
# world that no longer exists. See SPLIT_DESIGN.md.

DEFAULT_SPLIT_WINDOWS = {
    "train": (201801, 202312),  # 6 years: post-2018 enrichment era, includes COVID + recovery
    "validation": (202401, 202505),  # 17 months: most recent pre-holdout, current regime
    "holdout": (202506, 202605),  # 12 months: pristine, decision-relevant
}


@dataclass(frozen=True)
class Partition:
    name: str
    start_month: int  # YYYYMM inclusive
    end_month: int  # YYYYMM inclusive
    df: pd.DataFrame


@dataclass(frozen=True)
class Split:
    """A complete train/validation/holdout split.

    The partitions are views into the same panel; feature engineering in
    Phase 4 will operate on each independently with train-fit transforms.
    """

    train: Partition
    validation: Partition
    holdout: Partition
    panel: pd.DataFrame
    seed: int
    windows: dict

    def summary(self) -> str:
        lines = [f"Split (seed={self.seed})"]
        for part in (self.train, self.validation, self.holdout):
            lines.append(
                f"  {part.name:10s} [{part.start_month}-{part.end_month}] "
                f"rows={len(part.df):5d}  sites={part.df['TreatmentLocation'].nunique():2d}  "
                f"compliance median={part.df['compliance_pct'].median():.1f}"
            )
        return "\n".join(lines)


def build_temporal_split(
    windows: dict | None = None,
    panel: pd.DataFrame | None = None,
) -> Split:
    """Construct the chronological train/val/holdout split.

    Parameters
    ----------
    windows : dict, optional
        Mapping with keys 'train', 'validation', 'holdout', each a
        (start_month, end_month) tuple (YYYYMM inclusive). Defaults to
        DEFAULT_SPLIT_WINDOWS.
    panel : pd.DataFrame, optional
        Pre-built primary panel. Defaults to build_primary_panel().

    Returns
    -------
    Split
    """
    if windows is None:
        windows = DEFAULT_SPLIT_WINDOWS
    if panel is None:
        panel = build_primary_panel()

    p = panel.copy()
    p["m"] = p["Month"].astype(int)

    partitions = []
    for name in ("train", "validation", "holdout"):
        lo, hi = windows[name]
        mask = (p["m"] >= lo) & (p["m"] <= hi)
        sub = p.loc[mask].drop(columns=["m"]).reset_index(drop=True)
        partitions.append(Partition(name=name, start_month=lo, end_month=hi, df=sub))

    split = Split(
        train=partitions[0],
        validation=partitions[1],
        holdout=partitions[2],
        panel=p.drop(columns=["m"]).reset_index(drop=True),
        seed=RANDOM_SEED,
        windows=windows,
    )

    # Enforce the chronological-ordering invariant (L3) at construction time
    _assert_chronological(split)
    _assert_no_overlap(split)

    return split


# ---------------------------------------------------------------------------
# Invariant checks (L3: no time leakage)
# ---------------------------------------------------------------------------


def _assert_chronological(split: Split) -> None:
    """train.max_month < validation.min_month < holdout.min_month."""
    t_end = split.train.end_month
    v_start = split.validation.start_month
    v_end = split.validation.end_month
    h_start = split.holdout.start_month
    if not (t_end < v_start):
        raise ValueError(f"L3 violation: train end ({t_end}) >= validation start ({v_start})")
    if not (v_end < h_start):
        raise ValueError(f"L3 violation: validation end ({v_end}) >= holdout start ({h_start})")


def _assert_no_overlap(split: Split) -> None:
    """No (site, month) appears in more than one partition."""
    keys_seen = set()
    for part in (split.train, split.validation, split.holdout):
        for _, row in part.df[["TreatmentLocation", "Month"]].iterrows():
            k = (row["TreatmentLocation"], row["Month"])
            if k in keys_seen:
                raise ValueError(f"L3 violation: duplicate key {k} across partitions")
            keys_seen.add(k)


def check_leakage_invariants(split: Split) -> dict:
    """Return a dict of leakage-check results (all must pass for Phase 3 gate).

    L3 is enforced here. L1/L2 (feature-side) are enforced in Phase 4 once
    the feature matrix exists; this function checks what can be checked at
    the partition level.
    """
    results = {}
    # L3a: chronological ordering
    try:
        _assert_chronological(split)
        results["L3a_chronological_ordering"] = "PASS"
    except ValueError as e:
        results["L3a_chronological_ordering"] = f"FAIL: {e}"

    # L3b: no key overlap
    try:
        _assert_no_overlap(split)
        results["L3b_no_partition_overlap"] = "PASS"
    except ValueError as e:
        results["L3b_no_partition_overlap"] = f"FAIL: {e}"

    # L3c: every site in holdout also appears in train (we forecast known sites)
    train_sites = set(split.train.df["TreatmentLocation"].unique())
    holdout_sites = set(split.holdout.df["TreatmentLocation"].unique())
    novel_holdout_sites = holdout_sites - train_sites
    results["L3c_holdout_sites_all_in_train"] = (
        "PASS"
        if not novel_holdout_sites
        else f"WARN: {len(novel_holdout_sites)} holdout sites absent from train: "
        f"{sorted(novel_holdout_sites)[:5]}"
    )

    # Sanity: partition sizes
    results["partition_sizes"] = {
        "train": len(split.train.df),
        "validation": len(split.validation.df),
        "holdout": len(split.holdout.df),
    }

    return results


def build_split_manifest(split: Split) -> pd.DataFrame:
    """Return a manifest DataFrame: one row per (site, month) with its partition.

    Every row in split.panel is labeled. Rows outside the train/validation/
    holdout windows are labeled 'pre_split' (the pre-2018 core-only history
    that is held aside for an optional long-history baseline; see
    docs/SPLIT_DESIGN.md). This makes the manifest a complete provenance
    record: no panel row is silently dropped.

    Saved to data/processed/split_manifest.csv for reproducibility and audit.
    """
    rows = []
    labeled_keys: set[tuple[str, str]] = set()
    for part in (split.train, split.validation, split.holdout):
        for _, row in part.df[["TreatmentLocation", "Month"]].iterrows():
            k = (row["TreatmentLocation"], row["Month"])
            rows.append(
                {
                    "TreatmentLocation": row["TreatmentLocation"],
                    "Month": row["Month"],
                    "partition": part.name,
                }
            )
            labeled_keys.add(k)

    # Label any panel rows outside the split windows as pre_split
    for _, row in split.panel[["TreatmentLocation", "Month"]].iterrows():
        k = (row["TreatmentLocation"], row["Month"])
        if k not in labeled_keys:
            rows.append(
                {
                    "TreatmentLocation": row["TreatmentLocation"],
                    "Month": row["Month"],
                    "partition": "pre_split",
                }
            )
            labeled_keys.add(k)

    return pd.DataFrame(rows).sort_values(["TreatmentLocation", "Month"]).reset_index(drop=True)
