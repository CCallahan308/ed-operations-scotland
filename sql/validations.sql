-- Data-quality gates on the fact table. Every count MUST be 0.
SELECT
    (SELECT COUNT(*) FROM fact_site_month
       WHERE NumberWithin4HoursAll + NumberOver4HoursAll <> NumberOfAttendancesAll)
        AS count_identity_violations,
    (SELECT COUNT(*) FROM fact_site_month
       WHERE compliance_pct < 0 OR compliance_pct > 100)
        AS pct_range_violations,
    (SELECT COUNT(*) FROM (
        SELECT TreatmentLocation, Month FROM fact_site_month
        GROUP BY TreatmentLocation, Month HAVING COUNT(*) > 1) d)
        AS duplicate_grain_violations,
    (SELECT COUNT(*) FROM fact_site_month
       WHERE TreatmentLocation IS NULL OR Month IS NULL OR NumberOfAttendancesAll IS NULL)
        AS null_key_violations;
