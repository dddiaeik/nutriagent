"""Rank fixed dinner candidates against explicitly configured daily targets."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from nutrition import NUTRIENTS, InputError, Meal, calculate, compare_goals

# Planned quantities in grams, evaluated using the existing food catalog.
MENUS = (
    ("김치찌개와 쌀밥", (("김치찌개", 200), ("쌀밥", 150), ("시금치나물", 50))),
    ("두부조림과 보리밥", (("두부조림", 120), ("보리밥", 150), ("콩나물무침", 70))),
    ("닭가슴살과 잡곡밥", (("닭가슴살", 120), ("잡곡밥", 150), ("삶은 브로콜리", 80))),
    ("가자미구이와 현미밥", (("가자미구이", 120), ("현미밥", 150), ("오이생채", 60))),
    ("비빔밥과 삶은 달걀", (("비빔밥", 300), ("달걀_삶은것", 50))),
    ("소불고기와 쌀밥", (("소불고기", 100), ("쌀밥", 150), ("미역국_소고기", 200))),
)


@dataclass(frozen=True)
class IntakeRecord:
    day: date
    meal: Meal | None


@dataclass(frozen=True)
class GoalImpact:
    before: dict[str, float]
    after: dict[str, float]


@dataclass(frozen=True)
class Candidate:
    name: str
    meal: Meal
    impact: GoalImpact


def confirmed_totals(records: Iterable[IntakeRecord], day: date) -> dict[str, float]:
    meals = [record.meal for record in records if record.day == day and record.meal is not None]
    return {key: sum(meal.totals[key] for meal in meals) for key in NUTRIENTS}


def goal_gap(totals: dict, goals: dict) -> dict[str, float]:
    """Positive values still remain, negative values are already over the target."""
    return {key: -difference for key, difference in compare_goals(totals, goals).items()}


def evaluate_meal(meal: Meal, totals: dict, goals: dict) -> GoalImpact:
    after = {key: totals[key] + meal.totals[key] for key in NUTRIENTS}
    return GoalImpact(goal_gap(totals, goals), goal_gap(after, goals))


def rank_candidates(totals: dict, goals: dict) -> list[Candidate]:
    before = goal_gap(totals, goals)
    if not before:
        raise InputError("사이드바에서 오늘의 영양 목표를 한 가지 이상 설정해 주세요.")

    def distance(gap):
        return math.fsum(abs(value) / goals[key] for key, value in gap.items())

    baseline = distance(before)
    ranked = []
    for name, portions in MENUS:
        meal = calculate([{"food": food, "quantity": grams, "unit": "g"} for food, grams in portions])
        impact = evaluate_meal(meal, totals, goals)
        score = distance(impact.after)
        if score < baseline:
            ranked.append((score, Candidate(name, meal, impact)))
    return [candidate for _, candidate in sorted(ranked, key=lambda entry: entry[0])]
