import json
import os
from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import agent
from nutrition import InputError, calculate, replace_food

QWEN35 = "qwen3.5:9b-q4_K_M"
ENV_SETTINGS = ("MODEL", "THINK", "TEMPERATURE", "NUM_CTX", "NUM_PREDICT", "KEEP_ALIVE")
ITEMS = [{"food": "김치찌개", "quantity": 0.2, "unit": "kg"}, {"food": "쌀밥", "quantity": 150, "unit": "g"}]
MEAL = calculate([{"food": "닭가슴살", "quantity": 100, "unit": "g"},
                  {"food": "흰쌀밥", "quantity": 100, "unit": "g"}])
SPLIT_MEAL = calculate([{"food": "닭가슴살", "quantity": 120, "unit": "g"},
                        {"food": "닭가슴살", "quantity": 80, "unit": "g"},
                        {"food": "흰쌀밥", "quantity": 100, "unit": "g"}])
GOALS = {"kcal": 820, "protein_g": 60}

# The same selection and argument checks run on the wire-format fixture and both real models.
CASES = [
    ("intake", "김치찌개 0.2kg과 쌀밥 150g의 영양을 계산해 줘.", "calculate_meal", {"items": ITEMS}, 371),
    ("tofu", "두부 100g의 열량과 단백질을 계산해 줘.", "calculate_meal",
     {"items": [{"food": "두부", "quantity": 100, "unit": "g"}]}, 144),
    ("alias", "제육볶음 영양성분을 조회해 줘.", "find_food", {"name": "제육볶음"}, None),
    ("unknown", "미등록디저트 100g의 영양을 계산해 줘.", "calculate_meal",
     {"items": [{"food": "미등록디저트", "quantity": 100, "unit": "g"}]}, None),
    ("unclear", "두부를 조금 먹었어. 먹은 양의 영양을 계산해 줘.", "ask_clarification", {"missing": "quantity"}, None),
    ("serving", "김치찌개 1인분의 영양을 계산해 줘.", "calculate_meal",
     {"items": [{"food": "김치찌개", "quantity": 1, "unit": "serving"}]}, None),
    ("swap", "닭가슴살 대신 두부로 바꿔 줘.", "replace_food", {"old_food": "닭가슴살", "new_food": "두부"}, 274),
    ("swap-weight", "닭가슴살 대신 두부 150g으로 바꿔 줘.", "replace_food",
     {"old_food": "닭가슴살", "new_food": "두부", "quantity": 150, "unit": "g"}, 346),
    ("goal", "오늘 남은 영양 목표에 맞춰 저녁을 추천해 줘.", "recommend_for_goals", {}, None),
]

SWAP_ARGS = {"old_food": "닭가슴살", "new_food": "두부"}
SWAP_CASES = [
    ("swap-kg", "닭가슴살 대신 두부 0.15kg으로 바꿔 줘.", "replace_food",
     {**SWAP_ARGS, "quantity": 0.15, "unit": "kg"}, 346),
    ("swap-explicit-same", "닭가슴살 대신 두부 100g을 넣어 줘.", "replace_food",
     {**SWAP_ARGS, "quantity": 100, "unit": "g"}, 274),
    ("swap-split-keep", "닭가슴살 대신 두부로 바꾸고 중량은 유지해 줘.", "replace_food", SWAP_ARGS, 418),
    ("swap-split-total", "닭가슴살 대신 두부를 총 150g 넣어 줘.", "replace_food",
     {**SWAP_ARGS, "quantity": 150, "unit": "g"}, 346),
    ("ambiguous-swap", "닭가슴살 대신 두부를 조금 넣어 줘.", "ask_clarification", {"missing": "quantity"}, None),
    ("swap-old-weight", "닭가슴살 100g 대신 두부로 바꿔 줘.", "replace_food", SWAP_ARGS, 274),
]
SWAP_WEIGHTS = {
    "swap": [100], "swap-weight": [150], "swap-kg": [150], "swap-explicit-same": [100],
    "swap-split-keep": [120, 80], "swap-split-total": [150], "swap-old-weight": [100],
}


def _reference_meal(case):
    return SPLIT_MEAL if case[0].startswith("swap-split-") else MEAL


def _check_reply(case, reply):
    name, _, tool, arguments, kcal = case
    calls = [entry for entry in reply.tool_log if entry["tool"] == tool]
    if name == "serving" and not calls:
        assert any(entry["tool"] == "ask_clarification" and entry["input"].get("missing") == "quantity"
                   for entry in reply.tool_log), reply.text
    else:
        assert calls and calls[-1]["input"] == arguments, reply.tool_log
    if kcal is not None:
        assert reply.meal and reply.meal.totals["kcal"] == pytest.approx(kcal), reply.text
    if name == "alias":
        assert reply.food["name"] == "돼지고기볶음(제육볶음)"
    if name in {"unknown", "unclear", "serving"}:
        assert reply.meal is None and reply.needs_clarification
    if name == "goal":
        assert reply.candidates and reply.kind == "recommendation", reply.text
        assert reply.impact.before["kcal"] == 525
    if name.startswith("swap"):
        assert reply.kind == "recommendation"
        weights = [(line.food["name"], line.grams) for line in reply.meal.lines]
        expected = [("두부", grams) for grams in SWAP_WEIGHTS[name]] + [("흰쌀밥", 100)]
        assert weights == expected
        expected_meal = calculate([{"food": food, "quantity": grams, "unit": "g"} for food, grams in expected])
        assert reply.meal.totals == pytest.approx(expected_meal.totals)
        assert reply.previous_meal is _reference_meal(case)
        assert not any("effective_input" in call for call in calls), calls
    if name == "ambiguous-swap":
        assert reply.meal is None and reply.needs_clarification


def test_environment_configuration(monkeypatch):
    for key in ENV_SETTINGS:
        monkeypatch.delenv(f"NUTRIAGENT_{key}", raising=False)
    assert agent.configured_inference() == agent.InferenceConfig("qwen3:8b", False, 0, 4096, 512, "30m")
    values = (QWEN35, "1", "0.2", "8192", "1024", "1h15m")
    for key, value in zip(ENV_SETTINGS, values, strict=True):
        monkeypatch.setenv(f"NUTRIAGENT_{key}", value)
    assert agent.configured_inference() == agent.InferenceConfig(QWEN35, True, 0.2, 8192, 1024, "1h15m")


@pytest.mark.parametrize("key,value", [
    ("MODEL", " "), ("THINK", "auto"), ("TEMPERATURE", "nan"),
    ("NUM_CTX", "0"), ("NUM_PREDICT", "ten"), ("KEEP_ALIVE", "invalid"),
])
def test_invalid_environment_setting(monkeypatch, key, value):
    name = f"NUTRIAGENT_{key}"
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        agent.configured_inference()


@pytest.mark.parametrize("case", CASES + SWAP_CASES, ids=[case[0] for case in CASES + SWAP_CASES])
def test_ollama_transport_and_tools(monkeypatch, case):
    _, prompt, tool, arguments, _ = case
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        # A lookup-only turn may make a second call to allow a follow-on calculation.
        calls = [] if len(requests) > 1 else [{"function": {"name": tool, "arguments": arguments}}]
        return httpx.Response(200, json={
            "model": QWEN35, "done": True, "message": {"role": "assistant", "tool_calls": calls},
            "prompt_eval_count": 374, "eval_count": 49, "load_duration": 0, "prompt_eval_duration": 2_200_000,
            "eval_duration": 3_400_000, "total_duration": 6_000_000,
        })

    client = agent.ollama.Client(host="http://ollama.test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(agent.ollama, "Client", lambda **_: client)
    monkeypatch.setenv("NUTRIAGENT_MODEL", QWEN35)
    monkeypatch.setenv("NUTRIAGENT_NUM_CTX", "6144")
    settings = agent.configured_inference()
    meal = _reference_meal(case)
    reply = agent.run_turn([{"role": "user", "content": prompt}], meal,
                           mode=agent.Mode.OLLAMA, goals=GOALS, today_totals=MEAL.totals, settings=settings)
    _check_reply(case, reply)
    assert reply.model == requests[0]["model"] == QWEN35
    assert requests[0]["think"] is settings.think
    assert requests[0]["keep_alive"] == settings.keep_alive
    assert requests[0]["options"] == {
        "num_ctx": 6144, "num_predict": settings.num_predict, "temperature": settings.temperature,
    }
    assert f'직전 식단: 닭가슴살 {meal.lines[0].grams:g}g' in requests[0]["messages"][0]["content"]
    assert "돼지고기볶음(제육볶음)" not in requests[0]["messages"][0]["content"]
    assert reply.inference == [agent.InferenceMetrics(374, 49, 0, 2.2, 3.4, 6.0)] * len(requests)
    assert reply.agent_ms >= 0
    if tool == "find_food":
        assert json.loads(requests[1]["messages"][-1]["content"]) == {
            "name": "돼지고기볶음(제육볶음)", "serving_g": None,
        }


@pytest.mark.parametrize("prompt,expected", [
    ("닭가슴살 대신 두부로 변경해 줘.", [120, 80]),
    ("닭가슴살 120g 대신 두부로 변경해 줘.", [120, 80]),
    ("닭가슴살 120g을 두부로 바꿔 줘.", [120, 80]),
    ("닭가슴살 대신 두부 100g으로 변경해 줘.", [100]),
    ("닭가슴살 대신 두부150g으로 변경해 줘.", [150]),
    ("닭가슴살 대신 0.15kg의 두부로 변경해 줘.", [150]),
    ("닭가슴살 대신 두부는 적당히 넣어 줘.", None),
    ("닭가슴살 대신 두부 150g~200으로 변경해 줘.", None),
    ("닭가슴살 대신 두부로 바꾸고 쌀밥 150g은 유지해 줘.", None),
])
def test_swap_only_uses_user_grounded_weights(monkeypatch, prompt, expected):
    copied = {**SWAP_ARGS, "quantity": 100, "unit": "g"}
    response = agent.ollama.ChatResponse(message={
        "role": "assistant",
        "tool_calls": [{"function": {"name": "replace_food", "arguments": copied}}],
    })
    monkeypatch.setattr(agent.ollama, "Client", lambda **_: SimpleNamespace(chat=lambda **_: response))
    original = asdict(SPLIT_MEAL)
    reply = agent.run_turn([{"role": "user", "content": prompt}], SPLIT_MEAL, mode=agent.Mode.OLLAMA)
    assert reply.tool_log[0]["input"] == copied
    if expected is None:
        assert reply.needs_clarification and reply.meal is None
    else:
        assert [line.grams for line in reply.meal.lines if line.food["name"] == "두부"] == expected
        assert reply.kind == "recommendation"
        if len(expected) > 1:
            assert reply.tool_log[0]["effective_input"] == SWAP_ARGS
        elif expected == [100]:
            assert "effective_input" not in reply.tool_log[0] and "지정한 중량" in reply.text
        else:
            assert reply.tool_log[0]["effective_input"] != copied
    assert asdict(SPLIT_MEAL) == original


def test_copied_amount_does_not_change_saved_intake(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "OLLAMA")
    copied = {**SWAP_ARGS, "quantity": 100, "unit": "g"}
    responses = iter([
        ("calculate_meal", {"items": [{"food": line.food["name"], "quantity": line.grams, "unit": "g"}
                                        for line in SPLIT_MEAL.lines]}),
        ("replace_food", copied),
    ])

    def chat(**_):
        name, args = next(responses)
        return agent.ollama.ChatResponse(message={
            "role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}],
        })

    monkeypatch.setattr(agent.ollama, "Client", lambda **_: SimpleNamespace(chat=chat))
    screen = AppTest.from_file("app.py").run()
    screen.chat_input[0].set_value("닭가슴살 120g과 80g, 흰쌀밥 100g을 기록할게.").run()
    screen.button(key="record-0").click().run()
    before = asdict(screen.session_state.records[0])
    screen.chat_input[0].set_value("닭가슴살 대신 두부로 바꿔 줘.").run()
    assert not screen.exception and list(screen.session_state.records) == [0]
    assert asdict(screen.session_state.records[0]) == before
    reply = screen.session_state.turns[-1][1]
    assert reply.meal.totals["kcal"] == pytest.approx(418)
    assert reply.tool_log[0]["input"] == copied
    assert reply.tool_log[0]["effective_input"] == SWAP_ARGS
    assert not any(button.key == "record-1" for button in screen.button)


def test_explicit_amount_in_clarification_followup(monkeypatch):
    response = agent.ollama.ChatResponse(message={
        "role": "assistant",
        "tool_calls": [{"function": {"name": "replace_food", "arguments": SWAP_ARGS}}],
    })
    monkeypatch.setattr(agent.ollama, "Client", lambda **_: SimpleNamespace(chat=lambda **_: response))
    reply = agent.run_turn([
        {"role": "user", "content": "닭가슴살 대신 두부를 조금 넣어 줘."},
        {"role": "assistant", "content": agent.REPLACEMENT_QUESTION},
        {"role": "user", "content": "150g이야."},
    ], SPLIT_MEAL, mode=agent.Mode.OLLAMA)
    assert reply.meal.totals["kcal"] == pytest.approx(346)
    assert reply.tool_log[0]["input"] == SWAP_ARGS
    assert reply.tool_log[0]["effective_input"] == {**SWAP_ARGS, "quantity": 150, "unit": "g"}


def test_explicit_amount_replaces_total_across_matching_lines():
    meal = calculate([{"food": "닭가슴살", "quantity": grams, "unit": "g"} for grams in (120, 80)])
    kept = replace_food(meal, "닭가슴살", "두부")
    override = replace_food(meal, "닭가슴살", "두부", quantity=0.15, unit="kg")
    assert [line.grams for line in kept.lines] == [120, 80]
    assert [line.grams for line in override.lines] == [150]
    assert override.totals["kcal"] == 216
    assert meal.totals["kcal"] == 330
    with pytest.raises(InputError, match="수량과 단위를 함께"):
        replace_food(meal, "닭가슴살", "두부", quantity=150)
    with pytest.raises(InputError, match="인분 중량은 검증되지"):
        replace_food(meal, "닭가슴살", "김치찌개", quantity=1, unit="serving")


def test_ui_shows_configured_model_in_mock(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "MOCK")
    monkeypatch.setenv("NUTRIAGENT_MODEL", QWEN35)
    screen = AppTest.from_file("app.py").run()
    assert not screen.exception
    assert any(QWEN35 in caption.value for caption in screen.caption)
    assert any("MOCK" in caption.value for caption in screen.caption)
    assert "이전 식단 필요" in screen.button(key="example-2").label
    assert any(agent.PDF_MIRROR_URL in caption.value for caption in screen.caption)
    assert not any(expander.label == "Ollama 추론 지표" for expander in screen.expander)


def test_ui_preserves_clarification_context_and_shows_live_call_metrics(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "OLLAMA")
    monkeypatch.setenv("NUTRIAGENT_MODEL", QWEN35)
    sent = []

    def respond(request):
        body = json.loads(request.content)
        sent.append(body["messages"])
        last = body["messages"][-1]["content"]
        if last == "200g이야":
            tool = {"name": "calculate_meal", "arguments": {
                "items": [{"food": "김치찌개", "quantity": 200, "unit": "g"}],
            }}
        else:
            tool = {"name": "ask_clarification", "arguments": {"missing": "quantity"}}
        return httpx.Response(200, json={
            "model": QWEN35, "done": True, "prompt_eval_count": 230, "eval_count": 20,
            "message": {"role": "assistant", "tool_calls": [{"function": tool}]},
        })

    client = agent.ollama.Client(host="http://ollama.test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(agent.ollama, "Client", lambda **_: client)
    screen = AppTest.from_file("app.py").run()
    assert screen.caption[0].value == f"실행 모드: OLLAMA · {QWEN35} 요청"
    screen.chat_input[0].set_value("김치찌개를 먹었어").run()
    screen.chat_input[0].set_value("200g이야").run()
    assert not screen.exception
    assert [message["content"] for message in sent[-1] if message["role"] == "user"] == ["김치찌개를 먹었어", "200g이야"]
    reply = screen.session_state.turns[-1][1]
    assert reply.meal.totals["kcal"] == 122
    assert reply.inference[0].prompt_tokens == 230
    assert reply.inference[0].total_ms is None
    assert any(expander.label == "Ollama 추론 지표" for expander in screen.expander)


@pytest.mark.skipif(os.getenv("NUTRIAGENT_LIVE_OLLAMA") != "1", reason="requires a running Ollama and local model")
@pytest.mark.parametrize("model", (QWEN35, agent.MODEL_NAME))
def test_live_qwen_inference(model):
    if not agent.is_model_available(model):
        pytest.skip(f"model not installed: {model}")
    settings = replace(agent.configured_inference(), model=model)
    failures = []
    for case in CASES + SWAP_CASES:
        reply = agent.run_turn([{"role": "user", "content": case[1]}], _reference_meal(case),
                               mode=agent.Mode.OLLAMA, goals=GOALS, today_totals=MEAL.totals, settings=settings,
                               architecture=agent.ToolArchitecture.LEGACY)
        print(json.dumps({"model": model, "case": case[0], "settings": asdict(settings),
                          "agent_ms": reply.agent_ms, "calls": [asdict(call) for call in reply.inference]}))
        try:
            assert reply.inference, reply.text
            _check_reply(case, reply)
        except AssertionError as error:
            failures.append(f"{case[0]}: {error}")
    assert not failures, "\n".join(failures)
