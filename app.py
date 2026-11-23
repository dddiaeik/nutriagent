"""Streamlit chat for the NutriAgent Lite demo."""

import httpx
import ollama
import streamlit as st

from agent import MODEL_NAME, PDF_TITLE, PDF_URL, is_model_available, run_turn
from nutrition import FOODS, NUTRIENTS, SOURCE, SOURCE_URL, compare_goals

LABELS = {"kcal": "열량 (kcal)", "carbs_g": "탄수화물 (g)", "protein_g": "단백질 (g)", "fat_g": "지방 (g)"}


def nutrient_row(values):
    return {LABELS[key]: round(value, 2) for key, value in values.items()}


def render_reply(reply, turn_id, goals, records):
    st.write(reply.text)
    if reply.food:
        food = reply.food
        st.write(f'{food["name"]} · {food["description"]} · NDB {food["ndb"]}')
        st.table([{"기준량 (g)": 100, **nutrient_row(food["per_100g"])}])
    if reply.meal:
        st.table([
            {"음식": line.food["name"], "중량 (g)": round(line.grams, 2), "NDB": line.food["ndb"],
             **nutrient_row(line.nutrients)}
            for line in reply.meal.lines
        ] + [{"음식": "합계", **nutrient_row(reply.meal.totals)}])
        differences = compare_goals(reply.meal.totals, goals)
        if differences:
            st.caption("목표와의 차이 (이 식단 − 입력한 목표)")
            st.table([nutrient_row(differences)])
        if reply.kind == "intake":
            if turn_id in records:
                st.caption("섭취 기록에 저장했습니다.")
            elif st.button("이 식단을 섭취 기록에 추가", key=f"record-{turn_id}"):
                records.setdefault(turn_id, reply.meal)
                st.rerun()
        else:
            st.caption("추천 후보")
    if reply.food or reply.meal:
        st.caption(f"식품성분 출처 [{SOURCE}]({SOURCE_URL})")
    for hit in reply.hits:
        st.caption(f"[{PDF_TITLE}]({PDF_URL}) · PDF {hit['page']}쪽")
        st.text(hit["quote"])
    if reply.tool_log:
        with st.expander("도구 실행 로그"):
            st.json(reply.tool_log)


st.set_page_config(page_title="NutriAgent Lite")
st.title("NutriAgent Lite")
st.caption("식품 12종의 영양소를 계산합니다. 이 데모에서는 1인분을 100g으로 계산합니다.")

if "turns" not in st.session_state:
    st.session_state.turns = []
if "records" not in st.session_state:
    st.session_state.records = {}
turns = st.session_state.turns
records = st.session_state.records

with st.sidebar:
    if st.button(f"Ollama 모델 확인 ({MODEL_NAME})"):
        try:
            installed = is_model_available()
        except (ConnectionError, httpx.RequestError, ollama.ResponseError):
            st.error("Ollama 서버에서 모델 목록을 가져올 수 없습니다.")
        else:
            if installed:
                st.success(f"{MODEL_NAME} 모델이 서버에 설치되어 있습니다.")
            else:
                st.warning(f"{MODEL_NAME} 모델이 서버에 없습니다.")
    with st.expander("등록 식품"):
        for food in FOODS:
            st.write(f'{food["name"]} · {food["description"]}')
    st.subheader("비교 목표")
    goals = {
        key: st.number_input(label, min_value=0.01, value=None, step=1.0, key=f"goal-{key}")
        for key, label in LABELS.items()
    }
    st.subheader("세션 섭취 기록")
    st.write(f"확정한 식단 {len(records)}건")
    if records:
        totals = {key: sum(meal.totals[key] for meal in records.values()) for key in NUTRIENTS}
        st.table([nutrient_row(totals)])

prompt = st.chat_input("예: 닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘")
if prompt:
    previous = next((reply.meal for _, reply in reversed(turns) if reply.meal), None)
    history = [
        message
        for question, reply in turns[-5:]
        for message in ({"role": "user", "content": question}, {"role": "assistant", "content": reply.text})
    ]
    history.append({"role": "user", "content": prompt})
    with st.spinner("요청을 해석하는 중…"):
        reply = run_turn(history, previous, goals=goals)
    turns.append((prompt, reply))

for turn_id, (question, reply) in enumerate(turns):
    with st.chat_message("user"):
        st.text(question)
    with st.chat_message("assistant"):
        render_reply(reply, turn_id, goals, records)
