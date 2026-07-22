-- Fact table: 4-hour A&E compliance at (site x month) grain.
-- Mirrors src/ed_ops/data_quality.build_primary_panel exactly:
--   * restrict to Type 1 departments, AttendanceCategory = 'All'
--   * exclude the two quarantined site-months (F002 G405H-201505, F003 W106H-202505)
--   * recompute compliance from COUNTS (within4 / total), never trusting the
--     published percentage and never averaging percentages downstream.
-- Input relation `raw_activity` is created by scripts/run_sql.py (all columns VARCHAR).
CREATE OR REPLACE TABLE fact_site_month AS
SELECT
    Month,
    HBT,
    TreatmentLocation,
    CAST(NumberOfAttendancesAll AS BIGINT) AS NumberOfAttendancesAll,
    CAST(NumberWithin4HoursAll  AS BIGINT) AS NumberWithin4HoursAll,
    CAST(NumberOver4HoursAll    AS BIGINT) AS NumberOver4HoursAll,
    ROUND(
        CAST(NumberWithin4HoursAll AS DOUBLE)
        / NULLIF(CAST(NumberOfAttendancesAll AS BIGINT), 0) * 100,
        2
    ) AS compliance_pct
FROM raw_activity
WHERE DepartmentType = 'Type 1'
  AND AttendanceCategory = 'All'
  AND NOT (TreatmentLocation = 'G405H' AND Month = '201505')
  AND NOT (TreatmentLocation = 'W106H' AND Month = '202505')
ORDER BY TreatmentLocation, Month;
