from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from agent import Mode, run_turn
from nutrition import InputError, calculate
from nutrigap import MENUS, IntakeRecord, confirmed_totals, goal_gap, rank_candidates

INTAKE = "김치찌개 200g과 쌀밥 150g을 계산해 줘"
DINNER = "오늘 목표에 맞춰 저녁을 추천해 줘"


def test_confirmed_totals_use_only_active_records_from_today():
    today = date(2026, 11, 23)
    meal = calculate([{"food": "김치찌개", "quantity": 200, "unit": "g"}])
    records = [IntakeRecord(today, meal), IntakeRecord(today, None), IntakeRecord(today - timedelta(days=1), meal)]
    totals = confirmed_totals(records, today)
    assert totals == meal.totals
    assert goal_gap(totals, {"kcal": 100, "protein_g": None}) == {"kcal": -22}


def test_ranked_menus_target_only_explicit_goals():
    intake = run_turn([{"role": "user", "content": INTAKE}], mode=Mode.MOCK).meal
    goals = {"kcal": 820, "protein_g": 60, "fat_g": None}
    ranked = rank_candidates(intake.totals, goals)
    assert 5 <= len(MENUS) <= 10
    assert len(ranked) == len(MENUS)
    assert ranked[0].name == "닭가슴살과 잡곡밥"
    assert ranked[0].impact.before == pytest.approx({"kcal": 449, "protein_g": 47.42})
    assert ranked[0].impact.after == pytest.approx({"kcal": 4, "protein_g": 0.342})
    assert rank_candidates(intake.totals, {"kcal": 371}) == []
    with pytest.raises(InputError, match="목표를 한 가지 이상"):
        rank_candidates(intake.totals, {"protein_g": None})


def test_ui_daily_recommendation_substitution_edit_and_withdrawal(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "MOCK")
    screen = AppTest.from_file("app.py", default_timeout=15).run()
    screen.chat_input[0].set_value(INTAKE).run()
    assert not screen.session_state.records
    screen.button(key="record-0").click().run()
    screen.run()
    assert list(screen.session_state.records) == [0]
    assert screen.session_state.records[0].meal.totals["kcal"] == 371

    screen.number_input(key="goal-kcal").set_value(820).run()
    screen.number_input(key="goal-protein_g").set_value(60).run()
    screen.chat_input[0].set_value(DINNER).run()
    reply = screen.session_state.turns[1][1]
    assert reply.candidates[0].name == "닭가슴살과 잡곡밥"
    assert reply.impact.after["kcal"] == 4
    assert not any(button.key == "record-1" for button in screen.button)

    screen.chat_input[0].set_value("닭가슴살 대신 두부").run()
    swapped = screen.session_state.turns[2][1]
    assert swapped.changes["kcal"] == pytest.approx(-25.2)
    assert swapped.impact.after["kcal"] == pytest.approx(29.2)
    assert not any(button.key == "record-2" for button in screen.button)
    assert screen.session_state.records[0].meal.totals["kcal"] == 371

    def save_weight(grams):
        screen.number_input(key="weight-0-0").set_value(grams)
        next(button for button in screen.button if button.label == "중량 변경 저장").click().run()

    save_weight(0)
    assert "양의 숫자" in screen.error[0].value
    assert screen.session_state.records[0].meal.totals["kcal"] == 371
    save_weight(100)
    assert screen.session_state.records[0].meal.totals["kcal"] == 310
    screen.button(key="withdraw-0").click().run()
    assert not screen.exception
    assert screen.session_state.records[0].meal is None
    assert not any(button.key == "record-0" for button in screen.button)
    assert any("확정한 식단 0건" in text.value for text in screen.markdown)


def test_mock_requests_goal_before_ranking():
    reply = run_turn([{"role": "user", "content": DINNER}], mode=Mode.MOCK)
    assert not reply.candidates
    assert "목표를 한 가지 이상" in reply.text
