import hashlib

import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

import agent
from nutrition import InputError
from ui import format_amount, goal_progress

INTAKE = "김치찌개 200g과 쌀밥 150g을 먹었어."
DINNER = "오늘 남은 영양 목표에 맞춰 저녁을 추천해 줘."
SWAP = "닭가슴살 대신 두부 150g으로 바꿔 줘."


@pytest.mark.parametrize("target", [None, 0, -10, float("nan"), float("inf"), "820", True])
def test_goal_progress_for_missing_or_invalid_target(target):
    assert goal_progress(371, target) is None


def test_progress_preserves_the_rate_and_caps_the_bar():
    assert goal_progress(371, 820) == pytest.approx((449, 45.243902439, 45.243902439))
    assert goal_progress(12.58, 60) == pytest.approx((47.42, 20.966666667, 20.966666667))
    assert goal_progress(371, 320) == pytest.approx((-51, 115.9375, 100))


@pytest.mark.parametrize("value,expected", [(150.0000, "150"), (12.58, "12.58"), (0.002, "0.002"), (1000.50, "1,000.5")])
def test_display_amount_without_redundant_decimal_places(value, expected):
    assert format_amount(value) == expected


def _html(screen):
    return "\n".join(element.proto.body for element in screen.get("html"))


def test_dashboard_tracks_explicit_intake_but_not_recommendations(monkeypatch):
    monkeypatch.setenv("NUTRIAGENT_MODE", "MOCK")
    screen = AppTest.from_file("app.py", default_timeout=15).run()
    assert _html(screen).count("목표 미설정") == 4
    screen.button(key="example-0").click().run()
    assert screen.chat_input[0].value == INTAKE and not screen.session_state.turns
    screen.chat_input[0].set_value(INTAKE).run()
    assert "계산 완료 · 미기록" in _html(screen) and not screen.session_state.records
    screen.button(key="record-0").click().run()
    screen.number_input(key="goal-kcal").set_value(320).run()
    assert "371 / 320 kcal" in _html(screen) and "초과 51 kcal" in _html(screen)
    assert "달성률 115.9%" in _html(screen) and 'max="100" value="100"' in _html(screen)
    screen.number_input(key="goal-kcal").set_value(820).run()
    screen.number_input(key="goal-protein_g").set_value(60).run()
    assert "섭취 기록 완료" in _html(screen)
    assert "371 / 820 kcal" in _html(screen) and "남은 449 kcal" in _html(screen)
    assert "12.58 / 60 g" in _html(screen) and "남은 47.42 g" in _html(screen)
    assert not any(button.key == "record-0" for button in screen.button)
    screen.chat_input[0].set_value(DINNER).run()
    assert "남은 4 kcal" in _html(screen)
    screen.chat_input[0].set_value(SWAP).run()
    assert "추천 후보 · 실제 섭취 아님" in _html(screen)
    assert "초과 14 kcal" in _html(screen)
    assert any("열량 증가 +18 kcal" in caption.value for caption in screen.caption)
    assert screen.session_state.turns[-1][1].meal.lines[0].grams == 150
    assert not any((button.key or "").startswith("record-") for button in screen.button)
    assert list(screen.session_state.records) == [0]
    assert screen.session_state.records[0].meal.totals["kcal"] == 371
    screen.number_input(key="weight-0-0").set_value(100)
    next(button for button in screen.button if button.label == "중량 변경 저장").click().run()
    assert "기록 수정됨" in _html(screen) and "310 / 820 kcal" in _html(screen)
    screen.button(key="withdraw-0").click().run()
    assert "기록 취소됨" in _html(screen) and "0 / 820 kcal" in _html(screen)
    assert not any(button.key == "record-0" for button in screen.button) and not screen.exception


def _create_pdf(path, pages):
    with pymupdf.open() as document:
        for content in pages:
            page = document.new_page()
            page.insert_textbox((70, 70, 530, 750), content)
        document.save(path)


def test_guidelines_extract_complete_unique_sentences_and_keep_page_numbers(tmp_path, monkeypatch):
    pdf = tmp_path / "reference.pdf"
    _create_pdf(pdf, [
        "Focus on Whole Grains",
        "Local diets differ. Adults can choose whole grains daily. Protein supports meals.",
        "Adults can choose whole grains daily.",
        "Dr. Lee discussed whole grains. Other foods were mentioned.",
    ])
    monkeypatch.setattr(agent, "PDF_SHA256", hashlib.sha256(pdf.read_bytes()).hexdigest())
    hits = agent.search_guidelines(pdf, "통곡물")
    assert hits == agent.search_guidelines(pdf, "WHOLE GRAINS")
    assert hits == [
        {"page": 2, "quote": "Adults can choose whole grains daily."},
        {"page": 4, "quote": "Dr. Lee discussed whole grains."},
        {"page": 1, "quote": "Focus on Whole Grains"},
    ]
    assert agent.search_guidelines(pdf, "단백질") == [{"page": 2, "quote": "Protein supports meals."}]


def test_pdf_errors_also_appear_in_readiness_panel(tmp_path, monkeypatch):
    pdf = tmp_path / "reference.pdf"
    monkeypatch.setenv("NUTRIAGENT_MODE", "MOCK")
    monkeypatch.setattr(agent, "PDF_PATH", pdf)
    screen = AppTest.from_file("app.py").run()
    assert any("영양 가이드 PDF · 파일 없음" in item.value for item in screen.markdown)
    with pytest.raises(InputError, match="PDF가 없습니다"):
        agent.search_guidelines(pdf, "통곡물")
    _create_pdf(pdf, ["Whole grains are often discussed."])
    with pytest.raises(InputError, match="일치하지 않습니다"):
        agent.search_guidelines(pdf, "통곡물")
    screen.run()
    assert any("영양 가이드 PDF · 이 데모의 영양기준 PDF와 일치하지 않습니다" in item.value
               for item in screen.markdown)
    monkeypatch.setattr(agent, "PDF_SHA256", hashlib.sha256(pdf.read_bytes()).hexdigest())
    # A new file metadata key makes the status recheck the file.
    pdf.touch()
    screen.run()
    assert any("영양 가이드 PDF · SHA-256 일치" in item.value for item in screen.markdown)
    assert any("Ollama 연결 · 확인하지 않음 (MOCK)" in item.value for item in screen.caption)


@pytest.mark.parametrize("installed,connection,installation", [
    (True, "연결됨", "설치됨"), (False, "연결됨", "미설치"), (None, "연결 실패", "확인 불가"),
])
def test_ollama_readiness_is_checked_only_on_request(monkeypatch, installed, connection, installation):
    model = "qwen3.5:9b-q4_K_M"
    monkeypatch.setenv("NUTRIAGENT_MODE", "OLLAMA")
    monkeypatch.setenv("NUTRIAGENT_MODEL", model)
    checks = []

    def check(name):
        checks.append(name)
        if installed is None:
            raise ConnectionError
        return installed

    monkeypatch.setattr(agent, "is_model_available", check)
    screen = AppTest.from_file("app.py").run()
    assert not checks and any("Ollama 연결 · 확인 전" in item.value for item in screen.markdown)
    next(button for button in screen.button if button.label == f"Ollama 모델 확인 ({model})").click().run()
    assert checks == [model]
    assert any(f"Ollama 연결 · {connection}" in item.value for item in screen.markdown)
    assert any(f"모델 설치 · {installation}" in item.value for item in screen.markdown)
    screen.run()
    assert checks == [model] and not screen.exception
