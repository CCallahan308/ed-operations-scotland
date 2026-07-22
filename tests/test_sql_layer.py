"""Tests for the DuckDB analytics layer (sql/).

Fixture-mode tests run on any clone. Full-data tests reconcile the SQL fact table
to the Python pipeline row-for-row and skip when the dataset is absent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

from ed_ops.config import RAW_DIR

requires_full_data = pytest.mark.skipif(
    not (RAW_DIR / "nhs_scotland_ae_activity_monthly.csv").exists(),
    reason="Full PHS dataset absent -- run `python scripts/fetch_data.py` (see README Quickstart).",
)

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_sql", _ROOT / "scripts" / "run_sql.py")
run_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_sql)


def _connection_for(csv_path):
    con = duckdb.connect()
    run_sql.build_layer(con, csv_path)
    return con


def test_sql_fixture_validations_all_zero():
    con = _connection_for(run_sql.FIXTURE)
    violations = run_sql.run_validations(con)
    assert all(v == 0 for v in violations.values()), violations


def test_sql_fixture_reconciles_to_python():
    con = _connection_for(run_sql.FIXTURE)
    r = run_sql.reconcile(con, run_sql.FIXTURE)
    assert r["py_rows"] == r["sql_rows"]
    assert r["key_mismatch"] == 0
    assert r["count_mismatch"] == 0
    assert r["compliance_maxdiff"] <= 0.01


@requires_full_data
def test_sql_fulldata_reconciles_to_python():
    con = _connection_for(run_sql.FULL)
    r = run_sql.reconcile(con, run_sql.FULL)
    assert r["py_rows"] == 7022 and r["sql_rows"] == 7022
    assert r["key_mismatch"] == 0
    assert r["count_mismatch"] == 0
    assert r["compliance_maxdiff"] <= 0.01
    assert all(v == 0 for v in run_sql.run_validations(con).values())


@requires_full_data
def test_sql_national_compliance_matches_python():
    """Count-ratio national compliance from SQL must match the Python computation."""
    con = _connection_for(run_sql.FULL)
    sql_c = con.execute(
        "SELECT compliance_pct FROM agg_by_month WHERE month_id = '202605'"
    ).fetchone()[0]
    from ed_ops.data_quality import build_primary_panel

    p = build_primary_panel()
    p = p[p["Month"] == "202605"]
    py_c = round(100 * p["NumberWithin4HoursAll"].sum() / p["NumberOfAttendancesAll"].sum(), 2)
    assert abs(sql_c - py_c) <= 0.01
