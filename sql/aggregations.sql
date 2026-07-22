-- Aggregations use COUNT-RATIO re-aggregation: SUM(within4)/SUM(total).
-- They never average per-site percentages (that would be size-biased).

-- National monthly compliance.
CREATE OR REPLACE TABLE agg_by_month AS
SELECT
    Month AS month_id,
    COUNT(*) AS n_sites,
    SUM(NumberOfAttendancesAll) AS attendances,
    SUM(NumberWithin4HoursAll)  AS within_4h,
    ROUND(SUM(NumberWithin4HoursAll)::DOUBLE
          / NULLIF(SUM(NumberOfAttendancesAll), 0) * 100, 2) AS compliance_pct
FROM fact_site_month
GROUP BY Month
ORDER BY Month;

-- Per-board per-month compliance.
CREATE OR REPLACE TABLE agg_by_board_month AS
SELECT
    HBT AS board_id,
    Month AS month_id,
    ROUND(SUM(NumberWithin4HoursAll)::DOUBLE
          / NULLIF(SUM(NumberOfAttendancesAll), 0) * 100, 2) AS compliance_pct
FROM fact_site_month
GROUP BY HBT, Month
ORDER BY HBT, Month;

-- Annual MEDIAN of site-month compliance -- the structural-break series the
-- dashboard's "The data" page plots.
CREATE OR REPLACE TABLE agg_annual_median AS
SELECT
    CAST(SUBSTR(Month, 1, 4) AS INT) AS year,
    ROUND(MEDIAN(compliance_pct), 2) AS median_compliance_pct,
    COUNT(*) AS n_site_months
FROM fact_site_month
GROUP BY year
ORDER BY year;

-- Per-site lifetime compliance and coverage.
CREATE OR REPLACE TABLE agg_by_site AS
SELECT
    TreatmentLocation AS site_id,
    COUNT(*) AS n_months,
    ROUND(SUM(NumberWithin4HoursAll)::DOUBLE
          / NULLIF(SUM(NumberOfAttendancesAll), 0) * 100, 2) AS compliance_pct
FROM fact_site_month
GROUP BY site_id
ORDER BY site_id;
