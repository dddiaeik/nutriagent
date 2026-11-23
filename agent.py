"""Run shared nutrition tools using scripted responses or live Qwen3."""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

import httpx
import ollama
import pymupdf

from nutrition import DATA, FOODS, InputError, Meal, calculate, find_food, replace_food

MODEL_NAME = "qwen3:8b"
PDF_PATH = DATA / "reference.pdf"
PDF_TITLE = "USDA/HHS Dietary Guidelines for Americans, 2025–2030"
PDF_URL = "https://cdn.realfood.gov/DGA.pdf"
PDF_SHA256 = "c34f1bec5c9416265670b7fcb24556bb8616ba95e8de2f2890460b6bbca1a472"


class Mode(StrEnum):
    MOCK = "MOCK"
    OLLAMA = "OLLAMA"


def configured_mode() -> Mode:
    value = os.getenv("NUTRIAGENT_MODE", Mode.MOCK).strip().upper()
    try:
        return Mode(value)
    except ValueError:
        raise ValueError("NUTRIAGENT_MODE를 MOCK 또는 OLLAMA로 설정해 주세요.") from None


def is_model_available() -> bool:
    """Check whether the configured Ollama server has the model installed."""
    return any(model.model == MODEL_NAME for model in ollama.Client(timeout=5).list().models)


def _tool(name, description, properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
            },
        },
    }


TEXT = {"type": "string"}
ITEMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "food": TEXT,
            "quantity": {"type": "number", "exclusiveMinimum": 0},
            "unit": {"type": "string", "enum": ["g", "kg", "serving"]},
        },
        "required": ["food", "quantity", "unit"],
    },
}
QUESTIONS = {
    "food": "어떤 음식인지 정확히 알려 주세요. 예를 들어 흰쌀밥인지 현미밥인지 알려 주세요.",
    "quantity": "각 음식의 양과 단위를 알려 주세요. 예를 들어 두부 150g처럼 입력해 주세요.",
    "meal": "어떤 식단을 기준으로 바꿀지 알려 주세요.",
}
TOOLS = [
    _tool("find_food", "Look up the explicitly named food; preserve unknown names.", {"name": TEXT}),
    _tool("calculate_meal", "Calculate stated intake. Never assume unspecified amounts.", {"items": ITEMS}),
    _tool("recommend_meal", "Calculate a proposed meal, never an intake record.", {"items": ITEMS}),
    _tool("replace_food", "Substitute foods at the same weight in the previous meal.", {"old_food": TEXT, "new_food": TEXT}),
    _tool("search_guidelines", "Search the reference PDF by a short English keyword.", {"query": TEXT}),
    _tool("ask_clarification", "Ask for missing or ambiguous information.", {
        "missing": {"type": "string", "enum": list(QUESTIONS)},
    }),
]

SYSTEM_PROMPT = """You interpret Korean or English requests for the NutriAgent Lite demo.
Use only the tools for lookups, calculations, recommendations, substitutions, and PDF searches.
For intake, keep the user's actual foods and quantities. Never infer unknown foods, cooking methods,
weights, or serving counts. '밥' alone is ambiguous, and units such as 그릇, 개, or '조금' need
clarification. An explicitly stated 인분 is a serving (100 g in this demo). If food or amount is unclear
call ask_clarification. Pass unregistered foods unchanged; never replace them with a similar food.
Only propose amounts for recommendations, using foods from the catalog. For an explicit '대신'
request with a previous meal, use replace_food, keeping each item's gram weight. No tool records intake;
that requires an explicit UI confirmation. Never invent nutrients, guideline text, or citations.
For guideline questions use a short English keyword for search_guidelines. For ordinary lookup use
find_food. For calculation use calculate_meal. For a candidate use recommend_meal.
"""


MOCK_SCENARIOS = {
    "닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘": ("calculate_meal", {"items": [
        {"food": "닭가슴살", "quantity": 2, "unit": "serving"},
        {"food": "흰쌀밥", "quantity": 100, "unit": "g"},
    ]}),
    "두부와 흰쌀밥을 추천해 줘": ("recommend_meal", {"items": [
        {"food": "두부", "quantity": 100, "unit": "g"},
        {"food": "흰쌀밥", "quantity": 100, "unit": "g"},
    ]}),
    "닭가슴살 대신 두부": ("replace_food", {"old_food": "닭가슴살", "new_food": "두부"}),
    "두부 영양소를 조회해 줘": ("find_food", {"name": "두부"}),
    "두부를 조금 먹었어": ("ask_clarification", {"missing": "quantity"}),
    "떡볶이 100g을 계산해 줘": ("calculate_meal", {"items": [
        {"food": "떡볶이", "quantity": 100, "unit": "g"},
    ]}),
    "영양 가이드에서 whole grains를 검색해 줘": ("search_guidelines", {"query": "whole grains"}),
}


def _mock_message(messages: list) -> ollama.Message:
    last = messages[-1]
    if last["role"] == "user":
        scenario = MOCK_SCENARIOS.get(last["content"].strip())
        if scenario:
            name, args = scenario
            return ollama.Message(role="assistant", tool_calls=[
                ollama.Message.ToolCall(function=ollama.Message.ToolCall.Function(name=name, arguments=args))
            ])
    return ollama.Message(role="assistant")


def search_guidelines(path: Path, query: str) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 100:
        raise InputError("검색할 짧은 영문 키워드를 알려 주세요.")
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise InputError("영양기준 PDF가 없습니다. README의 문서 준비 방법을 참고해 주세요.") from None
    except OSError:
        raise InputError("영양기준 PDF를 읽을 수 없습니다.") from None
    if hashlib.sha256(data).hexdigest() != PDF_SHA256:
        raise InputError("이 데모의 영양기준 PDF와 일치하지 않습니다. README에서 지원하는 문서를 확인해 주세요.")
    keyword = re.compile(re.escape(query.strip()), re.IGNORECASE)
    hits = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            for page in document:
                content = " ".join(page.get_text().split())
                match = keyword.search(content)
                if match:
                    start = max(0, match.start() - 70)
                    end = match.end() + 110
                    hits.append({"page": page.number + 1, "quote": content[start:end]})
                if len(hits) == 3:
                    break
    except (pymupdf.FileDataError, OSError):
        raise InputError("영양기준 PDF를 열 수 없습니다.") from None
    return hits


@dataclass
class Reply:
    mode: Mode
    text: str = "음식과 섭취량을 알려 주시거나, 조회 또는 추천 요청을 구체적으로 입력해 주세요."
    meal: Meal | None = None
    kind: str | None = None
    food: dict | None = None
    hits: list[dict] = field(default_factory=list)
    tool_log: list[dict] = field(default_factory=list)


def _execute(name, args, reply, previous_meal, pdf_path):
    match name:
        case "find_food":
            reply.food = find_food(args.get("name"))
            reply.text = "등록 식품을 찾았습니다."
            return reply.food
        case "calculate_meal" | "recommend_meal":
            reply.meal = calculate(args.get("items"))
            reply.kind = "intake" if name == "calculate_meal" else "recommendation"
            reply.text = "섭취량을 계산했습니다." if reply.kind == "intake" else "추천 후보의 영양소를 계산했습니다."
            return asdict(reply.meal)
        case "replace_food":
            if previous_meal is None:
                raise InputError(QUESTIONS["meal"])
            reply.meal = replace_food(previous_meal, args.get("old_food"), args.get("new_food"))
            reply.kind = "recommendation"
            reply.text = "이전 식단에서 요청한 음식을 같은 중량으로 바꿔 추천 후보를 다시 계산했습니다."
            return asdict(reply.meal)
        case "search_guidelines":
            reply.hits = search_guidelines(pdf_path, args.get("query"))
            reply.text = "PDF 검색 결과입니다." if reply.hits else "PDF에서 해당 키워드를 찾지 못했습니다."
            return reply.hits
        case "ask_clarification":
            missing = args.get("missing")
            question = QUESTIONS.get(missing) if isinstance(missing, str) else None
            raise InputError(question or "음식 이름과 양을 구체적으로 알려 주세요.")
        case _:
            raise InputError("요청을 처리할 수 없습니다. 음식 이름과 양을 다시 알려 주세요.")


def run_turn(history: list[dict], previous_meal: Meal | None = None, *,
             mode: Mode | None = None, goals: dict | None = None, pdf_path: Path = PDF_PATH) -> Reply:
    """Use tool calls as proposals; present only Python-verified results."""
    catalog = ", ".join(food["name"] for food in FOODS)
    previous = [(line.food["name"], line.grams) for line in previous_meal.lines] if previous_meal else []
    context = f"Catalog: {catalog}. Previous meal (grams): {previous}. User goals: {goals or {}}."
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + context}, *history]
    mode = configured_mode() if mode is None else Mode(mode)
    client = ollama.Client(timeout=90) if mode == Mode.OLLAMA else None
    reply = Reply(mode)
    if mode == Mode.MOCK:
        reply.text = "등록된 MOCK 예시를 입력해 주세요. 화면의 예시 목록에서 복사할 수 있습니다."
    for _ in range(3):
        try:
            if client is None:
                message = _mock_message(messages)
            else:
                message = client.chat(model=MODEL_NAME, messages=messages, tools=TOOLS,
                                      think=False, options={"temperature": 0}).message
        except (ConnectionError, httpx.RequestError, ollama.ResponseError):
            return Reply(mode, text=f"Ollama에 연결해 {MODEL_NAME} 모델을 실행할 수 없습니다. 서버와 모델 설치 상태를 확인해 주세요.",
                         tool_log=reply.tool_log)
        if not message.tool_calls:
            return reply
        messages.append(message)
        for call in message.tool_calls:
            name, args = call.function.name, call.function.arguments
            try:
                result = _execute(name, args, reply, previous_meal, pdf_path)
            except InputError as error:
                reply.tool_log.append({"tool": name, "input": args, "status": str(error)})
                return Reply(mode, text=str(error), tool_log=reply.tool_log)
            reply.tool_log.append({"tool": name, "input": args, "status": "완료"})
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
        if reply.meal is not None or reply.hits or name == "search_guidelines":
            return reply
        # A lookup can be the first step of a calculation.
    return reply
