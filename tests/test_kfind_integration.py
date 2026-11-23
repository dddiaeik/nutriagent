"""K-FIND integration tests; all run offline without Ollama."""
import json

import pytest

from kfind_catalog import K_FIND_PATH, load_kfind_catalog
from nutrition import ALL_FOODS, FOODS, InputError, calculate, find_food


def test_catalog_has_98_unique_records_with_provenance():
    foods = load_kfind_catalog()
    assert len(foods) == 98
    assert len(ALL_FOODS) == len(FOODS) + 98
    assert len({f["food_code"] for f in foods}) == 98
    assert all(f["source_url"].startswith("https://") for f in foods)
    assert all(f["serving_g"] is None for f in foods)


def test_kfind_food_has_100g_source_basis_and_no_imputation():
    dataset = json.loads(K_FIND_PATH.read_text(encoding="utf-8"))
    assert dataset["meta"]["schema_version"] == "kfind-curated-v1"
    assert len(dataset["foods"]) == 98
    assert all(f["nutrient_basis"] == {"quantity": 100, "unit": "g"} for f in dataset["foods"])
    assert all(f["data_method"] == "분석" for f in dataset["foods"])
    assert all(f["source"] and f["food_code"] for f in dataset["foods"])
    assert all(f["per_100g"][field] is not None for f in dataset["foods"]
               for field in ("kcal", "carbs_g", "protein_g", "fat_g"))


def test_korean_rice_exact_match_preferred_over_usda_alias():
    rice = find_food("쌀밥")
    assert rice["name"] == "쌀밥"
    assert rice["per_100g"]["kcal"] == 166
    assert "K-FIND" in rice["source_name"]
    assert find_food("흰쌀밥")["ndb"] == "20445"


def test_kfind_stew_calculation_uses_grams_only():
    stew = find_food("김치찌개")
    assert stew["per_100g"]["kcal"] == 61
    result = calculate([{"food": "김치찌개", "quantity": 200, "unit": "g"}])
    assert result.totals["kcal"] == 122
    assert result.lines[0].food["food_code"] == stew["food_code"]


def test_kfind_serving_not_assumed_as_100g():
    with pytest.raises(InputError, match="1인분 중량은 검증되지"):
        calculate([{"food": "김치찌개", "quantity": 1, "unit": "serving"}])


def test_kfind_korean_alias_and_registered_rice():
    assert find_food("김치볶음밥")["name"] == "볶음밥_김치"
    assert find_food("제육볶음")["name"] == "돼지고기볶음(제육볶음)"
    assert find_food("떡볶이")["name"] == "떡볶이"


def test_existing_usda_calculations_remain_unchanged():
    result = calculate([
        {"food": "닭가슴살", "quantity": 100, "unit": "g"},
        {"food": "흰쌀밥", "quantity": 150, "unit": "g"},
    ])
    assert result.totals["kcal"] == 360
    assert result.totals["protein_g"] == pytest.approx(35.055)


def test_kfind_rejects_unverified_nutrient_basis(tmp_path):
    document = json.loads(K_FIND_PATH.read_text(encoding="utf-8"))
    document["foods"][0]["nutrient_basis"] = {"quantity": 100, "unit": "ml"}
    path = tmp_path / "wrong_basis.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported basis"):
        load_kfind_catalog(path)
