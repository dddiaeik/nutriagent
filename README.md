# NutriAgent Lite

Python이 등록 식품의 열량, 탄수화물, 단백질, 지방을 계산합니다. 두 실행 모드는 같은 식품 데이터, 계산 도구, 세션 기록을 사용합니다. 사용자가 화면에서 확정한 식단만 섭취 기록에 추가됩니다.

| `NUTRIAGENT_MODE` | 용도 | 채팅 입력 |
| --- | --- | --- |
| `MOCK` (기본값) | 노트북 개발 및 오프라인 테스트 | 화면의 **MOCK 예시 문장**을 입력하면 미리 정의한 도구 호출을 실행 |
| `OLLAMA` | Windows RTX 2080 SUPER에서 최종 시연 | 실제 `qwen3:8b`가 요청을 해석하고 도구 호출을 선택 |

화면은 실행 모드와 각 응답의 출처를 표시합니다. Ollama 요청이 실패하면 연결 또는 모델 상태를 확인하라는 안내를 표시합니다.

## 설치와 실행

Python 3.11.9로 저장소 루트에서 실행합니다.

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
NUTRIAGENT_MODE=MOCK python -m streamlit run app.py
```

## Windows 및 RTX 2080 SUPER 시연

Windows 10 22H2 이상에서 Python 3.11.9와 Windows용 Ollama를 설치합니다. Ollama Windows 문서의 NVIDIA 드라이버 요구 사항(551.61 이상)을 충족하는 드라이버를 사용합니다. Ollama 앱을 실행하면 기본 서버가 시작됩니다. 백그라운드 앱이 실행 중이지 않으면 별도의 PowerShell에서 `ollama serve`를 실행합니다. [Python 3.11.9](https://www.python.org/downloads/release/python-3119/) · [Ollama Windows 안내](https://docs.ollama.com/windows)

새 PowerShell에서 저장소를 복제하고 패키지를 설치합니다. `py -3.11 --version` 출력이 `Python 3.11.9`인지 확인합니다.

```powershell
git clone --branch feature/nutriagent-mvp https://github.com/dddiaeik/nutriagent.git
Set-Location nutriagent
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

시연 전에 모델을 내려받고, 응답과 GPU 사용 여부를 확인합니다. `ollama ps`의 `PROCESSOR` 열에서 GPU 사용 여부와 CPU 혼용 여부를 확인할 수 있습니다.

```powershell
nvidia-smi
ollama pull qwen3:8b
ollama list
ollama run qwen3:8b "한 문장으로 인사해 줘."
ollama ps
```

Ollama와 모델이 준비되면 `NUTRIAGENT_MODE`만 바꿔 같은 앱을 실행합니다. 모드를 바꿀 때는 Streamlit을 다시 시작합니다.

```powershell
$env:NUTRIAGENT_MODE = "OLLAMA"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

기본 서버 주소는 `http://127.0.0.1:11434`입니다. 다른 Ollama 서버를 사용한다면 Streamlit을 시작하는 PowerShell에서 `$env:OLLAMA_HOST`에 주소를 지정합니다. 오프라인으로 시연하려면 `$env:NUTRIAGENT_MODE = "MOCK"`으로 설정합니다.

## 시연 순서

1. 화면 상단에서 실행 모드를 확인합니다. `OLLAMA` 모드에서는 사이드바에서 모델 설치 상태를 확인할 수 있습니다. 식단 열량 목표에 450 kcal를 입력합니다.
2. “닭가슴살 2인분과 흰쌀밥 100g을 계산해 줘”라고 입력합니다. 이 데모에서 1인분은 100g입니다. 합계 열량은 460 kcal이고 목표와의 차이는 +10 kcal입니다. 표 아래에서 도구 실행 로그를 확인합니다.
3. “이 식단을 섭취 기록에 추가”를 누릅니다. 화면이 다시 실행되어도 해당 계산 결과는 한 번만 추가됩니다.
4. “닭가슴살 대신 두부”를 입력합니다. 같은 중량의 두부로 바꾼 추천 후보는 418 kcal입니다. 세션의 확정 기록은 460 kcal로 유지됩니다.
5. “두부와 흰쌀밥을 추천해 줘”로 추천 후보를 확인합니다. `MOCK` 모드의 미리 정한 후보는 각각 100g으로 274 kcal입니다. “두부를 조금 먹었어”와 “떡볶이 100g을 계산해 줘”는 각각 추가 질문과 미등록 안내를 확인하는 예시입니다.
6. 아래 PDF를 준비한 경우 “영양 가이드에서 whole grains를 검색해 줘”를 입력해 원문 발췌와 PDF 페이지를 확인합니다.

## 식품 데이터와 PDF

`data/foods.json`은 USDA National Nutrient Database for Standard Reference Release 28의 12개 식품을 담습니다. NDB 번호와 원문 식품 설명으로 조리 상태를 확인할 수 있습니다. `FOOD_DES.txt`의 식품 정보와 `NUT_DATA.txt`의 영양소 코드 208·205·203·204를 연결했습니다. 원자료의 100g당 값을 사용하며, 100g 인분은 앱의 시연 기준입니다. [USDA 원자료 설명서](https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/sr28_doc.pdf) · [검증에 사용한 SR28 원자료 미러](https://github.com/alyssaq/usda-sqlite/tree/1e457b599af101ce463a195867574eba16c81acb/data)

PDF 검색은 USDA/HHS의 *Dietary Guidelines for Americans, 2025–2030* 영어판 한 개를 대상으로 합니다. 영문 키워드가 나오는 PDF 페이지를 최대 3개까지 보여 줍니다. 클라우드의 발행처 접근이 차단되어 GitHub 미러 사본에서 검색과 페이지를 검증했습니다. [발행처 PDF](https://cdn.realfood.gov/DGA.pdf) · [검증에 사용한 미러 사본](https://github.com/wachin/Dietary-Guidelines-for-Americans-2025-2030/blob/e1d210fd1d709ee9d9893f12bbb77ea073512926/DGA.pdf)

```bash
curl --fail --location https://cdn.realfood.gov/DGA.pdf --output data/reference.pdf
sha256sum data/reference.pdf
```

Windows에서는 `Invoke-WebRequest https://cdn.realfood.gov/DGA.pdf -OutFile data/reference.pdf`로 내려받고 `Get-FileHash data/reference.pdf -Algorithm SHA256`으로 확인할 수 있습니다.

지원하는 사본의 SHA-256은 `c34f1bec5c9416265670b7fcb24556bb8616ba95e8de2f2890460b6bbca1a472`입니다. 검색 함수는 일치하는 사본만 발췌하고, 파일이 없거나 다른 문서이면 그 상태를 안내합니다. PDF와 개인 섭취 기록은 Git에 포함하지 않습니다.

## 테스트

오프라인 자동 테스트는 `python -m pytest -q -rs`로 실행합니다. Windows에서는 `python` 대신 `.\.venv\Scripts\python.exe`를 사용할 수 있습니다. 이 테스트는 앱의 `MOCK` 응답과 모의 클라이언트를 사용한 `OLLAMA` 연결 실패 처리를 검증합니다.

실제 Qwen3:8B 테스트는 서버와 모델이 준비된 뒤 별도로 실행합니다.

```powershell
$env:NUTRIAGENT_LIVE_OLLAMA = "1"
.\.venv\Scripts\python.exe -m pytest -q -k live_qwen_inference
```
