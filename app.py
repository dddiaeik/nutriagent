"""Streamlit interface for NutriAgent."""

from base64 import b64encode
from dataclasses import asdict
from datetime import date
from pathlib import Path

import httpx
import ollama
import streamlit as st

from agent import (
    MOCK_SCENARIOS, PDF_MIRROR_URL, PDF_PATH, PDF_TITLE, PDF_URL, Mode, configured_inference, configured_mode,
    is_model_available, read_verified_pdf, run_turn,
)
from nutrition import ALL_FOODS, FOODS, K_FIND_FOODS, SOURCE, SOURCE_URL, InputError, Meal, calculate, compare_goals
from nutrigap import IntakeRecord, confirmed_totals
from ui import (
    LABELS, amount_row, format_amount, meal_table, render_goals, render_impact, render_nutrient_cards,
    render_status, render_substitution,
)

ASSETS = Path(__file__).with_name("assets")
ICON = str(ASSETS / "nutriagent.png")
RECENT_DETAILS = 3
CHAT_KEY = "nutriagent_chat"
EXAMPLES = (
    ("음식 영양소 계산하기", ":material/restaurant:", "김치찌개 200g과 쌀밥 150g을 먹었어."),
    ("오늘 목표에 맞춰 추천받기", ":material/track_changes:", "오늘 남은 영양 목표에 맞춰 저녁을 추천해 줘."),
    ("음식과 중량 바꾸기 (이전 식단 필요)", ":material/swap_horiz:", "닭가슴살 대신 두부 150g으로 바꿔 줘."),
    ("영양 가이드 검색하기", ":material/menu_book:", "영양 가이드에서 통곡물에 대해 찾아 줘."),
)


def mode_label(mode, model):
    return f"OLLAMA · {model} 요청" if mode == Mode.OLLAMA else "MOCK · 미리 정의한 응답"


def render_food_sources(reply):
    foods = ([reply.food] if reply.food else []) + ([line.food for line in reply.meal.lines] if reply.meal else [])
    if not foods:
        return
    foods.extend(line.food for candidate in reply.candidates[1:] for line in candidate.meal.lines)
    if reply.previous_meal:
        foods.extend(line.food for line in reply.previous_meal.lines)
    sources = dict.fromkeys((food.get("source_name", SOURCE), food.get("source_url", SOURCE_URL)) for food in foods)
    st.caption("식품성분 출처 · " + " · ".join(f"[{name}]({url})" for name, url in sources))
    with st.expander("식품별 출처와 코드"):
        for food in {food["ndb"]: food for food in foods}.values():
            st.markdown(f'**{food["name"]}** · `{food["ndb"]}`  \n'
                        f'[{food.get("source_name", SOURCE)}]({food.get("source_url", SOURCE_URL)})')
            if food.get("description") and food["description"] != food["name"]:
                st.caption(food["description"])


def render_record_action(reply, turn_id, records, today, *, summary=None):
    saved = records.get(turn_id)
    if reply.kind == "intake":
        if saved is None:
            label, tone = "계산 완료 · 미기록", "pending"
        elif saved.meal is None:
            label, tone = "기록 취소됨", "neutral"
        elif saved.meal != reply.meal:
            label, tone = "기록 수정됨", "ready"
        else:
            label, tone = "섭취 기록 완료", "ready"
    else:
        label, tone = "추천 후보 · 실제 섭취 아님", "neutral"
    if summary is None:
        render_status(label, tone=tone)
    else:
        st.caption(f"{summary} · {label}")
    if reply.kind == "intake" and saved is None and st.button(
        "오늘 섭취 기록에 추가", key=f"record-{turn_id}", type="primary" if summary is None else "secondary",
        icon=":material/add_task:",
    ):
        records.setdefault(turn_id, IntakeRecord(today, reply.meal))
        st.rerun()


def render_reply(reply, turn_id, goals, records, today, *, detailed):
    provenance = mode_label(reply.mode, reply.model)
    if not detailed:
        if reply.meal:
            summary = " · ".join(f"{label} {value}" for label, value in amount_row(reply.meal.totals).items())
            render_record_action(reply, turn_id, records, today, summary=f"{provenance} · 합계 {summary}")
        else:
            summary = f'{reply.food["name"]} · {reply.text}' if reply.food else reply.text
            st.caption(f"{provenance} · {summary}")
        return

    st.caption(provenance)
    if reply.candidates:
        st.markdown(f'**{reply.candidates[0].name}**')
    else:
        st.write(reply.text)
    if reply.food:
        st.markdown(f'**{reply.food["name"]}** · 100 g 기준')
        render_nutrient_cards(reply.food["per_100g"])
    if reply.meal:
        render_nutrient_cards(reply.meal.totals)
        render_record_action(reply, turn_id, records, today)
        meal_table(reply.meal)
        if reply.impact is None and (differences := compare_goals(reply.meal.totals, goals)):
            st.caption("한 끼와 입력한 목표의 차이 · " + " · ".join(
                f"{label} {value}" for label, value in amount_row(differences).items()
            ))
        render_substitution(reply)
        render_impact(reply)
    render_food_sources(reply)
    if reply.hits:
        st.markdown("**PDF 원문 발췌**")
        for hit in reply.hits:
            st.caption(f"[{PDF_TITLE}]({PDF_URL}) · PDF {hit['page']}쪽")
            st.text(hit["quote"])
    if reply.tool_log:
        with st.expander("도구 실행 로그"):
            st.json(reply.tool_log)
    if reply.agent_ms is not None:
        with st.expander("Ollama 추론 지표"):
            st.caption(f"Agent 전체 응답 시간 {reply.agent_ms:.2f} ms")
            if reply.inference:
                st.json([asdict(call) for call in reply.inference])
            else:
                st.caption("Ollama 응답 지표를 받지 못했습니다.")


def edit_today_record(records, active_ids, today):
    with st.expander("오늘 기록 수정·철회"):
        turn_id = st.selectbox(
            "섭취 기록",
            active_ids,
            format_func=lambda index: f"{index + 1}. " + ", ".join(
                line.food["name"] for line in records[index].meal.lines
            ),
        )
        meal = records[turn_id].meal
        with st.form(f"record-edit-{turn_id}"):
            items = [
                {"food": line.food["name"], "unit": "g", "quantity": st.number_input(
                    f'{line.food["name"]} 중량 (g)', min_value=0.0, value=line.grams, step=1.0,
                    key=f"weight-{turn_id}-{index}",
                )}
                for index, line in enumerate(meal.lines)
            ]
            if st.form_submit_button("중량 변경 저장"):
                try:
                    updated = calculate(items)
                except InputError as error:
                    st.error(str(error))
                else:
                    records[turn_id] = IntakeRecord(today, updated)
                    st.rerun()
        if st.button("선택한 기록 철회", key=f"withdraw-{turn_id}"):
            records[turn_id] = IntakeRecord(today, None)
            st.rerun()


@st.cache_data(show_spinner=False)
def pdf_integrity(path, stamp):
    # Include the file metadata in the cache key so replacements are rechecked.
    try:
        read_verified_pdf(path)
    except InputError as error:
        return str(error)
    return "SHA-256 일치"


def render_system(mode, model):
    with st.expander("시스템 정보"):
        st.write(f"실행 모드 · {mode}")
        st.caption(f"설정 모델 · {model}")
        if mode == Mode.MOCK:
            st.caption("Ollama 연결 · 확인하지 않음 (MOCK)")
            st.caption("모델 설치 · 확인하지 않음 (MOCK)")
        else:
            if st.button(f"Ollama 모델 확인 ({model})", icon=":material/sync:"):
                try:
                    installed = is_model_available(model)
                except (ConnectionError, httpx.RequestError, ollama.ResponseError):
                    st.session_state["model_status"] = (model, "연결 실패", "확인 불가")
                else:
                    st.session_state["model_status"] = (model, "연결됨", "설치됨" if installed else "미설치")
            checked_model, connection, installation = st.session_state.get("model_status", (model, "확인 전", "확인 전"))
            st.write(f"Ollama 연결 · {connection if checked_model == model else '확인 전'}")
            st.write(f"모델 설치 · {installation if checked_model == model else '확인 전'}")
        try:
            stat = PDF_PATH.stat()
        except FileNotFoundError:
            pdf_status = "파일 없음"
        except OSError:
            pdf_status = "파일을 읽을 수 없음"
        else:
            pdf_status = pdf_integrity(PDF_PATH, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        st.write(f"영양 가이드 PDF · {pdf_status}")
        st.caption(f"[검증된 PDF 미러에서 내려받기]({PDF_MIRROR_URL})")
        st.caption(f"USDA {len(FOODS)}종 · K-FIND {len(K_FIND_FOODS)}종")
    with st.expander("등록 식품"):
        st.caption("K-FIND 식품의 중량은 g 또는 kg으로 입력합니다.")
        st.dataframe(
            [{"음식": food["name"], "출처": food.get("source_name", SOURCE)} for food in ALL_FOODS],
            hide_index=True, height=260, width="stretch",
        )
    if mode == Mode.MOCK:
        with st.expander("MOCK 예시 문장"):
            st.code("\n".join(MOCK_SCENARIOS), language="text")


def prefill_chat(prompt):
    st.session_state[CHAT_KEY] = prompt


def render_examples():
    st.subheader("어떤 도움이 필요하신가요?", anchor=False)
    for start in range(0, len(EXAMPLES), 2):
        for index, column in enumerate(st.columns(2), start=start):
            label, icon, prompt = EXAMPLES[index]
            with column:
                st.button(label, key=f"example-{index}", icon=icon, width="stretch", on_click=prefill_chat, args=(prompt,))
                st.caption(prompt)


st.set_page_config(page_title="NutriAgent", page_icon=ICON, layout="wide")
brandmark = b64encode((ASSETS / "nutriagent.svg").read_bytes()).decode("ascii")
css = (ASSETS / "nutriagent.css").read_text(encoding="utf-8")
st.html(f"<style>{css}\n.st-key-nutriagent_header{{--na-mark:url(data:image/svg+xml;base64,{brandmark})}}</style>")
try:
    mode = configured_mode()
    settings = configured_inference()
except ValueError as error:
    st.error(str(error))
    st.stop()

if "turns" not in st.session_state:
    st.session_state.turns = []
if "records" not in st.session_state:
    st.session_state.records = {}
turns = st.session_state.turns
records = st.session_state.records
today = date.today()
for turn_id, record in records.items():
    if isinstance(record, Meal):
        records[turn_id] = IntakeRecord(today, record)
totals = confirmed_totals(records.values(), today)
active_ids = [index for index, record in records.items() if record.day == today and record.meal is not None]

with st.sidebar:
    st.markdown("**NutriAgent**")
    render_status("MOCK · 모의 응답" if mode == Mode.MOCK else "OLLAMA · 실모델 요청")
    st.subheader("오늘의 영양 목표", anchor=False)
    dashboard = st.container()
    with st.expander("영양 목표 설정"):
        goals = {
            key: st.number_input(label, min_value=0.01, value=None, step=1.0, key=f"goal-{key}")
            for key, label in LABELS.items()
        }
    with dashboard:
        render_goals(totals, goals)
    st.subheader("오늘의 섭취 기록", anchor=False)
    st.write(f"확정한 식단 {len(active_ids)}건")
    if active_ids:
        edit_today_record(records, active_ids, today)
    history_selector = st.container()
    render_system(mode, settings.model)

# The root-level chat input remains fixed at the bottom in Streamlit.
prompt = st.chat_input("음식, 영양 목표 또는 식단에 대해 물어보세요", key=CHAT_KEY, width=1120)

with st.container(horizontal_alignment="center"):
    with st.container(width=1120, gap="medium"):
        with st.container(key="nutriagent_header"):
            st.title("NutriAgent", anchor=False)
            st.markdown("하루 영양 목표를 달성하도록 돕는 AI 식단 관리 Agent")
            st.caption(f"실행 모드: {mode_label(mode, settings.model)}")
        if prompt:
            previous = next((reply.meal for _, reply in reversed(turns) if reply.meal), None)
            recent = turns[-5:] if turns and turns[-1][1].needs_clarification else turns[-1:]
            history = [
                message
                for question, reply in recent
                for message in ({"role": "user", "content": question}, {"role": "assistant", "content": reply.text})
            ]
            history.append({"role": "user", "content": prompt})
            with st.spinner("요청을 해석하는 중…"):
                reply = run_turn(history, previous, mode=mode, goals=goals, today_totals=totals, settings=settings)
            turns.append((prompt, reply))

        if not turns:
            render_examples()
        summary_count = max(0, len(turns) - RECENT_DETAILS)
        selected_turn = None
        if summary_count:
            with history_selector:
                selected_turn = st.selectbox(
                    "이전 대화 상세 보기",
                    range(summary_count),
                    index=None,
                    format_func=lambda index: f"{index + 1}. {turns[index][0]}",
                    placeholder="볼 대화를 선택하세요",
                )

        for turn_id, (question, reply) in enumerate(turns):
            with st.chat_message("user"):
                st.text(question)
            with st.chat_message("assistant", avatar=ICON):
                render_reply(reply, turn_id, goals, records, today,
                             detailed=turn_id >= summary_count or turn_id == selected_turn)
