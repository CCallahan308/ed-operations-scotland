-- Star-schema dimensions around fact_site_month.
CREATE OR REPLACE TABLE dim_site AS
SELECT DISTINCT TreatmentLocation AS site_id, HBT AS board_id
FROM fact_site_month
ORDER BY site_id;

CREATE OR REPLACE TABLE dim_board AS
SELECT DISTINCT HBT AS board_id
FROM fact_site_month
ORDER BY board_id;

CREATE OR REPLACE TABLE dim_calendar AS
SELECT DISTINCT
    Month AS month_id,
    CAST(SUBSTR(Month, 1, 4) AS INT) AS year,
    CAST(SUBSTR(Month, 5, 2) AS INT) AS month_of_year,
    (CAST(SUBSTR(Month, 5, 2) AS INT) - 1) / 3 + 1 AS quarter,
    make_date(CAST(SUBSTR(Month, 1, 4) AS INT), CAST(SUBSTR(Month, 5, 2) AS INT), 1) AS month_start
FROM fact_site_month
ORDER BY month_id;
