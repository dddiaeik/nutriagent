# NutriAgent Lite

Qwen3:8B가 채팅 요청을 해석하고, Python이 등록 식품의 열량과 탄수화물·단백질·지방을 계산합니다. 사용자가 화면에서 확정한 식단만 현재 세션의 섭취 기록에 추가됩니다. 식품 검색, 추천 후보 및 대체식 계산, 영양기준 PDF 키워드 검색을 지원합니다.

## 설치와 실행

Python 3.11.9로 저장소 루트에서 실행합니다.

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

채팅을 사용하려면 Ollama 서버와 `qwen3:8b`가 필요합니다. 서버가 실행 중이지 않으면 별도 터미널에서 `ollama serve`를 실행합니다. 모델이 없다면 충분한 저장 공간이 있는 로컬 환경에서 다음 명령으로 내려받습니다. [Ollama 공식 설치 안내](https://ollama.com/download)

```bash
ollama --version
ollama list
ollama pull qwen3:8b
ollama run qwen3:8b "한 문장으로 인사해 줘."
```

기본 서버 주소는 `http://127.0.0.1:11434`입니다. 다른 Ollama 서버를 사용한다면 Streamlit을 시작하는 셸에 `OLLAMA_HOST`를 설정합니다.

## 시연 순서

1. 사이드바에서 Ollama 모델을 확인하고 비교 목표를 입력합니다. 예를 들어 식단 열량 목표에 450 kcal를 입력합니다.
2. “닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘”라고 입력합니다. 이 데모에서 1인분은 100g입니다. 합계 열량은 460 kcal이고 목표와의 차이는 +10 kcal입니다. 표 아래에서 도구 실행 로그를 확인합니다.
3. “이 식단을 섭취 기록에 추가”를 누릅니다. 화면이 다시 실행되어도 해당 계산 결과는 한 번만 추가됩니다.
4. “닭가슴살 대신 두부”를 입력합니다. 같은 중량의 두부로 바꾼 추천 후보는 418 kcal입니다. 세션의 확정 기록은 460 kcal로 유지됩니다.
5. “두부를 조금 먹었어”로 추가 질문을, “떡볶이 100g을 계산해 줘”로 미등록 안내를 확인합니다.
6. 아래 PDF를 준비한 경우 “영양 가이드에서 whole grains를 검색해 줘”를 입력해 원문 발췌와 PDF 페이지를 확인합니다.

## 식품 데이터와 PDF

`data/foods.json`은 USDA National Nutrient Database for Standard Reference Release 28의 12개 식품을 담습니다. NDB 번호와 원문 식품 설명으로 조리 상태를 확인할 수 있습니다. `FOOD_DES.txt`의 식품 정보와 `NUT_DATA.txt`의 영양소 코드 208·205·203·204를 연결했습니다. 원자료의 100g당 값을 사용하며, 100g 인분은 앱의 시연 기준입니다. [USDA 원자료 설명서](https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/sr28_doc.pdf) · [검증에 사용한 SR28 원자료 미러](https://github.com/alyssaq/usda-sqlite/tree/1e457b599af101ce463a195867574eba16c81acb/data)

PDF 검색은 USDA/HHS의 *Dietary Guidelines for Americans, 2025–2030* 영어판 한 개를 대상으로 합니다. 영문 키워드가 나오는 PDF 페이지를 최대 3개까지 보여 줍니다. 클라우드의 발행처 접근이 차단되어 GitHub 미러 사본에서 검색과 페이지를 검증했습니다. [발행처 PDF](https://cdn.realfood.gov/DGA.pdf) · [검증에 사용한 미러 사본](https://github.com/wachin/Dietary-Guidelines-for-Americans-2025-2030/blob/e1d210fd1d709ee9d9893f12bbb77ea073512926/DGA.pdf)

```bash
curl --fail --location https://cdn.realfood.gov/DGA.pdf --output data/reference.pdf
sha256sum data/reference.pdf
```

지원하는 사본의 SHA-256은 `c34f1bec5c9416265670b7fcb24556bb8616ba95e8de2f2890460b6bbca1a472`입니다. 검색 함수는 일치하는 사본만 발췌하고, 파일이 없거나 다른 문서이면 그 상태를 안내합니다. PDF와 개인 섭취 기록은 Git에 포함하지 않습니다.

## 테스트

```bash
python -m pytest -q -rs
NUTRIAGENT_LIVE_OLLAMA=1 python -m pytest -q -k live_qwen_inference
```

기본 테스트는 Python 계산과 모의 Ollama 도구 호출을 검증합니다. 두 번째 명령은 서버와 모델이 준비된 경우 실제 Qwen3:8B 응답을 요청합니다.
