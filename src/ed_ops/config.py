"""Project configuration: deterministic paths and constants only.

Schema and feature definitions are intentionally NOT encoded here yet.
Those depend on the Phase 1 scope lock and Phase 3 split strategy, and
will be added only after the plan is updated. See
docs/EXECUTION_LOG.md (records the HK->Scotland pivot; the project
itself is NHS Scotland A&E data).
"""

from pathlib import Path

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXTERNAL_DIR = DATA_DIR / "external"
PROCESSED_DIR = DATA_DIR / "processed"

DOCS_DIR = PROJECT_ROOT / "docs"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

# Deterministic seed for all stochastic operations (recorded in plan file).
RANDOM_SEED = 20260721

# --- Source provenance (NHS Scotland A&E, verified 2026-07-21) ---
# Pivoted from Hong Kong HA snapshot feed (3 fields) to NHS Scotland
# monthly A&E activity (rich site x month grain with 4h/8h/12h breaches).
# See DATA_SOURCE.md and Decision D005 in the plan.
SOURCE_DATASET_NAME = "Monthly A&E Activity and Waiting Times"
SOURCE_PROVIDER = "Public Health Scotland (PHS)"
SOURCE_PORTAL_URL = "https://www.opendata.nhs.scot/dataset/monthly-accident-and-emergency-activity-and-waiting-times"
SOURCE_DATASET_ID = "997acaa5-afe0-49d9-b333-dcf84584603d"
SOURCE_MAIN_RESOURCE_ID = "37ba17b1-c323-492c-87d5-e986aae9ab59"
SOURCE_MAIN_CSV_FILENAME = "monthly_ae_activitywaitingtimes.csv"
SOURCE_MAIN_CSV_URL = (
    "https://www.opendata.nhs.scot/dataset/"
    f"{SOURCE_DATASET_ID}/resource/{SOURCE_MAIN_RESOURCE_ID}"
    f"/download/{SOURCE_MAIN_CSV_FILENAME}"
)
SOURCE_LICENSE = "UK Open Government Licence (OGL) v3.0"
SOURCE_LICENSE_URL = (
    "https://www.nationalarchives.gov.uk/doc/open-government-licence-association/version/3/"
)
SOURCE_LOCAL_PATH = RAW_DIR / "nhs_scotland_ae_activity_monthly.csv"

# Companion resources (all downloaded + SHA-verified 2026-07-21).
# NOTE: demographics/when/referral cover 2018-01..2026-04 only (100 months),
# narrower than the core activity file (2007-07..2026-05). Phase 3 split must
# account for the fact that enriched features begin in 2018.
# multiple_attendances is ANNUAL grain (YearEnd), not monthly -> descriptive use
# only; cannot be joined as a monthly feature into the modeling panel.
SOURCE_RESOURCE_DEMOGRAPHICS_ID = "6abbf8e4-e4e0-4a56-a7b9-f7c7b4171ff3"
SOURCE_RESOURCE_WHEN_ID = "022c3b27-6a58-48dc-8038-8f1f93bb0e78"
SOURCE_RESOURCE_REFERRAL_ID = "235407ca-1676-472e-9e4d-6e7230934a95"
SOURCE_RESOURCE_MULTIPLE_ATTENDANCES_ID = "0ca3b959-b758-4532-bb55-aa86da28679e"

SOURCE_DEMOGRAPHICS_PATH = RAW_DIR / "nhs_scotland_ae_demographics.csv"
SOURCE_WHEN_PATH = RAW_DIR / "nhs_scotland_ae_when.csv"
SOURCE_REFERRAL_PATH = RAW_DIR / "nhs_scotland_ae_referral.csv"
SOURCE_MULTIPLE_ATTENDANCES_PATH = RAW_DIR / "nhs_scotland_ae_multiple_attendances.csv"

# Provenance of local copies (captured at download, 2026-07-21).
# Each tuple: (sha256, row_count_excl_header, first_month, last_month)
SOURCE_PROVENANCE = {
    "activity_monthly": (
        "746a19c75e41d99709a3d8b2cb3c56701ab569805ae6574c8b2941410e84f6b0",
        39583,
        "200707",
        "202605",
        "monthly",
    ),
    "demographics": (
        "c10d31d4f27b10f7a54fbc344561b33069729fd540684a0aa599efcebeb8c063",
        136322,
        "201801",
        "202604",
        "monthly",
    ),
    "when": (
        "db06db76b7af9a4e5aefe9812781f8a34afc8cf2dfa0538682fe7733977d195f",
        615758,
        "201801",
        "202604",
        "monthly",
    ),
    "referral": (
        "7b1b18e7aea62a9a09863f5b9dddec3f932b3b64cd1eeafb4c3f3af75711ce5b",
        150547,
        "201801",
        "202604",
        "monthly",
    ),
    "multiple_attendances": (
        "f430baa0c9a46e74af227923449aad5105e1f92d4981a320dc45ba4ad00f3479",
        None,
        "YearEnd-based",
        "annual",
        "annual",  # annual grain, no month axis
    ),
}
# Back-compat aliases for the main file (used elsewhere in the codebase)
SOURCE_LOCAL_SHA256 = SOURCE_PROVENANCE["activity_monthly"][0]
SOURCE_LOCAL_ROW_COUNT = SOURCE_PROVENANCE["activity_monthly"][1]
SOURCE_LOCAL_MONTH_COUNT = 227
SOURCE_COVERAGE_FIRST = "200707"
SOURCE_COVERAGE_LAST = "202605"
SOURCE_RETRIEVAL_DATE_UTC = "2026-07-21"
