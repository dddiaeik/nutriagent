"""Validated adapter for the curated K-FIND food catalog (100g-based rows only).

The original USDA list remains unchanged. K-FIND has no verified serving weight,
so these foods must be calculated from grams or kilograms, never "1 serving".
"""
from __future__ import annotations

import json
import math
from pathlib import Path

K_FIND_PATH = Path(__file__).with_name("data") / "foods_kfind_v1.json"
FIELDS = ("kcal", "carbs_g", "protein_g", "fat_g")
EXPLICIT_ALIASES = {
    "볶음밥_김치": ["김치볶음밥"],
    "볶음밥_새우": ["새우볶음밥"],
    "돼지고기볶음(제육볶음)": ["제육볶음"],
    "달걀부침(달걀후라이)": ["계란후라이", "달걀후라이"],
}


def load_kfind_catalog(path: Path = K_FIND_PATH) -> tuple[dict, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    meta = document.get("meta", {})
    if meta.get("schema_version") != "kfind-curated-v1":
        raise ValueError("Unsupported K-FIND data schema")
    source_url = meta.get("download_url", "")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise ValueError("Missing K-FIND data source")
    rows = document.get("foods")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty K-FIND catalog")
    catalog = []
    codes = set()
    names = set()
    for row in rows:
        name = row["name"]
        code = row["food_code"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing K-FIND food name")
        if not isinstance(code, str) or not code or code in codes or name in names:
            raise ValueError("Duplicate/missing K-FIND food code or name")
        if row.get("nutrient_basis") != {"quantity": 100, "unit": "g"}:
            raise ValueError("Unsupported basis for " + name)
        if row.get("data_method") != "분석":
            raise ValueError("Unexpected data method for " + name)
        nutrients = row.get("per_100g", {})
        for field in FIELDS:
            value = nutrients.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Missing/invalid {field} for {name}")
        sodium = nutrients.get("sodium_mg")
        if sodium is not None and (isinstance(sodium, bool) or
                                   not isinstance(sodium, (int, float)) or
                                   not math.isfinite(sodium) or sodium < 0):
            raise ValueError(f"Invalid sodium for {name}")
        # Space-separated labels and a tiny explicit alias list aid Korean lookup.
        aliases = list(dict.fromkeys(
            ([name.replace("_", " ")] if "_" in name else [])
            + EXPLICIT_ALIASES.get(name, [])
        ))
        catalog.append({
            "name": name,
            "aliases": aliases,
            "ndb": code,  # Legacy UI-compatible identifier; NOT a USDA NDB code.
            "food_code": code,
            "serving_g": None,  # K-FIND provided no verified 1-serving mapping.
            "description": f"{row['category']} · {row.get('data_origin') or 'K-FIND 분석'} · 100g 기준",
            "per_100g": {field: nutrients[field] for field in FIELDS},
            "sodium_mg": sodium,
            "source_name": "식품의약품안전처 K-FIND 음식 DB",
            "source_url": row.get("source_url") or source_url,
            "source_file_sha256": meta.get("source_file_sha256", ""),
            "category": row.get("category", ""),
        })
        codes.add(code)
        names.add(name)
    return tuple(catalog)
