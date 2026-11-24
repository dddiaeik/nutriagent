# NutriAgent V1.4 · NutriGap

Python이 등록 식품의 열량, 탄수화물, 단백질, 지방을 계산합니다. 두 실행 모드는 같은 식품 데이터, 계산 도구, 세션 기록을 사용합니다. 사용자가 화면에서 확정한 식단만 섭취 기록에 추가됩니다.

| `NUTRIAGENT_MODE` | 용도 | 채팅 입력 |
| --- | --- | --- |
| `MOCK` (기본값) | 노트북 개발 및 오프라인 테스트 | 화면의 **MOCK 예시 문장**을 입력하면 미리 정의한 도구 호출을 실행 |
| `OLLAMA` | Windows RTX 2080 SUPER에서 최종 시연 | 선택한 모델이 요청을 해석하고 도구를 호출. 기본 `qwen3:8b` |

화면은 실행 모드와 각 응답의 출처를 표시합니다. Ollama 요청이 실패하면 연결 또는 모델 상태를 확인하라는 안내를 표시합니다.

사이드바의 목표 카드에서 확정 섭취량, 목표량, 남은 양이나 초과량, 달성률을 확인합니다. 식사 계산 후 **오늘 섭취 기록에 추가**를 눌러야 합계에 반영됩니다. 기록 수정과 철회도 사이드바에서 할 수 있습니다. **시스템 정보**에서 모델 연결을 직접 확인하고 영양 가이드 PDF의 무결성과 등록 식품 수를 볼 수 있습니다.

[UI 디자인](docs/UI_DESIGN_V1_4.md) · [V1.4 검증 기록](docs/VALIDATION_V1_4.md)

## NutriGap K-FIND 한국 음식 확장 (개선 브랜치)

기존 USDA 12종을 보존하고 K-FIND 음식 98종을 추가합니다. K-FIND 영양성분은 100g 기준이며 검증된 1인분 중량이 없으므로 g 또는 kg으로 입력해야 합니다.

- 음식 데이터는 `data/foods.json`(USDA 12종), `data/foods_kfind_v1.json`(K-FIND 98종)으로 분리합니다.
- 같은 단어가 충돌하면 K-FIND 정확한 이름을 우선합니다. 예: `쌀밥`은 K-FIND, `흰쌀밥`은 USDA입니다.
- 원본 Excel 파일은 `data/raw/음식 DB.xlsx`에만 보관하며 Git에는 올리지 않습니다. 앱 실행에는 원본 Excel이 필요하지 않습니다.
- 누락된 값은 0으로 대체하지 않으며 100ml 기준 데이터를 100g으로 환산하지 않습니다.

Windows PowerShell에서 준비된 Python 3.11.9 가상환경으로 한 번에 검증:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_nutrigap.ps1
# 원본 엑셀까지 반드시 검사하려면 -RequireSource 옵션 추가
# 실제 Qwen3:8B 호출까지 검증하려면 -Live 옵션 추가
```

데이터 출처·검증·한계는 [NutriGap K-FIND 자동 검증 가이드](docs/NUTRIGAP_KFIND_AUTOMATION.md)를 참고하세요.

PowerShell 7이 있는 Linux에서는 `pwsh -File scripts/validate_nutrigap.ps1 -RequireSource`로 같은 검증을 실행할 수 있습니다.

하루 집계에는 앱이 실행되는 PC의 로컬 날짜와 현재 브라우저 세션에서 확정한 기록을 사용합니다. 설정한 목표만 비교하고, 미입력 항목은 판단을 보류합니다. Python은 등록 식품과 고정 중량으로 구성한 저녁 6개를 계산합니다. 후보별로 각 목표와의 절대 차이를 목표값으로 나누어 합산하고, 이 합이 줄어드는 후보를 최대 3개 표시합니다. 이는 사용자가 입력한 목표와의 거리 비교입니다. 후보 중량은 시연용이며 표의 숫자만 정수로 표시합니다.

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
git clone --branch feature/nutriagent-ui-branding-v1 https://github.com/dddiaeik/nutriagent.git
Set-Location nutriagent
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

시연 전에 `ollama list`에서 사용할 모델 태그를 확인합니다. 짧은 예열 요청 후 `ollama ps`의 `PROCESSOR` 열에서 GPU 사용 여부와 CPU 혼용 여부를 확인할 수 있습니다. 아래 명령은 Qwen3.5 모델이 이미 설치된 PC에서 실행합니다.

```powershell
nvidia-smi
ollama list
ollama run qwen3.5:9b-q4_K_M "한 문장으로 인사해 줘."
ollama ps
```

Ollama와 모델이 준비되면 PowerShell에서 환경변수를 설정하고 Streamlit을 시작합니다.

```powershell
$env:NUTRIAGENT_MODE = "OLLAMA"
$env:NUTRIAGENT_MODEL = "qwen3.5:9b-q4_K_M"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

기본 서버 주소는 `http://127.0.0.1:11434`입니다. 다른 Ollama 서버를 사용한다면 Streamlit을 시작하는 PowerShell에서 `$env:OLLAMA_HOST`에 주소를 지정합니다. 오프라인으로 시연하려면 `$env:NUTRIAGENT_MODE = "MOCK"`으로 설정합니다.

### 모델과 추론 설정

| 환경변수 | 기본값 | 허용 값 |
| --- | --- | --- |
| `NUTRIAGENT_MODEL` | `qwen3:8b` | Ollama에 설치된 모델 이름 또는 태그 |
| `NUTRIAGENT_THINK` | `false` | `true` / `false` 또는 `1` / `0` |
| `NUTRIAGENT_TEMPERATURE` | `0` | 0 이상의 유한한 숫자 |
| `NUTRIAGENT_NUM_CTX` | `4096` | 양의 정수 |
| `NUTRIAGENT_NUM_PREDICT` | `512` | 양의 정수 |
| `NUTRIAGENT_KEEP_ALIVE` | `30m` | `10m` 등 유지 시간, `0` 즉시 해제, `-1` 계속 유지 |

전체 식품 목록은 사이드바에서 볼 수 있으며 Python 조회는 전체 데이터와 별칭을 사용합니다. 모델에는 전체 식품 목록 대신 직전 식단과 최근 대화만 전달합니다. 일반 턴은 직전 1턴을 전달하고, 추가 질문 직후에는 앞선 조건을 보존하기 위해 최대 5턴을 전달합니다.

**Ollama 추론 지표**에는 API 호출별 `prompt_tokens`와 `output_tokens` 및 모델 로딩·입력 처리·출력 생성·Ollama 전체 시간을 밀리초로 표시합니다. Agent 전체 시간에는 모든 모델 호출, 서버 왕복 및 Python 도구 실행이 들어갑니다. Ollama가 제공하지 않은 지표는 비워 두며, MOCK에는 실측 지표가 표시되지 않습니다.

## 시연 순서

1. “김치찌개 200g과 쌀밥 150g을 먹었어.”를 입력하고 **오늘 섭취 기록에 추가**를 누릅니다. K-FIND 출처와 오늘 누적 371 kcal를 확인합니다. 빈 대화의 예시 버튼은 요청 문장을 입력창에 채웁니다.
2. 오늘의 시연용 목표로 열량 820 kcal와 단백질 60g을 입력합니다. 입력하지 않은 탄수화물과 지방은 목표 비교에서 빠집니다.
3. “오늘 목표에 맞춰 저녁을 추천해 줘”를 입력합니다. 닭가슴살과 잡곡밥 후보는 445 kcal로, 이 후보를 더했을 때 남는 열량은 449 kcal에서 4 kcal로 줄어듭니다.
4. “닭가슴살 대신 두부”를 입력하면 기존 중량을 사용합니다. 추천을 다시 요청한 뒤 “닭가슴살 대신 두부 150g”을 입력하면 새 중량으로 대체합니다. 두 경우 모두 오늘 확정 기록은 371 kcal로 유지됩니다.
5. 사이드바의 **오늘 기록 수정·철회**에서 중량을 바꾸거나 확정 기록을 철회합니다. 필요하면 **이전 대화 상세 보기**에서 오래된 후보의 표와 도구 로그를 다시 엽니다.
6. “두부를 조금 먹었어”로 중량을 묻는 답변을 확인합니다. PDF가 준비되면 “영양 가이드에서 통곡물에 대해 찾아 줘.”를 입력해 원문 발췌, 발행처 링크, PDF 페이지를 확인합니다.

## 식품 데이터와 PDF

`data/foods.json`은 USDA National Nutrient Database for Standard Reference Release 28의 12개 식품을 담습니다. NDB 번호와 원문 식품 설명으로 조리 상태를 확인할 수 있습니다. `FOOD_DES.txt`의 식품 정보와 `NUT_DATA.txt`의 영양소 코드 208·205·203·204를 연결했습니다. 원자료의 100g당 값을 사용하며, 100g 인분은 앱의 시연 기준입니다. [USDA 원자료 설명서](https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/sr28_doc.pdf) · [검증에 사용한 SR28 원자료 미러](https://github.com/alyssaq/usda-sqlite/tree/1e457b599af101ce463a195867574eba16c81acb/data)

PDF 검색은 USDA/HHS의 *Dietary Guidelines for Americans, 2025–2030* 영어판에서 키워드와 일치하는 원문 발췌를 최대 3개 표시합니다. 문장 경계를 확인하기 어려운 경우 추출한 문단이나 제목을 그대로 표시합니다. 통곡물, 단백질, 식이섬유, 첨가당, 건강한 지방은 영어 검색어에 대응합니다. [발행처 PDF](https://cdn.realfood.gov/DGA.pdf) · [검증한 미러 사본](https://github.com/wachin/Dietary-Guidelines-for-Americans-2025-2030/blob/e1d210fd1d709ee9d9893f12bbb77ea073512926/DGA.pdf)

```bash
curl --fail --location https://cdn.realfood.gov/DGA.pdf --output data/reference.pdf
sha256sum data/reference.pdf
```

Windows에서는 발행처 URL에서 내려받습니다. 발행처 연결이 어려우면 아래 주석의 고정 커밋 미러 URL을 대신 사용할 수 있습니다.

```powershell
$pdf = "https://cdn.realfood.gov/DGA.pdf"
# $pdf = "https://raw.githubusercontent.com/wachin/Dietary-Guidelines-for-Americans-2025-2030/e1d210fd1d709ee9d9893f12bbb77ea073512926/DGA.pdf"
Invoke-WebRequest $pdf -OutFile data/reference.pdf
Get-FileHash data/reference.pdf -Algorithm SHA256
```

지원하는 사본의 SHA-256은 `c34f1bec5c9416265670b7fcb24556bb8616ba95e8de2f2890460b6bbca1a472`입니다. 검색 함수는 일치하는 사본만 발췌하고, 파일이 없거나 다른 문서이면 그 상태를 안내합니다. PDF와 개인 섭취 기록은 Git에 포함하지 않습니다.

## 테스트

오프라인 자동 테스트는 `python -m pytest -q -rs`로 실행합니다. Windows에서는 `python` 대신 `.\.venv\Scripts\python.exe`를 사용할 수 있습니다. 이 테스트는 앱의 `MOCK` 응답과 모의 클라이언트를 사용한 `OLLAMA` 연결 실패 처리를 검증합니다.

실제 모델 테스트는 서버가 준비된 뒤 별도로 실행합니다. Qwen3.5와 기본 Qwen3가 둘 다 설치되어 있으면 한국어 도구 선택, 인자 추출, 모호한 입력, K-FIND 인분, 대체 중량, 목표 추천을 같은 테스트 문장으로 비교합니다. 설치되지 않은 모델은 건너뛰며, 모델별·사례별 호출 지표를 JSON으로 출력합니다.

```powershell
$env:NUTRIAGENT_LIVE_OLLAMA = "1"
.\.venv\Scripts\python.exe -m pytest -q -rs -s -k live_qwen_inference
```
