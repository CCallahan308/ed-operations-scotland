#!/usr/bin/env python3
"""Build and validate the DuckDB analytics layer, and reconcile it to the Python pipeline.

The SQL in sql/ rebuilds the (site x month) fact table, star-schema dimensions, and
count-ratio aggregations directly from the raw CSV, then runs data-quality gates.
This script wires the SQL to a data source, asserts the gates pass, and checks that
the SQL fact table matches src/ed_ops.build_primary_panel row-for-row.

Usage:
  python scripts/run_sql.py            # full dataset (data/raw/...)
  python scripts/run_sql.py --fixture  # committed 5-site fixture (no download needed)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ed_ops import data_quality as dq  # noqa: E402

SQL_DIR = ROOT / "sql"
FULL = ROOT / "data" / "raw" / "nhs_scotland_ae_activity_monthly.csv"
FIXTURE = ROOT / "tests" / "fixtures" / "activity_sample.csv"


def build_layer(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    con.execute(
        "CREATE OR REPLACE VIEW raw_activity AS "
        f"SELECT * FROM read_csv_auto('{csv_path.as_posix()}', all_varchar = true);"
    )
    for name in ("fact_site_month.sql", "dimensions.sql", "aggregations.sql"):
        con.execute((SQL_DIR / name).read_text())


def run_validations(con: duckdb.DuckDBPyConnection) -> dict:
    con.execute((SQL_DIR / "validations.sql").read_text())
    cols = [d[0] for d in con.description]
    return dict(zip(cols, con.fetchone(), strict=True))


def reconcile(con: duckdb.DuckDBPyConnection, csv_path: Path) -> dict:
    sql_panel = con.execute(
        "SELECT TreatmentLocation, Month, NumberOfAttendancesAll, "
        "NumberWithin4HoursAll, NumberOver4HoursAll, compliance_pct "
        "FROM fact_site_month ORDER BY TreatmentLocation, Month"
    ).df()
    py_panel = dq.clean_activity_to_panel(pd.read_csv(csv_path, dtype=str)).reset_index(drop=True)
    py_panel["Month"] = py_panel["Month"].astype(str)

    merged = py_panel.merge(
        sql_panel,
        on=["TreatmentLocation", "Month"],
        suffixes=("_py", "_sql"),
        how="outer",
        indicator=True,
    )
    key_mismatch = int((merged["_merge"] != "both").sum())
    both = merged[merged["_merge"] == "both"]
    count_mismatch = int(
        (both["NumberWithin4HoursAll_py"] != both["NumberWithin4HoursAll_sql"]).sum()
    )
    compliance_maxdiff = float((both["compliance_pct_py"] - both["compliance_pct_sql"]).abs().max())
    return {
        "py_rows": len(py_panel),
        "sql_rows": len(sql_panel),
        "key_mismatch": key_mismatch,
        "count_mismatch": count_mismatch,
        "compliance_maxdiff": round(compliance_maxdiff, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build/validate the DuckDB analytics layer.")
    ap.add_argument("--fixture", action="store_true", help="use the committed fixture sample")
    args = ap.parse_args()
    csv_path = FIXTURE if args.fixture else FULL
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run scripts/fetch_data.py (or use --fixture).")
        return 1

    con = duckdb.connect()
    build_layer(con, csv_path)

    fact = con.execute(
        "SELECT COUNT(*) AS rows, COUNT(DISTINCT TreatmentLocation) AS sites, "
        "COUNT(DISTINCT HBT) AS boards FROM fact_site_month"
    ).fetchone()
    print(f"fact_site_month: {fact[0]} rows, {fact[1]} sites, {fact[2]} boards ({csv_path.name})")

    vals = run_validations(con)
    print("data-quality gates (all must be 0):")
    for k, v in vals.items():
        print(f"  {'OK ' if v == 0 else 'FAIL'} {k} = {v}")

    rec = reconcile(con, csv_path)
    print("reconciliation vs Python build_primary_panel:")
    print(
        f"  rows py={rec['py_rows']} sql={rec['sql_rows']}  key_mismatch={rec['key_mismatch']}"
        f"  count_mismatch={rec['count_mismatch']}  compliance_maxdiff={rec['compliance_maxdiff']}"
    )

    ok = (
        all(v == 0 for v in vals.values())
        and rec["py_rows"] == rec["sql_rows"]
        and rec["key_mismatch"] == 0
        and rec["count_mismatch"] == 0
        and rec["compliance_maxdiff"] <= 0.01
    )
    print("\nRESULT:", "PASS -- SQL layer reconciles to the Python pipeline." if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
