"""Tests for data-quality invariants and cleaning rules (Phase 2).

These tests enforce the documented invariants in src/ed_ops/data_quality.py.
They run against the real raw data in data/raw/.
"""

from __future__ import annotations

import pytest

from ed_ops import config
from ed_ops import data_quality as dq

# ---------------------------------------------------------------------------
# Raw-data integrity (Phase 0 evidence: SHA + row counts must hold)
# ---------------------------------------------------------------------------


class TestRawIntegrity:
    """Verify the raw files match their recorded provenance (SHA + row count)."""

    def test_activity_sha_matches_config(self):
        import hashlib

        path = config.RAW_DIR / "nhs_scotland_ae_activity_monthly.csv"
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        assert h == config.SOURCE_PROVENANCE["activity_monthly"][0]

    def test_activity_row_count_matches_config(self):
        df = dq.load_activity_raw()
        expected = config.SOURCE_PROVENANCE["activity_monthly"][1]
        assert len(df) == expected

    def test_activity_schema_matches_expected(self):
        df = dq.load_activity_raw()
        assert list(df.columns) == dq.EXPECTED_COLUMNS_ACTIVITY

    @pytest.mark.parametrize(
        "name,filename",
        [
            ("demographics", "nhs_scotland_ae_demographics.csv"),
            ("when", "nhs_scotland_ae_when.csv"),
            ("referral", "nhs_scotland_ae_referral.csv"),
            ("multiple_attendances", "nhs_scotland_ae_multiple_attendances.csv"),
        ],
    )
    def test_companion_sha_matches_config(self, name, filename):
        import hashlib

        path = config.RAW_DIR / filename
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        assert h == config.SOURCE_PROVENANCE[name][0], f"{filename} SHA mismatch"


# ---------------------------------------------------------------------------
# Documented finding invariants (regression tests for F001-F005)
# ---------------------------------------------------------------------------


class TestDocumentedFindings:
    """The cleaning rules exist because of specific findings. These tests
    guard against the findings silently changing (e.g. PHS fixes a bug and
    our quarantine becomes a no-op, or new duplicates appear)."""

    def test_episode_nulls_match_F001_count(self):
        """F001: 16894 episode-null rows, all QF='z'. If this changes the
        cleaning logic must be re-audited."""
        df = dq.load_activity_raw()
        nulls = df["NumberOfAttendancesEpisode"].isna()
        assert nulls.sum() == 16894, "F001 episode-null count changed; re-audit"
        # All nulls must carry QF='z'
        assert (df.loc[nulls, "NumberOfAttendancesEpisodeQF"] == "z").all()

    def test_duplicate_keys_match_F002(self):
        """F002: exactly 4 duplicate-key rows at G405H-201505, across 2 key
        combinations (the 'All' pair and the 'Unplanned' pair)."""
        df = dq.load_activity_raw()
        res = dq.check_duplicate_keys_activity(df)
        assert res["rows_in_duplicate_groups"] == 4
        assert res["duplicate_key_combinations"] == 2

    def test_invalid_counts_match_F003(self):
        """F003: W106H-202505 has within4 > total (2 rows: All + Unplanned)."""
        df = dq.load_activity_raw()
        res = dq.check_pct_bounds_activity(df)
        assert res["rows_invalid_counts_within_gt_total"] == 2

    def test_country_constant_F004(self):
        """F004: Country is constant."""
        df = dq.load_activity_raw()
        assert df["Country"].nunique() == 1


# ---------------------------------------------------------------------------
# Count identity (the core numeric invariant of the dataset)
# ---------------------------------------------------------------------------


class TestCountIdentity:
    def test_within_plus_over_equals_total_all_rows(self):
        """within4 + over4 == NumberOfAttendancesAll for every row.
        This must hold exactly; any failure is data corruption."""
        df = dq.load_activity_raw()
        res = dq.check_count_identity_activity(df)
        assert res["identity_failures"] == 0
        assert res["max_abs_diff"] == 0.0


# ---------------------------------------------------------------------------
# Quarantine dtype guard (W2 fix)
# ---------------------------------------------------------------------------


class TestQuarantineDtypeGuard:
    """REGRESSION GUARD (W2 fix): the quarantine matches Month as a STRING
    ('201505'). If a caller loads Month as int, the match silently fails and
    the bad rows leak into the panel. clean_activity_to_panel must raise."""

    def test_int_month_raises_typeerror(self):
        """Loading Month as int must raise, not silently skip quarantine."""
        df = dq.load_activity_raw().copy()
        df["Month"] = df["Month"].astype(int)
        with pytest.raises(TypeError, match="Month dtype must be string"):
            dq.clean_activity_to_panel(df)

    def test_string_month_quarantines_correctly(self):
        """Sanity: the normal string-Month path still quarantines G405H-201505."""
        df = dq.load_activity_raw()
        panel = dq.clean_activity_to_panel(df)
        # G405H-201505 must be absent (quarantined)
        assert not ((panel["TreatmentLocation"] == "G405H") & (panel["Month"] == "201505")).any()


# ---------------------------------------------------------------------------
# Cleaned panel invariants (the output the model will see)
# ---------------------------------------------------------------------------


class TestCleanedPanel:
    """The cleaned primary panel must satisfy its invariants or the model
    cannot trust it."""

    @pytest.fixture(scope="class")
    def panel(self):
        return dq.build_primary_panel()

    def test_no_nulls_in_required_columns(self, panel):
        required = [
            "Month",
            "HBT",
            "TreatmentLocation",
            "NumberOfAttendancesAll",
            "NumberWithin4HoursAll",
            "NumberOver4HoursAll",
            "compliance_pct",
        ]
        nulls = panel[required].isna().sum()
        assert (nulls == 0).all(), f"Nulls: {nulls[nulls > 0].to_dict()}"

    def test_unique_site_month_key(self, panel):
        assert not panel.duplicated(subset=["TreatmentLocation", "Month"]).any()

    def test_compliance_pct_in_valid_range(self, panel):
        p = panel["compliance_pct"]
        assert (p >= 0).all() and (p <= 100).all()
        # Sanity: no >100 artifacts survived the recompute
        assert (p <= 100).all()

    def test_count_identity_holds_in_panel(self, panel):
        s = panel["NumberWithin4HoursAll"] + panel["NumberOver4HoursAll"]
        assert (s == panel["NumberOfAttendancesAll"]).all()

    def test_quarantined_site_months_excluded(self, panel):
        for site, month in dq.QUARANTINED_SITE_MONTHS:
            assert not ((panel["TreatmentLocation"] == site) & (panel["Month"] == month)).any()

    def test_only_type1_all_category(self, panel):
        """Panel is Type 1 / AttendanceCategory='All' only (F001).
        Post-cleaning these columns are dropped, so we verify the row count
        matches the expected Type-1-All population."""
        raw = dq.load_activity_raw()
        expected = (
            (raw["DepartmentType"] == "Type 1")
            & (raw["AttendanceCategory"] == "All")
            & ~raw.apply(
                lambda r: (r["TreatmentLocation"], r["Month"]) in dq.QUARANTINED_SITE_MONTHS, axis=1
            )
        ).sum()
        assert len(panel) == expected

    def test_recomputed_pct_matches_count_ratio(self, panel):
        """The compliance_pct column must equal within4/total*100 exactly
        (the count-ratio rule from PROBLEM_FRAMING.md, never averaging %)."""
        expected = (panel["NumberWithin4HoursAll"] / panel["NumberOfAttendancesAll"] * 100).round(2)
        assert (panel["compliance_pct"] == expected).all()

    def test_expected_site_count(self, panel):
        """Type 1 sites: 35 (Phase 0/2 audit)."""
        assert panel["TreatmentLocation"].nunique() == 35

    def test_coverage_full_span(self, panel):
        """Type 1 sites collectively cover 2007-07 through 2026-05."""
        months = sorted(panel["Month"].astype(int).unique())
        assert months[0] == 200707
        assert months[-1] == 202605
