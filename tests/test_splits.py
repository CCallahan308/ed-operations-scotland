"""Tests for Phase 3 split and leakage invariants."""

from __future__ import annotations

import pandas as pd
import pytest

from ed_ops import splits
from ed_ops.config import RANDOM_SEED, RAW_DIR

requires_full_data = pytest.mark.skipif(
    not (RAW_DIR / "nhs_scotland_ae_activity_monthly.csv").exists(),
    reason="Full PHS dataset absent -- run `python scripts/fetch_data.py` (see README Quickstart).",
)
pytestmark = requires_full_data


@pytest.fixture(scope="module")
def split():
    return splits.build_temporal_split()


class TestSplitStructure:
    def test_three_partitions(self, split):
        assert split.train.name == "train"
        assert split.validation.name == "validation"
        assert split.holdout.name == "holdout"

    def test_seed_recorded(self, split):
        assert split.seed == RANDOM_SEED

    def test_all_partitions_nonempty(self, split):
        for part in (split.train, split.validation, split.holdout):
            assert len(part.df) > 0
            assert part.df["TreatmentLocation"].nunique() > 0

    def test_holdout_is_most_recent(self, split):
        """Holdout must be the most recent period (decision-relevant)."""
        assert split.holdout.start_month > split.validation.start_month
        assert split.holdout.end_month >= split.validation.end_month

    def test_partition_sizes_reasonable(self, split):
        """Holdout should be the smallest; train the largest."""
        sizes = {
            "train": len(split.train.df),
            "val": len(split.validation.df),
            "holdout": len(split.holdout.df),
        }
        assert sizes["train"] > sizes["val"] >= sizes["holdout"], sizes


class TestLeakageInvariants:
    """L3: no time leakage across partitions."""

    def test_chronological_ordering(self, split):
        """train.max < val.min <= val.max < holdout.min (all YYYYMM)."""
        assert split.train.end_month < split.validation.start_month
        assert split.validation.end_month < split.holdout.start_month

    def test_no_partition_overlap(self, split):
        """No (site, month) in more than one partition."""
        from ed_ops.splits import _assert_no_overlap

        _assert_no_overlap(split)  # raises on violation

    def test_no_month_in_two_partitions(self, split):
        """A given calendar month must belong to exactly one partition."""
        for part in (split.train, split.validation, split.holdout):
            months = set(part.df["Month"].astype(int).unique())
            for other in (split.train, split.validation, split.holdout):
                if other is part:
                    continue
                other_months = set(other.df["Month"].astype(int).unique())
                overlap = months & other_months
                assert not overlap, f"Month overlap between {part.name} and {other.name}: {overlap}"

    def test_holdout_months_all_after_train(self, split):
        """Every holdout month strictly greater than every train month."""
        train_max = split.train.df["Month"].astype(int).max()
        holdout_min = split.holdout.df["Month"].astype(int).min()
        assert holdout_min > train_max

    def test_holdout_sites_appear_in_train(self, split):
        """We only forecast sites we have trained on. A novel site in holdout
        would be an out-of-extension generalization claim we aren't making."""
        train_sites = set(split.train.df["TreatmentLocation"].unique())
        holdout_sites = set(split.holdout.df["TreatmentLocation"].unique())
        novel = holdout_sites - train_sites
        assert not novel, f"Holdout sites not in train: {novel}"


class TestLeakageChecks:
    def test_check_leakage_invariants_all_pass(self, split):
        results = splits.check_leakage_invariants(split)
        for key in ("L3a_chronological_ordering", "L3b_no_partition_overlap"):
            assert results[key] == "PASS", f"{key}: {results[key]}"
        # L3c may warn if a site closed before holdout; that's acceptable
        assert (
            "WARN" not in results["L3c_holdout_sites_all_in_train"]
            or "absent" in results["L3c_holdout_sites_all_in_train"]
        )


class TestManifest:
    def test_manifest_covers_every_panel_row(self, split):
        """Every panel row is labeled. Rows outside train/val/holdout windows
        are labeled 'pre_split' (the pre-2018 core-only history held aside)."""
        manifest = splits.build_split_manifest(split)
        panel_rows = len(split.panel)
        assert len(manifest) == panel_rows
        # Every panel (site, month) is labeled with a valid partition name
        valid = {"train", "validation", "holdout", "pre_split"}
        assert set(manifest["partition"].unique()).issubset(valid)
        # The split partitions (train/val/holdout) must cover 2018+ only
        split_rows = manifest[manifest["partition"] != "pre_split"]
        assert split_rows["Month"].astype(int).min() >= 201801
        # Pre-split rows must all be pre-2018
        pre = manifest[manifest["partition"] == "pre_split"]
        if len(pre) > 0:
            assert pre["Month"].astype(int).max() < 201801

    def test_manifest_deterministic(self, split):
        """Building the manifest twice yields identical output."""
        m1 = splits.build_split_manifest(split)
        m2 = splits.build_split_manifest(split)
        pd.testing.assert_frame_equal(m1, m2)


class TestRegressionGuards:
    """Pin the documented split-window decisions so they don't drift silently."""

    def test_default_windows_match_D015(self, split):
        """D015 split: train 2018-01..2023-12, val 2024-01..2025-05, holdout 2025-06..2026-05."""
        assert split.windows["train"] == (201801, 202312)
        assert split.windows["validation"] == (202401, 202505)
        assert split.windows["holdout"] == (202506, 202605)

    def test_holdout_is_12_months(self, split):
        """D015: holdout is exactly 12 months (2025-06 .. 2026-05)."""
        months = sorted(split.holdout.df["Month"].astype(int).unique())
        assert len(months) == 12
