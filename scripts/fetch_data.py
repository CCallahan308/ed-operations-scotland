#!/usr/bin/env python3
"""Download the NHS Scotland A&E raw data this project uses.

Source : Public Health Scotland, "Monthly A&E Activity and Waiting Times".
License: UK Open Government Licence (OGL) v3.0.
Portal : https://www.opendata.nhs.scot/dataset/monthly-accident-and-emergency-activity-and-waiting-times

Only the monthly *activity* CSV is required to run the pipeline and the core
test suite. Four companion files (demographics / when / referral / multiple
attendances) are optional enrichment, reserved for future work and NOT used by
the model.

Each download is checked against the SHA-256 recorded in src/ed_ops/config.py
(the 2026-07-21 snapshot). A mismatch means Public Health Scotland has updated
the dataset since that snapshot; the committed artifacts correspond to the frozen
snapshot, so a newer file may change results.

Usage:
  python scripts/fetch_data.py           # download the essential activity file + verify
  python scripts/fetch_data.py --all     # also attempt the optional companion files
  python scripts/fetch_data.py --verify  # verify already-present files, no download
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ed_ops import config as C  # noqa: E402

UA = {"User-Agent": "ed-operations-scotland/1.0 (portfolio; OGL v3.0 data)"}
CKAN_RESOURCE_SHOW = "https://www.opendata.nhs.scot/api/3/action/resource_show?id={}"

MAIN = ("activity_monthly", C.SOURCE_LOCAL_PATH, C.SOURCE_MAIN_CSV_URL)
COMPANIONS = [
    ("demographics", C.SOURCE_DEMOGRAPHICS_PATH, C.SOURCE_RESOURCE_DEMOGRAPHICS_ID),
    ("when", C.SOURCE_WHEN_PATH, C.SOURCE_RESOURCE_WHEN_ID),
    ("referral", C.SOURCE_REFERRAL_PATH, C.SOURCE_RESOURCE_REFERRAL_ID),
    (
        "multiple_attendances",
        C.SOURCE_MULTIPLE_ATTENDANCES_PATH,
        C.SOURCE_RESOURCE_MULTIPLE_ATTENDANCES_ID,
    ),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(key: str, path: Path) -> bool:
    if not path.exists():
        print(f"  [MISSING]  {path.name}")
        return False
    got, exp = sha256(path), C.SOURCE_PROVENANCE[key][0]
    ok = got == exp
    print(f"  [{'OK' if ok else 'SHA MISMATCH'}]  {path.name}")
    if not ok:
        print(f"       expected {exp[:16]}..  got {got[:16]}..")
        print(
            "       Public Health Scotland has updated the dataset since the 2026-07-21 "
            "snapshot; committed results correspond to that snapshot."
        )
    return ok


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {dest.name} ...")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        f.write(r.read())


def _resolve_ckan_url(resource_id: str) -> str:
    req = urllib.request.Request(CKAN_RESOURCE_SHOW.format(resource_id), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["result"]["url"]


def fetch_one(key: str, path: Path, url_or_id: str, *, is_id: bool = False) -> bool:
    try:
        url = _resolve_ckan_url(url_or_id) if is_id else url_or_id
        _download(url, path)
    except (urllib.error.URLError, KeyError, TimeoutError) as e:
        print(f"  [FAILED]   {path.name}: {e}")
        return False
    return verify(key, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch NHS Scotland A&E raw data (OGL v3.0).")
    ap.add_argument("--all", action="store_true", help="also fetch optional companion files")
    ap.add_argument("--verify", action="store_true", help="verify present files only (no download)")
    args = ap.parse_args()

    print("NHS Scotland A&E data - Public Health Scotland, OGL v3.0")
    print(f"Portal: {C.SOURCE_PORTAL_URL}\n")

    if args.verify:
        print("Verifying present files against recorded SHA-256 (2026-07-21 snapshot):")
        results = [verify(MAIN[0], MAIN[1])]
        results += [verify(k, p) for k, p, _ in COMPANIONS if p.exists()]
        return 0 if all(results) else 1

    print("Fetching the essential activity file (the only input the model uses):")
    if not fetch_one(*MAIN):
        print("\nERROR: the essential activity file did not download/verify (see above).")
        return 1

    if args.all:
        print("\nFetching optional companion enrichment files (not used by the model):")
        for k, p, rid in COMPANIONS:
            fetch_one(k, p, rid, is_id=True)
    else:
        print("\nOptional companion files (enrichment, not used by the model) were skipped.")
        print("Run with --all to attempt them, or download manually from the portal.")

    print("\nDone. Run `python -m pytest tests/ -q` to validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
