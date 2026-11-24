"""Display helpers for the Streamlit interface."""

import math
from html import escape

import streamlit as st

NUTRIENTS = {
    "kcal": ("열량", "kcal"),
    "carbs_g": ("탄수화물", "g"),
    "protein_g": ("단백질", "g"),
    "fat_g": ("지방", "g"),
}
LABELS = {key: f"{label} ({unit})" for key, (label, unit) in NUTRIENTS.items()}


def format_amount(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) < 0.005:
        return f"{value:.3g}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def goal_progress(current: float, target: float | None) -> tuple[float, float, float] | None:
    """Return signed remaining amount, exact percentage, and the bar's percentage."""
    if (isinstance(target, bool) or not isinstance(target, (int, float))
            or target <= 0 or not math.isfinite(target)):
        return None
    rate = current / target * 100
    return target - current, rate, min(100, max(0, rate))


def render_goals(totals, goals):
    cards = []
    for key, (label, unit) in NUTRIENTS.items():
        current = format_amount(totals[key])
        target = goals.get(key)
        progress = goal_progress(totals[key], target)
        if progress is None:
            detail = "목표 미설정" if target is None else "목표값 확인 필요"
            amount = f"{current} {unit}"
            bottom = f'<div class="na-goal__bottom">{detail}</div>'
        else:
            remaining, rate, bar = progress
            amount = f"{current} / {format_amount(target)} {unit}"
            detail = (f"초과 {format_amount(-remaining)} {unit}" if remaining < 0
                      else f"남은 {format_amount(remaining)} {unit}" if remaining else "목표 달성")
            bottom = (f'<progress aria-label="{label} 달성률" max="100" value="{bar:g}"></progress>'
                      f'<div class="na-goal__bottom"><span>달성률 {rate:.1f}%</span><span>{detail}</span></div>')
        cards.append(f'<div class="na-goal"><div class="na-goal__top"><span>{label}</span>'
                     f'<span>{escape(amount)}</span></div>{bottom}</div>')
    st.html('<section class="na-dashboard" aria-label="오늘 영양 목표 달성 현황">' + "".join(cards) + "</section>")


def render_status(label, *, tone="neutral"):
    st.html(f'<span class="na-status na-status--{tone}">{escape(label)}</span>')


def render_nutrient_cards(values):
    cards = []
    for key, (label, unit) in NUTRIENTS.items():
        cards.append(f'<div class="na-nutrient"><span class="na-nutrient__label">{label}</span>'
                     f'<strong class="na-nutrient__value">{format_amount(values[key])} '
                     f'<span class="na-nutrient__unit">{unit}</span></strong></div>')
    st.html('<section class="na-nutrients" aria-label="영양 합계">' + "".join(cards) + "</section>")


def amount_row(values):
    return {LABELS[key]: format_amount(value) for key, value in values.items()}


def composition(meal):
    return " · ".join(f'{line.food["name"]} {format_amount(line.grams)} g' for line in meal.lines)


def meal_table(meal):
    labels = ("중량 (g)", *LABELS.values())
    headers = "".join(f'<th scope="col">{label}</th>' for label in ("음식", *labels))
    rows = []
    for line in meal.lines:
        values = (line.grams, *(line.nutrients[key] for key in NUTRIENTS))
        cells = "".join(f'<td role="cell"><span aria-hidden="true">{label}</span>{format_amount(value)}</td>'
                        for label, value in zip(labels, values, strict=True))
        rows.append(f'<tr role="row"><th scope="row" role="rowheader">{escape(line.food["name"])}</th>{cells}</tr>')
    st.html('<table class="na-meal-table" role="table" aria-label="식품별 영양소">'
            f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def gap_text(value, unit):
    if value < 0:
        return f"초과 {format_amount(-value)} {unit}"
    if value > 0:
        return f"남은 {format_amount(value)} {unit}"
    return "목표 달성"


def render_impact(reply):
    if reply.impact and reply.impact.before:
        st.markdown("**목표까지 남은 양**")
        st.caption("추천을 받은 시점에 확정된 섭취량과 입력한 목표를 기준으로 비교합니다.")
        rows = []
        for key, before in reply.impact.before.items():
            label, unit = NUTRIENTS[key]
            rows.append(f'<div class="na-impact"><strong>{label}</strong>'
                        f'<span><small>추천 전</small>{gap_text(before, unit)}</span>'
                        f'<span><small>후보 섭취 후</small>{gap_text(reply.impact.after[key], unit)}</span></div>')
        st.html('<section class="na-impacts" aria-label="추천 전후 목표 차이">' + "".join(rows) + "</section>")
    if reply.candidates:
        st.caption("목표별 차이를 목표값으로 나눈 절대값의 합이 줄어드는 후보부터 표시합니다.")
    if len(reply.candidates) > 1:
        with st.expander("다른 저녁 후보"):
            for candidate in reply.candidates[1:]:
                st.markdown(f"**{candidate.name}**")
                st.text(composition(candidate.meal))
                st.caption(" · ".join(f"{label} {value}" for label, value in amount_row(candidate.meal.totals).items()))
                st.caption("후보 섭취 후 · " + " · ".join(
                    f"{NUTRIENTS[key][0]} {gap_text(value, NUTRIENTS[key][1])}"
                    for key, value in candidate.impact.after.items()
                ))


def render_substitution(reply):
    if not reply.previous_meal:
        return
    st.markdown("**음식 대체 전후**")
    st.text(f"이전  {composition(reply.previous_meal)}")
    st.text(f"대체  {composition(reply.meal)}")
    changes = []
    for key, difference in reply.changes.items():
        label, unit = NUTRIENTS[key]
        if abs(difference) < 1e-10:
            changes.append(f"{label} 변화 없음")
        else:
            direction = "증가 +" if difference > 0 else "감소 −"
            changes.append(f"{label} {direction}{format_amount(abs(difference))} {unit}")
    st.caption(" · ".join(changes))
