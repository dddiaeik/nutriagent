"""Streamlit chat for the NutriAgent Lite demo."""

from dataclasses import asdict
from datetime import date

import httpx
import ollama
import streamlit as st

from agent import (
    MOCK_SCENARIOS, PDF_TITLE, PDF_URL, Mode, configured_inference, configured_mode, is_model_available, run_turn,
)
from nutrition import ALL_FOODS, SOURCE, SOURCE_URL, InputError, Meal, calculate, compare_goals
from nutrigap import IntakeRecord, confirmed_totals, goal_gap

LABELS = {"kcal": "열량 (kcal)", "carbs_g": "탄수화물 (g)", "protein_g": "단백질 (g)", "fat_g": "지방 (g)"}
RECENT_DETAILS = 3


def nutrient_row(values):
    return {LABELS[key]: round(value) for key, value in values.items()}


def mode_label(mode, model):
    return f"OLLAMA · {model} 요청" if mode == Mode.OLLAMA else "MOCK · 미리 정의한 응답"


def render_reply(reply, turn_id, goals, records, today, *, detailed):
    st.caption(mode_label(reply.mode, reply.model))
    st.write(reply.text)
    if reply.food:
        food = reply.food
        st.write(f'{food["name"]} · {food["description"]} · 식품코드 {food["ndb"]}')
        if detailed:
            st.table([{"기준량 (g)": 100, **nutrient_row(food["per_100g"])}])
    if reply.meal:
        if detailed:
            st.table([
                {"음식": line.food["name"], "중량 (g)": round(line.grams), "식품코드": line.food["ndb"],
                 **nutrient_row(line.nutrients)}
                for line in reply.meal.lines
            ] + [{"음식": "합계", **nutrient_row(reply.meal.totals)}])
            differences = compare_goals(reply.meal.totals, goals) if reply.impact is None else {}
            if differences:
                st.caption("목표와의 차이 (이 식단 − 입력한 목표)")
                st.table([nutrient_row(differences)])
        else:
            st.caption("합계 " + " · ".join(f"{label} {value}" for label, value in nutrient_row(reply.meal.totals).items()))
        if reply.kind == "intake":
            if turn_id in records:
                st.caption("섭취 기록을 철회했습니다." if records[turn_id].meal is None else "섭취 기록에 저장했습니다.")
            elif st.button("이 식단을 섭취 기록에 추가", key=f"record-{turn_id}"):
                records.setdefault(turn_id, IntakeRecord(today, reply.meal))
                st.rerun()
        else:
            st.caption("추천 후보")
        if detailed and reply.impact and reply.impact.before:
            st.caption("추천 당시의 남은 목표 (목표 − 누적, 음수는 초과)")
            st.table([
                {"영양소": LABELS[key], "추천 전": round(value), "후보를 먹은 뒤": round(reply.impact.after[key])}
                for key, value in reply.impact.before.items()
            ])
        if detailed and reply.changes:
            st.caption("대체에 따른 차이 (대체 후 − 대체 전)")
            st.table([nutrient_row(reply.changes)])
        if detailed and len(reply.candidates) > 1:
            st.caption("다른 저녁 후보와 섭취 후 남은 목표")
            st.table([
                {
                    "후보": candidate.name,
                    "구성": ", ".join(f'{line.food["name"]} {line.grams:.0f}g' for line in candidate.meal.lines),
                    **{f"남은 {label}": value for label, value in nutrient_row(candidate.impact.after).items()},
                }
                for candidate in reply.candidates[1:]
            ])
    if reply.food or reply.meal:
        foods_in_result = ([reply.food] if reply.food else []) + ([line.food for line in reply.meal.lines] if reply.meal else [])
        if detailed:
            foods_in_result.extend(line.food for candidate in reply.candidates[1:] for line in candidate.meal.lines)
        sources = list(dict.fromkeys((f.get("source_name", SOURCE), f.get("source_url", SOURCE_URL)) for f in foods_in_result))
        st.caption("식품성분 출처: " + " · ".join(f"[{label}]({url})" for label, url in sources))
    if detailed:
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


st.set_page_config(page_title="NutriAgent Lite")
st.title("NutriAgent Lite")
try:
    mode = configured_mode()
    settings = configured_inference()
except ValueError as error:
    st.error(str(error))
    st.stop()
st.caption(f"실행 모드: {mode_label(mode, settings.model)}")
st.caption("USDA 12종 + K-FIND 98종. K-FIND 음식의 1인분 중량은 미확인으로 g 또는 kg으로 입력합니다.")

if mode == Mode.MOCK:
    st.caption(f"설정된 Ollama 모델: {settings.model}")
    with st.expander("MOCK 예시 문장"):
        st.code("\n".join(MOCK_SCENARIOS), language="text")

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
    if mode == Mode.OLLAMA and st.button(f"Ollama 모델 확인 ({settings.model})"):
        try:
            installed = is_model_available(settings.model)
        except (ConnectionError, httpx.RequestError, ollama.ResponseError):
            st.error("Ollama 서버에서 모델 목록을 가져올 수 없습니다.")
        else:
            if installed:
                st.success(f"{settings.model} 모델이 서버에 설치되어 있습니다.")
            else:
                st.warning(f"{settings.model} 모델이 서버에 없습니다.")
    with st.expander("등록 식품"):
        st.caption(f"조회 가능한 식품 데이터 {len(ALL_FOODS)}건 (USDA + K-FIND)")
        st.dataframe(
            [{"음식": f["name"], "출처": f.get("source_name", SOURCE)} for f in ALL_FOODS],
            hide_index=True, height=260, width="stretch",
        )
    st.subheader("오늘 영양 목표")
    goals = {
        key: st.number_input(label, min_value=0.01, value=None, step=1.0, key=f"goal-{key}")
        for key, label in LABELS.items()
    }
    st.subheader("오늘 섭취 기록")
    st.write(f"확정한 식단 {len(active_ids)}건")
    if active_ids:
        st.table([nutrient_row(totals)])
        edit_today_record(records, active_ids, today)
    gap = goal_gap(totals, goals)
    if gap:
        st.caption("오늘 남은 목표 (음수는 초과)")
        st.table([nutrient_row(gap)])

prompt = st.chat_input("예: 닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘")
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

summary_count = max(0, len(turns) - RECENT_DETAILS)
selected_turn = None
if summary_count:
    selected_turn = st.sidebar.selectbox(
        "이전 대화 상세 보기",
        range(summary_count),
        index=None,
        format_func=lambda index: f"{index + 1}. {turns[index][0]}",
        placeholder="볼 대화를 선택하세요",
    )

for turn_id, (question, reply) in enumerate(turns):
    with st.chat_message("user"):
        st.text(question)
    with st.chat_message("assistant"):
        render_reply(reply, turn_id, goals, records, today,
                     detailed=turn_id >= summary_count or turn_id == selected_turn)
