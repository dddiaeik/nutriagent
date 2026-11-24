import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import agent
from nutrition import calculate

A = agent.ToolArchitecture.LEGACY
B = agent.ToolArchitecture.SPLIT
ARGS = {"old_food": "닭가슴살", "new_food": "두부"}
MEAL = calculate([{"food": "닭가슴살", "quantity": weight, "unit": "g"} for weight in (65, 105)])


def client_with_calls(*calls):
    return SimpleNamespace(chat=lambda **_: agent.ollama.ChatResponse(
        message={"role": "assistant", "tool_calls": [
            {"function": {"name": tool, "arguments": args}} for tool, args in calls
        ]}
    ))


def run(prompt, tool, args, *, architecture=B, meal=MEAL):
    return agent.run_turn([{"role": "user", "content": prompt}], meal, architecture=architecture,
                          mode=agent.Mode.OLLAMA, client=client_with_calls((tool, args)))


def test_legacy_is_default_with_frozen_prompt_and_schemas(monkeypatch):
    monkeypatch.delenv("NUTRIAGENT_TOOL_ARCHITECTURE", raising=False)
    assert agent.configured_tool_architecture() == A
    prompt, tools = agent.tool_definition(A)
    assert hashlib.sha256(prompt.encode()).hexdigest() == "0800f951a6ccbe201099186c46d706e5ea996396bb4a54b7c389ba9fe5678bbe"
    schema = json.dumps(tools, sort_keys=True, ensure_ascii=False)
    assert hashlib.sha256(schema.encode()).hexdigest() == "3e40b35987b7c34d654d5d8276f98c611c9c390a44fb3511663642923e0aab48"
    monkeypatch.setenv("NUTRIAGENT_TOOL_ARCHITECTURE", "OTHER")
    with pytest.raises(ValueError, match="NUTRIAGENT_TOOL_ARCHITECTURE"):
        agent.configured_tool_architecture()


def test_split_schema_required_arguments_and_unchanged_other_tools():
    prompt, tools = agent.tool_definition(B)
    wire = {tool["function"]["name"]: agent.ollama.Tool.model_validate(tool).model_dump(exclude_none=True)
            for tool in tools}
    for tool, expected in [("replace_food", {"old_food", "new_food"}),
                           ("replace_food_with_weight", {"old_food", "new_food", "quantity", "unit"})]:
        parameters = wire[tool]["function"]["parameters"]
        assert set(parameters["properties"]) == set(parameters["required"]) == expected
    assert "replace_food_with_weight" in prompt
    assert [tool for tool in tools if tool["function"]["name"] not in {"replace_food", "replace_food_with_weight"}] == [
        tool for tool in agent.TOOLS if tool["function"]["name"] != "replace_food"
    ]


def test_split_copies_no_weight_even_if_the_model_selects_weight_tool():
    reply = run("기존 닭가슴살을 두부로 교체해 줘.", "replace_food_with_weight",
                {**ARGS, "quantity": 65, "unit": "g"})
    assert [line.grams for line in reply.meal.lines] == [65, 105]
    assert reply.meal.totals["kcal"] == pytest.approx(244.8)
    assert reply.raw_calls == [{"tool": "replace_food_with_weight", "input": {**ARGS, "quantity": 65, "unit": "g"}}]
    assert reply.tool_log[0]["executed_tool"] == "replace_food"
    assert reply.tool_log[0]["effective_input"] == ARGS


@pytest.mark.parametrize("tool,args", [
    ("replace_food", ARGS),
    ("replace_food_with_weight", ARGS),
    ("replace_food_with_weight", {**ARGS, "quantity": 600, "unit": "kg"}),
])
def test_split_fills_only_an_explicit_target_amount(tool, args):
    reply = run("닭가슴살 대신 두부를 총 135g 올려줘.", tool, args)
    assert [line.grams for line in reply.meal.lines] == [135]
    assert reply.meal.totals["protein_g"] == pytest.approx(17.27 * 1.35)
    assert reply.raw_calls[0]["input"] == args
    assert reply.tool_log[0]["executed_tool"] == "replace_food_with_weight"
    assert reply.tool_log[0]["effective_input"] == {**ARGS, "quantity": 135, "unit": "g"}


@pytest.mark.parametrize("prompt", [
    "닭가슴살 대신 두부를 두 배 넣어 줘.",
    "닭가슴살을 두부로 대체하고 두부 95~110g으로 해 줘.",
    "닭가슴살 대신 두부 155g은 제외하고 바꿔 줘.",
    "닭가슴살 대신 두부를 175g보다 덜 넣어 줘.",
])
def test_split_blocks_unsupported_amounts(prompt):
    reply = run(prompt, "replace_food_with_weight", {**ARGS, "quantity": 155, "unit": "g"})
    assert reply.meal is None and reply.needs_clarification
    assert reply.text == agent.REPLACEMENT_QUESTION
    assert reply.tool_log[0]["validation"] == "blocked"
    assert "executed_tool" not in reply.tool_log[0]


def test_split_negated_weight_retains_the_old_amount_without_changing_legacy():
    prompt = "닭가슴살 대신 두부 91g은 아니고 원래 무게로 바꿔 줘."
    proposed = {**ARGS, "quantity": 91, "unit": "g"}
    assert [line.grams for line in run(prompt, "replace_food", proposed, architecture=A).meal.lines] == [91]
    split = run(prompt, "replace_food_with_weight", proposed)
    assert [line.grams for line in split.meal.lines] == [65, 105]


def test_split_blocks_wrong_tool_and_keeps_raw_calls_even_when_terminated():
    args = {"items": [{"food": "두부", "quantity": 65, "unit": "g"}]}
    reply = agent.run_turn([{"role": "user", "content": "닭가슴살 대신 두부로 교체해 줘."}], MEAL,
                           mode=agent.Mode.OLLAMA, architecture=B,
                           client=client_with_calls(("calculate_meal", args), ("replace_food", ARGS)))
    assert reply.meal is None and reply.needs_clarification
    assert reply.raw_calls == [{"tool": "calculate_meal", "input": args}, {"tool": "replace_food", "input": ARGS}]
    assert len(reply.tool_log) == 1 and reply.tool_log[0]["validation"] == "blocked"


def test_split_no_previous_meal_asks_for_reference():
    result = run("닭가슴살 대신 두부로 교체해 줘.", "replace_food", ARGS, meal=None)
    assert result.meal is None and result.needs_clarification and result.text == agent.QUESTIONS["meal"]


def test_split_streamlit_can_replace_without_changing_confirmed_record(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "MOCK")
    monkeypatch.setenv("NUTRIAGENT_TOOL_ARCHITECTURE", "SPLIT")
    screen = AppTest.from_file("app.py").run()
    screen.chat_input[0].set_value("닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘").run()
    screen.button(key="record-0").click().run()
    snapshot = asdict(screen.session_state.records[0])
    screen.chat_input[0].set_value("닭가슴살 대신 두부 150g").run()
    assert not screen.exception and list(screen.session_state.records) == [0]
    assert asdict(screen.session_state.records[0]) == snapshot
    reply = screen.session_state.turns[-1][1]
    assert reply.raw_calls == [{"tool": "replace_food_with_weight",
                                "input": {**ARGS, "quantity": 150, "unit": "g"}}]
    assert reply.meal.totals["kcal"] == pytest.approx(346)
    assert not any(button.key == "record-1" for button in screen.button)
