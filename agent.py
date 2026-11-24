"""Run shared nutrition tools using scripted responses or live Qwen3."""

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from time import perf_counter_ns

import httpx
import ollama
import pymupdf

from nutrition import DATA, NUTRIENTS, InputError, Meal, calculate, find_food, replace_food
from nutrigap import Candidate, GoalImpact, evaluate_meal, rank_candidates

MODEL_NAME = "qwen3:8b"
PDF_PATH = DATA / "reference.pdf"
PDF_TITLE = "USDA/HHS Dietary Guidelines for Americans, 2025–2030"
PDF_URL = "https://cdn.realfood.gov/DGA.pdf"
PDF_SHA256 = "c34f1bec5c9416265670b7fcb24556bb8616ba95e8de2f2890460b6bbca1a472"
GUIDELINE_KEYWORDS = {
    "통곡물": "whole grains",
    "단백질": "protein",
    "식이섬유": "fiber",
    "첨가당": "added sugars",
    "건강한 지방": "healthy fats",
}
SENTENCE_BREAK = re.compile(r'(?<![A-Z]\.)(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bDr\.)(?<=[.!?])\s+(?=["“(]?[A-Z])')


class Mode(StrEnum):
    MOCK = "MOCK"
    OLLAMA = "OLLAMA"


def configured_mode() -> Mode:
    value = os.getenv("NUTRIAGENT_MODE", Mode.MOCK).strip().upper()
    try:
        return Mode(value)
    except ValueError:
        raise ValueError("NUTRIAGENT_MODE를 MOCK 또는 OLLAMA로 설정해 주세요.") from None


@dataclass(frozen=True)
class InferenceConfig:
    model: str = MODEL_NAME
    think: bool = False
    temperature: float = 0.0
    num_ctx: int = 4096
    num_predict: int = 512
    keep_alive: str | int = "30m"


def _numeric_setting(name, default, parse, is_valid, requirement):
    value = os.getenv(name, str(default))
    try:
        parsed = parse(value)
        if is_valid(parsed):
            return parsed
    except ValueError:
        pass
    raise ValueError(f"{name}: {requirement}")


def configured_inference() -> InferenceConfig:
    model = os.getenv("NUTRIAGENT_MODEL", MODEL_NAME).strip()
    if not model or any(char.isspace() for char in model):
        raise ValueError("NUTRIAGENT_MODEL에 공백 없는 Ollama 모델 이름을 입력해 주세요.")
    think = os.getenv("NUTRIAGENT_THINK", "false").strip().lower()
    if think not in {"true", "false", "1", "0"}:
        raise ValueError("NUTRIAGENT_THINK는 true, false, 1 또는 0이어야 합니다.")
    keep_alive = os.getenv("NUTRIAGENT_KEEP_ALIVE", "30m").strip()
    if keep_alive in {"0", "-1"}:
        keep_alive = int(keep_alive)
    elif not re.fullmatch(r"(?:\d+(?:\.\d+)?(?:ms|s|m|h))+", keep_alive):
        raise ValueError("NUTRIAGENT_KEEP_ALIVE에 30m 같은 기간, 0 또는 -1을 입력해 주세요.")
    return InferenceConfig(
        model=model, think=think in {"true", "1"}, keep_alive=keep_alive,
        temperature=_numeric_setting("NUTRIAGENT_TEMPERATURE", 0, float,
                                     lambda x: math.isfinite(x) and x >= 0, "유한한 0 이상의 숫자를 입력해 주세요."),
        num_ctx=_numeric_setting("NUTRIAGENT_NUM_CTX", 4096, int, lambda x: x > 0, "양의 정수를 입력해 주세요."),
        num_predict=_numeric_setting("NUTRIAGENT_NUM_PREDICT", 512, int, lambda x: x > 0, "양의 정수를 입력해 주세요."),
    )


def is_model_available(model: str | None = None) -> bool:
    """Check whether Ollama lists the selected model."""
    model = configured_inference().model if model is None else model
    tag = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
    return any(entry.model == tag for entry in ollama.Client(timeout=5).list().models)


def _tool(name, description, properties, *, optional=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [key for key in properties if key not in optional],
            },
        },
    }


TEXT = {"type": "string"}
QUANTITY = {"type": "number", "description": "The stated numeric quantity."}
UNIT = {"type": "string", "enum": ["g", "kg", "serving"]}
ITEMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "food": TEXT,
            "quantity": QUANTITY,
            "unit": UNIT,
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
    _tool("find_food", "중량 없는 식품 영양 조회. 사용자 음식명을 유지.", {"name": TEXT}),
    _tool("calculate_meal", "명시된 음식·수량·단위로 섭취 영양 계산.", {"items": ITEMS}),
    _tool("recommend_meal", "사용자가 지정한 음식으로 구성한 후보 계산.", {"items": ITEMS}),
    _tool("recommend_for_goals", "오늘 목표 또는 남은 섭취량에 맞춘 저녁 추천. 인자 없음.", {}),
    _tool("replace_food", "직전 식단의 음식 대체. 새 수량과 단위가 명시되면 둘 다 전달.", {
        "old_food": TEXT, "new_food": TEXT, "quantity": QUANTITY, "unit": UNIT,
    }, optional=("quantity", "unit")),
    _tool("search_guidelines", "영양 기준 PDF를 짧은 영문 키워드로 검색.", {"query": TEXT}),
    _tool("ask_clarification", "음식·양·기준 식단이 모호할 때 추가 질문.", {
        "missing": {"type": "string", "enum": list(QUESTIONS)},
    }),
]

SYSTEM_PROMPT = """한국어·영어 요청의 의도를 파악해 도구를 호출하세요. 수치·출처·인용은 Python 도구의 결과만 사용합니다.
음식명·조리법·수량·단위를 보존하세요. 미등록 음식도 이름 그대로 전달하고 유사 식품으로 바꾸지 마세요.
섭취 계산에서 '밥', '한 그릇', '조금'처럼 정보가 모호하면 ask_clarification. 명시된 인분은 serving으로 전달하면 Python이 검증하며, K-FIND는 g 또는 kg이 필요합니다.
오늘 목표/남은 영양/저녁 추천은 recommend_for_goals로 요청하세요. Python이 후보와 중량을 정합니다. 지정 음식으로 후보를 요청한 경우에만 recommend_meal을 쓰고 후보 중량을 제안할 수 있습니다.
'대신'은 replace_food로 처리하세요. 사용자가 새 중량을 지정한 경우에만 quantity와 unit을 전달하세요.
어떤 도구도 실제 섭취 기록을 확정하지 않습니다.
"""


MOCK_SCENARIOS = {
    "김치찌개 200g과 쌀밥 150g을 계산해 줘": ("calculate_meal", {"items": [
        {"food": "김치찌개", "quantity": 200, "unit": "g"},
        {"food": "쌀밥", "quantity": 150, "unit": "g"},
    ]}),
    "닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘": ("calculate_meal", {"items": [
        {"food": "닭가슴살", "quantity": 2, "unit": "serving"},
        {"food": "흰쌀밥", "quantity": 100, "unit": "g"},
    ]}),
    "두부와 흰쌀밥을 추천해 줘": ("recommend_meal", {"items": [
        {"food": "두부", "quantity": 100, "unit": "g"},
        {"food": "흰쌀밥", "quantity": 100, "unit": "g"},
    ]}),
    "오늘 목표에 맞춰 저녁을 추천해 줘": ("recommend_for_goals", {}),
    "닭가슴살 대신 두부": ("replace_food", {"old_food": "닭가슴살", "new_food": "두부"}),
    "닭가슴살 대신 두부 150g": ("replace_food", {
        "old_food": "닭가슴살", "new_food": "두부", "quantity": 150, "unit": "g",
    }),
    "두부 영양소를 조회해 줘": ("find_food", {"name": "두부"}),
    "두부를 조금 먹었어": ("ask_clarification", {"missing": "quantity"}),
    "미등록디저트 100g을 계산해 줘": ("calculate_meal", {"items": [
        {"food": "미등록디저트", "quantity": 100, "unit": "g"},
    ]}),
    "영양 가이드에서 whole grains를 검색해 줘": ("search_guidelines", {"query": "whole grains"}),
    "영양 가이드에서 통곡물에 대해 찾아 줘.": ("search_guidelines", {"query": "통곡물"}),
}
MOCK_SCENARIOS.update({
    "김치찌개 200g과 쌀밥 150g을 먹었어.": MOCK_SCENARIOS["김치찌개 200g과 쌀밥 150g을 계산해 줘"],
    "오늘 남은 영양 목표에 맞춰 저녁을 추천해 줘.": MOCK_SCENARIOS["오늘 목표에 맞춰 저녁을 추천해 줘"],
    "닭가슴살 대신 두부 150g으로 바꿔 줘.": MOCK_SCENARIOS["닭가슴살 대신 두부 150g"],
})


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


def read_verified_pdf(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise InputError("영양기준 PDF가 없습니다. README의 문서 준비 방법을 참고해 주세요.") from None
    except OSError:
        raise InputError("영양기준 PDF를 읽을 수 없습니다.") from None
    if hashlib.sha256(data).hexdigest() != PDF_SHA256:
        raise InputError("이 데모의 영양기준 PDF와 일치하지 않습니다. README에서 지원하는 문서를 확인해 주세요.")
    return data


def search_guidelines(path: Path, query: str) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 100:
        raise InputError("검색할 짧은 키워드를 알려 주세요. 예를 들어 통곡물 또는 whole grains를 입력해 주세요.")
    phrase = " ".join(query.split())
    term = GUIDELINE_KEYWORDS.get(phrase, phrase)
    keyword = re.compile(re.escape(term), re.IGNORECASE)
    data = read_verified_pdf(path)
    hits = []
    fallback = []
    seen = set()
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            for page in document:
                for block in page.get_text("blocks", sort=True):
                    if block[6] != 0:
                        continue
                    content = " ".join(block[4].split())
                    if not keyword.search(content):
                        continue
                    complete = [sentence for sentence in SENTENCE_BREAK.split(content)
                                if sentence[-1:] in ".!?" and keyword.search(sentence)
                                and re.match(r'(?:[+•−-]\s*)?["“(]?[A-Z]', sentence)]
                    for quote in complete or [content]:
                        normal = quote.casefold()
                        if normal in seen:
                            continue
                        seen.add(normal)
                        result = {"page": page.number + 1, "quote": quote}
                        if complete:
                            hits.append(result)
                            if len(hits) == 3:
                                return hits
                        elif len(fallback) < 3:
                            fallback.append(result)
    except (pymupdf.FileDataError, OSError):
        raise InputError("영양기준 PDF를 열 수 없습니다.") from None
    return (hits + fallback)[:3]


@dataclass
class InferenceMetrics:
    prompt_tokens: int | None
    output_tokens: int | None
    load_ms: float | None
    prompt_ms: float | None
    generation_ms: float | None
    total_ms: float | None

    @classmethod
    def from_response(cls, response: ollama.ChatResponse):
        def ms(nanoseconds):
            return nanoseconds / 1_000_000 if nanoseconds is not None else None

        return cls(response.prompt_eval_count, response.eval_count, ms(response.load_duration),
                   ms(response.prompt_eval_duration), ms(response.eval_duration), ms(response.total_duration))


@dataclass
class Reply:
    mode: Mode
    text: str = "음식과 섭취량을 알려 주시거나, 조회 또는 추천 요청을 구체적으로 입력해 주세요."
    meal: Meal | None = None
    kind: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    impact: GoalImpact | None = None
    changes: dict[str, float] = field(default_factory=dict)
    previous_meal: Meal | None = None
    food: dict | None = None
    hits: list[dict] = field(default_factory=list)
    tool_log: list[dict] = field(default_factory=list)
    model: str = MODEL_NAME
    needs_clarification: bool = False
    inference: list[InferenceMetrics] = field(default_factory=list)
    agent_ms: float | None = None


def _execute(name, args, reply, previous_meal, pdf_path, today_totals, goals):
    match name:
        case "find_food":
            reply.food = find_food(args.get("name"))
            reply.text = "등록 식품을 찾았습니다."
            return {"name": reply.food["name"], "serving_g": reply.food["serving_g"]}
        case "calculate_meal" | "recommend_meal":
            reply.meal = calculate(args.get("items"))
            reply.kind = "intake" if name == "calculate_meal" else "recommendation"
            reply.text = "섭취량을 계산했습니다." if reply.kind == "intake" else "추천 후보의 영양소를 계산했습니다."
        case "recommend_for_goals":
            reply.candidates = rank_candidates(today_totals, goals)[:3]
            if not reply.candidates:
                reply.text = "설정한 목표에 더 가까워지는 저녁 후보를 찾지 못했습니다."
                return
            best = reply.candidates[0]
            reply.meal, reply.impact, reply.kind = best.meal, best.impact, "recommendation"
            reply.text = f"오늘의 목표에 가장 가까워지는 후보는 {best.name}입니다."
        case "replace_food":
            if previous_meal is None:
                raise InputError(QUESTIONS["meal"])
            quantity = args.get("quantity")
            reply.meal = replace_food(previous_meal, args.get("old_food"), args.get("new_food"),
                                      quantity=quantity, unit=args.get("unit"))
            reply.previous_meal = previous_meal
            reply.kind = "recommendation"
            reply.impact = evaluate_meal(reply.meal, today_totals, goals)
            reply.changes = {key: reply.meal.totals[key] - previous_meal.totals[key] for key in NUTRIENTS}
            weight = "같은 중량" if quantity is None else "지정한 중량"
            reply.text = f"이전 식단에서 요청한 음식을 {weight}으로 바꿔 추천 후보를 다시 계산했습니다."
        case "search_guidelines":
            reply.hits = search_guidelines(pdf_path, args.get("query"))
            reply.text = "PDF 검색 결과입니다." if reply.hits else "PDF에서 해당 키워드를 찾지 못했습니다."
        case "ask_clarification":
            missing = args.get("missing")
            question = QUESTIONS.get(missing) if isinstance(missing, str) else None
            raise InputError(question or "음식 이름과 양을 구체적으로 알려 주세요.")
        case _:
            raise InputError("요청을 처리할 수 없습니다. 음식 이름과 양을 다시 알려 주세요.")


def run_turn(history: list[dict], previous_meal: Meal | None = None, *,
             mode: Mode | None = None, goals: dict | None = None, pdf_path: Path = PDF_PATH,
             today_totals: dict | None = None, settings: InferenceConfig | None = None) -> Reply:
    """Use tool calls as proposals; present only Python-verified results."""
    start = perf_counter_ns()
    mode = configured_mode() if mode is None else Mode(mode)
    settings = configured_inference() if settings is None else settings
    client = ollama.Client(timeout=90) if mode == Mode.OLLAMA else None
    system = SYSTEM_PROMPT
    if previous_meal:
        previous = ", ".join(f'{line.food["name"]} {line.grams:g}g' for line in previous_meal.lines)
        system += f"직전 식단: {previous}"
    messages = [{"role": "system", "content": system}, *history]
    totals = today_totals if today_totals is not None else dict.fromkeys(NUTRIENTS, 0.0)
    reply = _run_tools(messages, previous_meal, pdf_path, totals, goals or {}, mode, settings, client)
    if client is not None:
        reply.agent_ms = (perf_counter_ns() - start) / 1_000_000
    return reply


def _run_tools(messages, previous_meal, pdf_path, today_totals, goals, mode, settings, client):
    reply = Reply(mode, model=settings.model)
    if mode == Mode.MOCK:
        reply.text = "등록된 MOCK 예시를 입력해 주세요. 화면의 예시 목록에서 복사할 수 있습니다."
    for _ in range(3):
        try:
            if client is None:
                message = _mock_message(messages)
            else:
                response = client.chat(
                    model=settings.model, messages=messages, tools=TOOLS,
                    think=settings.think, keep_alive=settings.keep_alive,
                    options={"temperature": settings.temperature, "num_ctx": settings.num_ctx,
                             "num_predict": settings.num_predict},
                )
                reply.inference.append(InferenceMetrics.from_response(response))
                message = response.message
        except (ConnectionError, httpx.RequestError, ollama.ResponseError):
            return Reply(mode, model=settings.model, inference=reply.inference, tool_log=reply.tool_log,
                         text=f"Ollama에서 {settings.model} 모델을 실행할 수 없습니다. 서버와 모델 설치 상태를 확인해 주세요.")
        if not message.tool_calls:
            reply.needs_clarification = reply.food is None
            return reply
        messages.append(message)
        for call in message.tool_calls:
            name, args = call.function.name, call.function.arguments
            try:
                result = _execute(name, args, reply, previous_meal, pdf_path, today_totals, goals)
            except InputError as error:
                reply.tool_log.append({"tool": name, "input": args, "status": str(error)})
                return Reply(mode, model=settings.model, inference=reply.inference, text=str(error),
                             needs_clarification=True, tool_log=reply.tool_log)
            reply.tool_log.append({"tool": name, "input": args, "status": "완료"})
            if reply.meal is not None or name in ("search_guidelines", "recommend_for_goals"):
                return reply
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
        # A lookup can be the first step of a calculation.
    return reply
