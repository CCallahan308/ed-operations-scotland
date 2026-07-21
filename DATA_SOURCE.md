# Data Source: NHS Scotland Monthly A&E Activity and Waiting Times

> **Status:** Verified and downloaded 2026-07-21. Schema below is read **directly from the real CSV header**, not inferred.

## Identity

| Field | Value |
|---|---|
| Dataset | Monthly A&E Activity and Waiting Times |
| Publisher | Public Health Scotland (PHS) |
| Portal page | <https://www.opendata.nhs.scot/dataset/monthly-accident-and-emergency-activity-and-waiting-times> |
| Dataset ID | `997acaa5-afe0-49d9-b333-dcf84584603d` |
| Main resource ID | `37ba17b1-c323-492c-87d5-e986aae9ab59` |
| License | UK Open Government Licence (OGL) v3.0 |
| Frequency | Monthly (published ~2 months in arrears) |
| Local copy | `data/raw/nhs_scotland_ae_activity_monthly.csv` |

## Local copy provenance

| | |
|---|---|
| Retrieved (UTC) | 2026-07-21 |
| Rows (excl. header) | 39,583 |
| Months covered | 227 (2007-07 to 2026-05) |
| Unique treatment locations | 103 |
| Department types | Type 1, Type 3 |
| Attendance categories | All, New planned, Unplanned |
| SHA-256 | `746a19c75e41d99709a3d8b2cb3c56701ab569805ae6574c8b2941410e84f6b0` |
| Size | 4,785,719 bytes |

## Schema (verified from the actual CSV header)

26 columns. Quality-flag columns (`*QF`) carry PHS codes (e.g. `z` = not applicable) and must be parsed alongside their measure column.

| Group | Columns |
|---|---|
| Keys | `Month`, `Country`, `HBT` (NHS board), `TreatmentLocation` (site), `DepartmentType`, `AttendanceCategory` |
| Aggregate attendance (All episode types) | `NumberOfAttendancesAll`, `NumberWithin4HoursAll`, `NumberOver4HoursAll`, `PercentageWithin4HoursAll` |
| Episode-level attendance | `NumberOfAttendancesEpisode`, `NumberOfAttendancesEpisodeQF` |
| Episode 4-hour breach | `NumberWithin4HoursEpisode`, `NumberWithin4HoursEpisodeQF`, `NumberOver4HoursEpisode`, `NumberOver4HoursEpisodeQF`, `PercentageWithin4HoursEpisode`, `PercentageWithin4HoursEpisodeQF` |
| Episode 8-hour breach | `NumberOver8HoursEpisode`, `NumberOver8HoursEpisodeQF`, `PercentageOver8HoursEpisode`, `PercentageOver8HoursEpisodeQF` |
| Episode 12-hour breach | `NumberOver12HoursEpisode`, `NumberOver12HoursEpisodeQF`, `PercentageOver12HoursEpisode`, `PercentageOver12HoursEpisodeQF` |

**Notes**
- `Month` is `YYYYMM` integer (e.g. `200707`). No day component: this is site-month grain, not patient-level.
- `HBT` and `TreatmentLocation` are coded (e.g. `S08000015`, `A101H`); site-name lookup requires the PHS *Hospital Locations* reference dataset.
- Episode-level fields are the operationally meaningful ones (one ED visit = one episode). The "All" fields include episode-type combinations.
- 4h/8h/12h thresholds align with Scottish Government STP/STP8/STP12 standards.

## Why this dataset (pivot rationale)

The original Candidate A design assumed patient-level ED operational data. The Hong Kong HA "A&E Waiting Time" dataset was found to be only a near-real-time hospital-level snapshot (3 fields), which cannot support that design. NHS Scotland publishes rich **site-month** activity and breach statistics back to 2007, sufficient for:

- BI: compliance % vs the 4-hour standard, by site / board / month.
- Business analytics: breach-driver decomposition (Type 1 vs Type 3, unplanned vs planned), trend and seasonality.
- Data science: forecasting next-month site-level breach volume and 4-hour compliance %, with 19 years of history for honest temporal evaluation.

**Granularity caveat (logged as Phase 1 risk):** this is site-month, not patient-level. Individual-patient breach classification is **not** possible with this source; the modeling target must be an aggregate (site-month) target. This is recorded explicitly in the plan.

## Retrieval commands (reproduce the local copy)

```bash
# From project root:
curl -sS -L --max-time 180 \
  -o data/raw/nhs_scotland_ae_activity_monthly.csv \
  "https://www.opendata.nhs.scot/dataset/997acaa5-afe0-49d9-b333-dcf84584603d/resource/37ba17b1-c323-492c-87d5-e986aae9ab59/download/monthly_ae_activitywaitingtimes.csv"

# Verify integrity:
sha256sum data/raw/nhs_scotland_ae_activity_monthly.csv
# expected: 746a19c75e41d99709a3d8b2cb3c56701ab569805ae6574c8b2941410e84f6b0
```

## Companion resources (optional enrichment, Phase 1 decision)

Available on the same dataset page, not yet downloaded:

| Breakdown | Resource ID |
|---|---|
| Demographics (age/sex) | `6abbf8e4-e4e0-4a56-a7b9-f7c7b4171ff3` |
| When (day-of-week, hour-band) | `022c3b27-6a58-48dc-8038-8f1f93bb0e78` |
| Referral source | `235407ca-1676-472e-9e4d-6e7230934a95` |
| Multiple attendances | `0ca3b959-b758-4532-bb55-aa86da28679e` |

Whether to pull these depends on Phase 1's feature decisions.
