#!/usr/bin/env python3
"""Regenerate reports/dashboard_data.json (the committed artifact the app reads).

Run after the model or data changes. Requires the full dataset (scripts/fetch_data.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ed_ops.dashboard_data import write_dashboard_data  # noqa: E402

if __name__ == "__main__":
    out = write_dashboard_data()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
