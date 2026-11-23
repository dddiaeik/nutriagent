"""Streamlit entry point for NutriAgent."""

import ollama
import streamlit as st

from agent import MODEL_NAME, is_model_available

st.set_page_config(page_title="NutriAgent")
st.title("NutriAgent")
st.write("로컬 AI 영양 분석 및 식단 추천")

if st.button(f"Ollama 모델 확인 ({MODEL_NAME})"):
    try:
        model_available = is_model_available()
    except ConnectionError:
        st.error("Ollama 서버에 연결할 수 없습니다.")
    except ollama.ResponseError as error:
        st.error(f"Ollama 모델 목록 요청에 실패했습니다. HTTP {error.status_code}")
    else:
        if model_available:
            st.success(f"Ollama 서버에 {MODEL_NAME} 모델이 설치되어 있습니다.")
        else:
            st.warning(f"Ollama 서버에 {MODEL_NAME} 모델을 설치해 주세요.")
