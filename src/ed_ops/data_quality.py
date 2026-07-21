"""Phase 2: Data integrity and cleaning for NHS Scotland A&E data.

All cleaning rules here are evidence-led: every condition, the number of rows
affected, the treatment, and the justification are documented in
docs/DATA_QUALITY.md and referenced from this module via the QUALITY_FINDINGS
dict. The module is importable and unit-tested (tests/test_data_quality.py).

Design rules (see docs/PROBLEM_FRAMING.md):
- Raw data is NEVER mutated. All cleaning produces a new DataFrame.
- Quality-flag (QF) columns are parsed but never silently dropped.
- The panel uses count-ratio re-aggregation (within4/total*100), never averages
  of percentages, to avoid size bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ed_ops.config import RAW_DIR

# ---------------------------------------------------------------------------
# Documented quality findings (Phase 2 audit, 2026-07-21)
# ---------------------------------------------------------------------------
# Each finding records: condition, count affected, treatment, justification.
# These are the single source of truth referenced by the cleaning functions.

QUALITY_FINDINGS: dict[str, dict] = {
    "F001_episode_nulls_type3": {
        "condition": "NumberOfAttendancesEpisode and all Episode-derived columns "
        "are null, with QF code 'z' (PHS: not applicable).",
        "affected": 16894,
        "population": "Predominantly Type 3 departments (16594 of 16894); "
        "remainder are Type 1 'All'/'Unplanned' rows at sites with no episode reporting.",
        "treatment": "Restrict primary modeling panel to Type 1 sites where Episode "
        "fields are populated. Episode grain is the operationally meaningful one.",
        "justification": "QF 'z' is a PHS convention meaning the field does not exist for "
        "that row, not that data is missing. Type 3 (minor injury units) do not "
        "report the 4h/8h/12h episode breakdown. The 4-hour standard bite is "
        "concentrated at Type 1 major EDs, which is the policy-relevant population.",
    },
    "F002_duplicate_keys_G405H_201505": {
        "condition": "Site G405H, Month 201505, Type 1 has duplicate key rows for "
        "both 'All' and 'Unplanned' categories, with inconsistent attendance "
        "values (4990 vs 137).",
        "affected": 4,
        "treatment": "Quarantine this site-month from the primary panel. Do NOT pick a row.",
        "justification": "Cannot determine which row is authoritative from the data alone. "
        "Picking one would be a fabrication. Excluding 1 site-month out of ~7900 "
        "Type-1 site-months is negligible coverage loss and preserves integrity.",
    },
    "F003_invalid_counts_W106H_202505": {
        "condition": "Site W106H, Month 202505, Type 3 reports within4=96 > total=69, "
        "over4=-27, PercentageWithin4HoursAll=139.1 (>100).",
        "affected": 2,
        "treatment": "Quarantine this site-month. Do NOT clip; clipping hides the inconsistency.",
        "justification": "Negative count and >100% percentage indicate a PHS publication "
        "error, not a bounded-percentage artifact. Quarantine is the only "
        "honest treatment without an authoritative source to reconcile against.",
    },
    "F004_country_constant": {
        "condition": "Country column is constant ('S92000003' = Scotland) across all rows.",
        "affected": 39583,
        "treatment": "Drop the Country column from the cleaned panel.",
        "justification": "A constant column carries no information for modeling or analysis.",
    },
    "F005_pct_over_100_artifacts": {
        "condition": "PercentageWithin4HoursAll exceeds 100 in a small number of rows "
        "where the underlying counts are valid (within4 <= total).",
        "affected": "0 after F003 quarantine; monitored.",
        "treatment": "For rows where counts reconcile (within4 <= total), recompute the "
        "percentage from counts rather than trusting the published value.",
        "justification": "Published percentages can carry rounding/aggregation artifacts. "
        "The count ratio is the ground truth; recomputing removes artifacts "
        "without discarding valid rows.",
    },
}


# ---------------------------------------------------------------------------
# Integrity checks (run on raw data; raise on violation)
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS_ACTIVITY = [
    "Month",
    "Country",
    "HBT",
    "TreatmentLocation",
    "DepartmentType",
    "AttendanceCategory",
    "NumberOfAttendancesAll",
    "NumberWithin4HoursAll",
    "NumberOver4HoursAll",
    "PercentageWithin4HoursAll",
    "NumberOfAttendancesEpisode",
    "NumberOfAttendancesEpisodeQF",
    "NumberWithin4HoursEpisode",
    "NumberWithin4HoursEpisodeQF",
    "NumberOver4HoursEpisode",
    "NumberOver4HoursEpisodeQF",
    "PercentageWithin4HoursEpisode",
    "PercentageWithin4HoursEpisodeQF",
    "NumberOver8HoursEpisode",
    "NumberOver8HoursEpisodeQF",
    "PercentageOver8HoursEpisode",
    "PercentageOver8HoursEpisodeQF",
    "NumberOver12HoursEpisode",
    "NumberOver12HoursEpisodeQF",
    "PercentageOver12HoursEpisode",
    "PercentageOver12HoursEpisodeQF",
]


@dataclass
class IntegrityReport:
    """Container for integrity-check results. Pass/fail is explicit."""

    file: str
    expected_rows: int | None
    actual_rows: int
    expected_sha: str
    actual_sha: str
    schema_ok: bool
    row_count_ok: bool
    sha_ok: bool
    checks: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.schema_ok and self.row_count_ok and self.sha_ok

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            f"[{status}] {self.file}",
            f"  rows: expected={self.expected_rows} actual={self.actual_rows} "
            f"-> {'ok' if self.row_count_ok else 'MISMATCH'}",
            f"  sha256: {'ok' if self.sha_ok else 'MISMATCH'} "
            f"(expected={self.expected_sha[:12]}.. actual={self.actual_sha[:12]}..)",
            f"  schema: {'ok' if self.schema_ok else 'MISMATCH'}",
        ]
        for name, result in self.checks.items():
            lines.append(f"  {name}: {result}")
        return "\n".join(lines)


def load_activity_raw() -> pd.DataFrame:
    """Load the raw activity CSV as-is (all strings, no cleaning)."""
    return pd.read_csv(RAW_DIR / "nhs_scotland_ae_activity_monthly.csv", dtype=str)


def check_count_identity_activity(df: pd.DataFrame) -> dict:
    """Verify within4 + over4 == NumberOfAttendancesAll on the 'All' columns.

    Per F005, the published percentage may carry artifacts but the counts must
    reconcile exactly. This is the core numeric invariant of the dataset.
    """
    cols = ["NumberOfAttendancesAll", "NumberWithin4HoursAll", "NumberOver4HoursAll"]
    nums = df[cols].apply(pd.to_numeric, errors="coerce")
    valid = nums.dropna()
    s = nums["NumberWithin4HoursAll"] + nums["NumberOver4HoursAll"]
    diff = (s - nums["NumberOfAttendancesAll"]).abs()
    failures = int((diff > 0).sum())
    return {
        "rows_checked": len(valid),
        "identity_failures": failures,
        "max_abs_diff": float(diff.max()) if len(diff) else 0.0,
    }


def check_duplicate_keys_activity(df: pd.DataFrame) -> dict:
    """Count rows in duplicate-key groups on the natural key.

    Key: (TreatmentLocation, Month, DepartmentType, AttendanceCategory).
    Known duplicates: F002 (G405H 201505, 4 rows). New duplicates would be a
    data-quality regression and must be investigated.
    """
    keys = ["TreatmentLocation", "Month", "DepartmentType", "AttendanceCategory"]
    dup_mask = df.duplicated(subset=keys, keep=False)
    dup_groups = df.loc[dup_mask, keys].drop_duplicates()
    return {
        "rows_in_duplicate_groups": int(dup_mask.sum()),
        "duplicate_key_combinations": int(len(dup_groups)),
        "known_duplicate_site_months": ["G405H-201505"],  # F002
    }


def check_pct_bounds_activity(df: pd.DataFrame) -> dict:
    """Check PercentageWithin4HoursAll bounds. Legal range is [0, 100].

    Values >100 with valid counts are F005 artifacts (recomputed in cleaning).
    Values >100 with invalid counts are F003 (quarantined).
    """
    pct = pd.to_numeric(df["PercentageWithin4HoursAll"], errors="coerce")
    within = pd.to_numeric(df["NumberWithin4HoursAll"], errors="coerce")
    total = pd.to_numeric(df["NumberOfAttendancesAll"], errors="coerce")
    over_100 = pct > 100
    # F003 signature: within > total
    invalid_counts = within > total
    return {
        "rows_pct_over_100": int(over_100.sum()),
        "rows_invalid_counts_within_gt_total": int(invalid_counts.sum()),
        "max_pct": float(pct.max()),
        "min_pct": float(pct.min()),
    }


# ---------------------------------------------------------------------------
# Cleaning: produces the primary modeling panel
# ---------------------------------------------------------------------------

# Site-months to quarantine (F002, F003). Tuple: (TreatmentLocation, Month).
QUARANTINED_SITE_MONTHS: set[tuple[str, str]] = {
    ("G405H", "201505"),  # F002: duplicate keys with inconsistent values
    ("W106H", "202505"),  # F003: invalid counts, pct=139.1
}


def clean_activity_to_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all documented cleaning rules and return the primary panel.

    The primary panel is: one row per (TreatmentLocation, Month) for Type 1
    departments, AttendanceCategory='All', with the 4-hour compliance percentage
    recomputed from counts (count-ratio rule, never averaging percentages).

    Steps (each maps to a QUALITY_FINDINGS entry):
    1. F004: drop constant Country column.
    2. F002/F003: quarantine the two known bad site-months.
    3. F001: filter to DepartmentType='Type 1' AND AttendanceCategory='All'
       (the population where Episode grain exists and the policy bite is real).
    4. F005: recompute pct from counts.
    5. Numeric coercion + final invariant checks.
    """
    out = df.copy()

    # Quarantine relies on Month being a string (QUARANTINED_SITE_MONTHS stores
    # '201505', not 201505). Guard against a future caller loading Month as int.
    if out["Month"].dtype != object:
        raise TypeError(
            f"Month dtype must be string (object) for quarantine matching; "
            f"got {out['Month'].dtype}. Load with dtype=str."
        )

    # F004: drop constant Country
    out = out.drop(columns=["Country"])

    # F002/F003: quarantine known bad site-months (vectorized tuple match).
    # Build a set of (site, month) tuples from the panel and intersect.
    panel_tuples = set(zip(out["TreatmentLocation"], out["Month"], strict=False))
    bad_tuples = panel_tuples & QUARANTINED_SITE_MONTHS
    bad_mask = out.apply(
        lambda r: (r["TreatmentLocation"], r["Month"]) in bad_tuples,
        axis=1,
    )
    quarantined = int(bad_mask.sum())
    out = out.loc[~bad_mask].copy()

    # F001: restrict to Type 1 + AttendanceCategory='All'
    out = out[(out["DepartmentType"] == "Type 1") & (out["AttendanceCategory"] == "All")].copy()

    # Numeric coercion of the count columns
    for c in ["NumberOfAttendancesAll", "NumberWithin4HoursAll", "NumberOver4HoursAll"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # F005: recompute percentage from counts (count-ratio rule)
    # Guard divide-by-zero: sites with 0 attendance shouldn't exist post-filter,
    # but defend anyway.
    denom = out["NumberOfAttendancesAll"].replace(0, pd.NA)
    out["compliance_pct"] = (out["NumberWithin4HoursAll"] / denom * 100).round(2)

    # Final invariants (assertions on the cleaned panel)
    _assert_clean_invariants(out, quarantined)

    # Drop the now-redundant percentage + category columns, keep keys + counts
    keep = [
        "Month",
        "HBT",
        "TreatmentLocation",
        "NumberOfAttendancesAll",
        "NumberWithin4HoursAll",
        "NumberOver4HoursAll",
        "compliance_pct",
    ]
    return out[keep].sort_values(["TreatmentLocation", "Month"]).reset_index(drop=True)


def _assert_clean_invariants(df: pd.DataFrame, quarantined: int) -> None:
    """Assert the cleaned panel satisfies its invariants. Raise on violation.

    The quarantine-row accounting is data-driven (computed from the raw frame
    the caller passed in to clean_activity_to_panel), not a hardcoded constant,
    so it tracks reality if PHS changes the underlying data.
    """
    # No nulls in key/numeric columns
    required = [
        "Month",
        "HBT",
        "TreatmentLocation",
        "NumberOfAttendancesAll",
        "NumberWithin4HoursAll",
        "NumberOver4HoursAll",
    ]
    null_counts = df[required].isna().sum()
    if (null_counts > 0).any():
        raise ValueError(f"Nulls in cleaned panel: {null_counts[null_counts > 0].to_dict()}")

    # Count identity holds exactly
    s = df["NumberWithin4HoursAll"] + df["NumberOver4HoursAll"]
    if not (s == df["NumberOfAttendancesAll"]).all():
        raise ValueError("Count identity within4+over4==total violated in cleaned panel")

    # Compliance in [0, 100] (no >100 artifacts post-recompute)
    if not ((df["compliance_pct"] >= 0) & (df["compliance_pct"] <= 100)).all():
        raise ValueError("compliance_pct out of [0,100] range in cleaned panel")

    # Unique key
    keys = ["TreatmentLocation", "Month"]
    if df.duplicated(subset=keys).any():
        raise ValueError("Duplicate (TreatmentLocation, Month) keys in cleaned panel")

    # Quarantine accounted for: every quarantined site-month should have had at
    # least one row removed. If zero rows matched a quarantine target, the
    # quarantine list has gone stale (PHS fixed the data) -> warn, don't fail.
    if quarantined == 0 and len(QUARANTINED_SITE_MONTHS) > 0:
        import warnings

        warnings.warn(
            "Quarantine removed 0 rows but QUARANTINED_SITE_MONTHS is non-empty. "
            "PHS may have fixed the flagged data; re-audit F002/F003.",
            stacklevel=2,
        )


def build_primary_panel() -> pd.DataFrame:
    """End-to-end: load raw activity, clean, return the Type-1 site-month panel."""
    raw = load_activity_raw()
    return clean_activity_to_panel(raw)
