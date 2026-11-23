"""Inspect K-FIND public workbook structure without changing its contents.

Usage:
    python scripts/inspect_kfind.py "data/raw/downloaded.xlsx"
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path


def inspect(path: Path) -> int:
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    print(f"Path: {path}")
    print(f"Size: {path.stat().st_size:,} bytes")
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    print(f"SHA-256: {checksum.hexdigest()}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist()[:40]:
                print(f"ZIP member: {item.filename} ({item.file_size:,} bytes)")
        print("Extract the file locally after checking its contents; then inspect the .xlsx file.")
        return 0

    if path.suffix.lower() != ".xlsx":
        print("Supported formats: .xlsx or .zip containing a workbook. If .xls, convert to .xlsx first.")
        return 2

    try:
        from openpyxl import load_workbook
    except ImportError:
        print("Missing dependency: run .\\.venv\\Scripts\\python.exe -m pip install openpyxl", file=sys.stderr)
        return 2

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        print(f"Sheets: {workbook.sheetnames}")
        for sheet in workbook:
            print(f"\n=== Sheet: {sheet.title} | rows≈{sheet.max_row}, columns≈{sheet.max_column} ===")
            count = 0
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                populated = [
                    f"{column}: {str(cell)[:85]}"
                    for column, cell in enumerate(row, start=1)
                    if cell is not None and str(cell).strip()
                ]
                if not populated:
                    continue
                print(f"Row {row_number}: " + " | ".join(populated[:35]))
                if len(populated) > 35:
                    print(f"   ... and {len(populated) - 35} more nonempty cells")
                count += 1
                if count >= 8:
                    break
            if count == 0:
                print("No nonempty rows found.")
    finally:
        workbook.close()
    print("\nInspection only. Nutrient columns, units and per-serving bases still need manual mapping.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="K-FIND .xlsx or downloaded .zip")
    arguments = parser.parse_args()
    raise SystemExit(inspect(arguments.file))
