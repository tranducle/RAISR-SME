#!/usr/bin/env python3
"""Standalone NIST CSF 2.0 subcategory identifier verifier for RAISR-SME.

Verifies every NIST CSF 2.0 subcategory identifier (GV/ID/PR/DE/RS/RC.XX-NN)
referenced in instrument/nist_csf2_crosswalk.json and optional manuscript files against the
vendored authoritative catalog (catalogs_nist_csf_2_0.csv: 106 active subcategories plus 79
withdrawn v1.1 records), and writes deterministic verification output to
results/nist_csf2_id_verification.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "catalogs_nist_csf_2_0.csv"
BANK_PATH = HERE.parent / "instrument" / "nist_csf2_crosswalk.json"
OUT_PATH = HERE / "results" / "nist_csf2_id_verification.json"

CSF_PATTERN = re.compile(r"\b(?:GV|ID|PR|DE|RS|RC)\.[A-Z]{2}-\d{2}\b")


def load_csf_catalog(path: Path = CATALOG_PATH) -> Dict[str, Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def scan_file(path: Path, catalog: Dict[str, Dict[str, str]]) -> List[Dict[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: List[Dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in CSF_PATTERN.finditer(line):
            cid = match.group(0)
            rec = catalog.get(cid)
            verdict = "ok" if (rec is not None and (rec.get("status") or "active") == "active") else "unknown"
            rows.append(
                {
                    "file": path.name,
                    "line": line_no,
                    "id": cid,
                    "framework": "nist_csf_2_0",
                    "verdict": verdict,
                    "name": rec.get("title", "") if rec else "",
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify NIST CSF 2.0 subcategory IDs.")
    parser.add_argument("paths", nargs="*", help="Optional files to check (defaults to instrument/nist_csf2_crosswalk.json).")
    parser.add_argument("-w", dest="write_json", action="store_true", help="Write results/nist_csf2_id_verification.json.")
    args = parser.parse_args()

    catalog = load_csf_catalog()
    active_count = sum(1 for r in catalog.values() if (r.get("status") or "active") == "active")
    targets = [Path(p) for p in args.paths] if args.paths else [BANK_PATH]
    all_occ: List[Dict[str, object]] = []
    for t in targets:
        all_occ.extend(scan_file(t, catalog))

    problems = sum(1 for r in all_occ if r["verdict"] != "ok")
    unique_ids = sorted({str(r["id"]) for r in all_occ})
    if args.write_json or not args.paths:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "catalog_subcategories": len(catalog),
            "active_catalog_subcategories": active_count,
            "checked_files": [t.name for t in targets],
            "total_occurrences": len(all_occ),
            "unique_ids_count": len(unique_ids),
            "unique_ids": unique_ids,
            "problems": problems,
            "all_ok": problems == 0,
            "occurrences": all_occ,
        }
        OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        f"[verify_ids] catalog={active_count} active ({len(catalog)} total) | "
        f"occurrences={len(all_occ)} | unique={len(unique_ids)} | problems={problems}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
