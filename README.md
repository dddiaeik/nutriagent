# NutriAgent Lite · NutriGap V1.2

Python이 등록 식품의 열량, 탄수화물, 단백질, 지방을 계산합니다. 두 실행 모드는 같은 식품 데이터, 계산 도구, 세션 기록을 사용합니다. 사용자가 화면에서 확정한 식단만 섭취 기록에 추가됩니다.

| `NUTRIAGENT_MODE` | 용도 | 채팅 입력 |
| --- | --- | --- |
| `MOCK` (기본값) | 노트북 개발 및 오프라인 테스트 | 화면의 **MOCK 예시 문장**을 입력하면 미리 정의한 도구 호출을 실행 |
| `OLLAMA` | Windows RTX 2080 SUPER에서 최종 시연 | 실제 `qwen3:8b`가 요청을 해석하고 도구 호출을 선택 |

화면은 실행 모드와 각 응답의 출처를 표시합니다. Ollama 요청이 실패하면 연결 또는 모델 상태를 확인하라는 안내를 표시합니다.

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
git clone --branch feature/nutrigap-kfind-v1 https://github.com/dddiaeik/nutriagent.git
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

1. “김치찌개 200g과 쌀밥 150g을 계산해 줘”를 입력하고 **이 식단을 섭취 기록에 추가**를 누릅니다. K-FIND 출처와 오늘 누적 371 kcal를 확인합니다.
2. 오늘의 시연용 목표로 열량 820 kcal와 단백질 60g을 입력합니다. 입력하지 않은 탄수화물과 지방은 목표 비교에서 빠집니다.
3. “오늘 목표에 맞춰 저녁을 추천해 줘”를 입력합니다. 닭가슴살과 잡곡밥 후보는 445 kcal로, 이 후보를 더했을 때 남는 열량은 449 kcal에서 4 kcal로 줄어듭니다.
4. “닭가슴살 대신 두부”를 입력합니다. 같은 중량을 사용한 대체 결과와 목표 차이를 확인합니다. 오늘 확정 기록은 371 kcal로 유지됩니다.
5. 사이드바의 **오늘 기록 수정·철회**에서 중량을 바꾸거나 확정 기록을 철회합니다. 필요하면 **이전 대화 상세 보기**에서 오래된 후보의 표와 도구 로그를 다시 엽니다.
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
