"""Verify curated K-FIND foods against the exact original downloaded workbook.

Usage:
    python scripts/verify_kfind_source.py "data/raw/음식 DB.xlsx"

Read-only. Uses Python standard library (no extra spreadsheet dependencies).
Does not overwrite the tracked curated dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

BASE = Path(__file__).resolve().parents[1]
CURATED = BASE / "data" / "foods_kfind_v1.json"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUMNS = {"A", "B", "Q", "R", "T", "U", "W", "FB"}


def read_original(xlsx: Path):
    with ZipFile(xlsx) as archive:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.iter(NS + "t"))
            for item in root.findall(NS + "si")
        ]
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            for _, element in ET.iterparse(sheet, events=("end",)):
                if element.tag != NS + "row":
                    continue
                record = {}
                for cell in element.findall(NS + "c"):
                    match = re.match(r"[A-Z]+", cell.get("r", ""))
                    col = match.group() if match else ""
                    if col not in COLUMNS:
                        continue
                    value = cell.find(NS + "v")
                    if value is None:
                        continue
                    raw = value.text
                    if raw is not None and cell.get("t") == "s":
                        raw = shared[int(raw)]
                    record[col] = raw
                yield record
                element.clear()


def main(xlsx: Path) -> int:
    if not xlsx.is_file():
        print(f"Original workbook missing: {xlsx}", file=sys.stderr)
        return 2
    data = json.loads(CURATED.read_text(encoding="utf-8"))
    expected_sha = data["meta"]["source_file_sha256"]
    sha = hashlib.sha256()
    with xlsx.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != expected_sha:
        print("Source workbook SHA-256 differs; stop before mixing versions.", file=sys.stderr)
        return 2

    expected = {f["food_code"]: f for f in data["foods"]}
    matched = {}
    fields = {"kcal": "R", "protein_g": "T", "fat_g": "U", "carbs_g": "W"}
    for row in read_original(xlsx):
        code = row.get("A")
        if code not in expected:
            continue
        original = expected[code]
        if row.get("B") != original["name"] or row.get("Q") != "100g" or row.get("FB") != "분석":
            print(f"Metadata mismatch for {code}", file=sys.stderr)
            return 2
        for field, column in fields.items():
            val = float(row[column])
            target = float(original["per_100g"][field])
            if not (math.isfinite(val) and math.isclose(val, target, abs_tol=1e-8)):
                print(f"Nutrient mismatch for {code}, {field}", file=sys.stderr)
                return 2
        if code in matched:
            print(f"Duplicate food code in workbook: {code}", file=sys.stderr)
            return 2
        matched[code] = original["name"]

    missing = set(expected) - set(matched)
    if missing:
        print(f"Missing curated codes: {len(missing)}", file=sys.stderr)
        return 2
    print(f"PASS: {len(matched)} K-FIND foods verified against original XLSX and SHA-256")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.xlsx))
