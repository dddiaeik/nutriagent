import hashlib
import os

import pymupdf
import pytest
from ollama import ChatResponse
from streamlit.testing.v1 import AppTest

import agent
from nutrition import FOODS, InputError, calculate, compare_goals, find_food, replace_food


def item(food, quantity=100, unit="g"):
    return {"food": food, "quantity": quantity, "unit": unit}


def tool_reply(tool_name, **arguments):
    return ChatResponse(model=agent.MODEL_NAME, message={
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": tool_name, "arguments": arguments}}],
    })


def history(text):
    return [{"role": "user", "content": text}]


def test_calculation_and_goals():
    assert len(FOODS) == 12
    assert len({food["ndb"] for food in FOODS}) == 12
    meal = calculate([item("닭가슴살"), item("흰쌀밥", 0.1, "kg")])
    assert meal.totals == pytest.approx({"kcal": 295, "carbs_g": 28.17, "protein_g": 33.71, "fat_g": 3.85})
    assert compare_goals(meal.totals, {"kcal": 300, "protein_g": 30}) == pytest.approx({
        "kcal": -5, "protein_g": 3.71,
    })


def test_two_servings():
    meal = calculate([item("닭가슴살", 2, "serving")])
    assert meal.lines[0].grams == 200
    assert meal.totals["protein_g"] == pytest.approx(62.04)


@pytest.mark.parametrize("quantity,unit", [(None, "g"), (True, "g"), (0, "g"), (-1, "g"),
                                          (float("nan"), "g"), (float("inf"), "g"), (1, "그릇")])
def test_invalid_quantity(quantity, unit):
    with pytest.raises(InputError):
        calculate([item("두부", quantity, unit)])


def test_unregistered_food():
    with pytest.raises(InputError, match="등록되지 않았습니다"):
        find_food("떡볶이")
    with pytest.raises(InputError):
        calculate([item("밥")])


def test_replacement_keeps_weight_and_original_meal():
    before = calculate([item("닭가슴살", 150), item("흰쌀밥")])
    after = replace_food(before, "닭가슴살", "두부")
    assert after.lines[0].grams == 150
    assert after.totals["kcal"] == 346
    assert before.lines[0].food["name"] == "닭가슴살"
    assert before.totals["kcal"] == 377.5


def test_mocked_lookup_then_calculation(monkeypatch):
    responses = iter([
        tool_reply("find_food", name="두부"),
        tool_reply("calculate_meal", items=[item("두부", 2, "serving")]),
    ])
    monkeypatch.setattr(agent.CLIENT, "chat", lambda **_: next(responses))
    reply = agent.run_turn(history("두부 2인분을 계산해 줘"))
    assert reply.meal.totals["kcal"] == 288
    assert [entry["tool"] for entry in reply.tool_log] == ["find_food", "calculate_meal"]


def test_mocked_clarification_unknown_food_and_model_text(monkeypatch):
    responses = iter([
        tool_reply("ask_clarification", missing="quantity"),
        tool_reply("calculate_meal", items=[item("떡볶이")]),
        ChatResponse(message={"role": "assistant", "content": "12345 kcal"}),
    ])
    monkeypatch.setattr(agent.CLIENT, "chat", lambda **_: next(responses))
    ambiguous = agent.run_turn(history("두부를 조금 먹었어"))
    unknown = agent.run_turn(history("떡볶이 100g을 먹었어"))
    unverified = agent.run_turn(history("영양성분을 알려 줘"))
    assert ambiguous.meal is None and "양과 단위" in ambiguous.text
    assert unknown.meal is None and "등록되지 않았습니다" in unknown.text
    assert "12345" not in unverified.text


def test_mocked_ui_confirmation_and_recommendation(monkeypatch):
    responses = iter([
        tool_reply("calculate_meal", items=[item("닭가슴살")]),
        tool_reply("replace_food", old_food="닭가슴살", new_food="두부"),
        tool_reply("recommend_meal", items=[item("두부"), item("흰쌀밥")]),
    ])
    monkeypatch.setattr(agent.CLIENT, "chat", lambda **_: next(responses))
    screen = AppTest.from_file("app.py").run()
    assert screen.title[0].value == "NutriAgent Lite"
    screen.chat_input[0].set_value("닭가슴살 100g을 먹었어").run()
    assert not screen.exception
    assert not screen.session_state.records
    screen.button(key="record-0").click().run()
    screen.run()
    assert len(screen.session_state.records) == 1
    assert screen.session_state.records[0].totals["kcal"] == 165
    assert all(button.key != "record-0" for button in screen.button)
    screen.chat_input[0].set_value("닭가슴살 대신 두부").run()
    screen.chat_input[0].set_value("두부와 흰쌀밥을 추천해 줘").run()
    assert not screen.exception
    assert len(screen.session_state.records) == 1
    assert all(not (button.key or "").startswith("record-") for button in screen.button)
    assert screen.session_state.turns[1][1].meal.totals["kcal"] == 144
    assert screen.session_state.turns[2][1].meal.totals["kcal"] == 274


def test_pdf_requires_matching_file(tmp_path, monkeypatch):
    pdf = tmp_path / "reference.pdf"
    with pytest.raises(InputError, match="PDF가 없습니다"):
        agent.search_guidelines(pdf, "whole grains")
    with pymupdf.open() as document:
        document.new_page().insert_text((50, 50), "An example about whole grains.")
        document.save(pdf)
    with pytest.raises(InputError, match="일치하지 않습니다"):
        agent.search_guidelines(pdf, "whole grains")
    monkeypatch.setattr(agent, "PDF_SHA256", hashlib.sha256(pdf.read_bytes()).hexdigest())
    assert agent.search_guidelines(pdf, "Whole Grains") == [
        {"page": 1, "quote": "An example about whole grains."},
    ]
    assert agent.search_guidelines(pdf, "protein") == []


@pytest.mark.skipif(os.getenv("NUTRIAGENT_LIVE_OLLAMA") != "1", reason="requires a running Ollama with qwen3:8b")
def test_live_qwen_inference():
    assert agent.is_model_available()
    reply = agent.run_turn(history("두부 100g의 열량과 단백질을 계산해 줘."))
    assert reply.kind == "intake", reply.text
    assert reply.meal.totals["kcal"] == 144
    assert reply.meal.totals["protein_g"] == pytest.approx(17.27)
