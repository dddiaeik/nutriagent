"""Calculate meal nutrition from a small USDA Standard Reference dataset."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).with_name("data")
NUTRIENTS = ("kcal", "carbs_g", "protein_g", "fat_g")
UNITS = ("g", "kg", "serving")
SOURCE = "USDA National Nutrient Database for Standard Reference, Release 28"
SOURCE_URL = "https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/sr28_doc.pdf"
FOODS = json.loads((DATA / "foods.json").read_text(encoding="utf-8"))


class InputError(ValueError):
    """An input needs clarification before it can be calculated."""


@dataclass(frozen=True)
class MealLine:
    food: dict
    grams: float
    nutrients: dict


@dataclass(frozen=True)
class Meal:
    lines: tuple[MealLine, ...]
    totals: dict


def _normalize(name: str) -> str:
    return " ".join(name.casefold().split())


def find_food(name: str) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise InputError("음식 이름을 알려 주세요.")
    query = _normalize(name)
    for food in FOODS:
        if query in {_normalize(alias) for alias in (food["name"], *food["aliases"])}:
            return food
    raise InputError(f"'{name}'은 등록되지 않았습니다. 식품 목록에서 선택해 주세요.")


def _number(value, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InputError(f"{label}을(를) 양의 숫자로 알려 주세요.")
    try:
        number = float(value)
    except OverflowError:
        raise InputError(f"{label}이(가) 너무 큽니다.") from None
    if not math.isfinite(number) or number <= 0:
        raise InputError(f"{label}을(를) 유한한 양의 숫자로 알려 주세요.")
    return number


def calculate(items: list[dict]) -> Meal:
    if not isinstance(items, list) or not items:
        raise InputError("음식, 수량, 단위를 알려 주세요.")
    lines = []
    for item in items:
        if not isinstance(item, dict):
            raise InputError("각 음식의 이름, 수량, 단위를 알려 주세요.")
        food = find_food(item.get("food"))
        quantity = _number(item.get("quantity"), f'{food["name"]} 수량')
        unit = item.get("unit")
        if unit not in UNITS:
            raise InputError(f'{food["name"]}의 단위를 g, kg 또는 인분으로 알려 주세요.')
        grams = quantity * {"g": 1, "kg": 1000, "serving": food["serving_g"]}[unit]
        nutrients = {key: food["per_100g"][key] * (grams / 100) for key in NUTRIENTS}
        lines.append(MealLine(food, grams, nutrients))
    totals = {key: sum(line.nutrients[key] for line in lines) for key in NUTRIENTS}
    if not all(math.isfinite(value) for value in totals.values()):
        raise InputError("섭취량이 너무 커서 계산할 수 없습니다.")
    return Meal(tuple(lines), totals)


def compare_goals(totals: dict, goals: dict) -> dict:
    """Return the signed difference between intake and each supplied goal."""
    return {
        key: totals[key] - _number(goals[key], "목표값")
        for key in NUTRIENTS
        if goals.get(key) is not None
    }


def replace_food(meal: Meal, old_food: str, new_food: str) -> Meal:
    old = find_food(old_food)
    new = find_food(new_food)
    if not any(line.food["ndb"] == old["ndb"] for line in meal.lines):
        raise InputError(f'이전 식단에 {old["name"]}이(가) 없습니다.')
    items = [
        {
            "food": new["name"] if line.food["ndb"] == old["ndb"] else line.food["name"],
            "quantity": line.grams,
            "unit": "g",
        }
        for line in meal.lines
    ]
    return calculate(items)
