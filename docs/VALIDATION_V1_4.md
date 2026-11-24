# NutriAgent V1.4 검증 기록

기준 커밋은 `12fca487b54f60f630a4b6335ea42ddf1e612403`이다. Python 3.11.9와 Streamlit 1.51.0에서 확인했다.

## 자동 테스트와 데이터

| 항목 | 결과 |
| --- | --- |
| V1.3 기준선 | 50 통과, 실추론 2건 건너뜀 |
| V1.4 오프라인 | 68 통과, 실추론 2건 건너뜀 |
| K-FIND 원본 | `validate_nutrigap.ps1 -RequireSource` 통과. 기준 SHA-256과 추출 식품 98종 일치 |
| PDF | 누락과 해시 불일치를 거부. 검증된 미러 PDF에서 5개 한국어 검색어와 출처·페이지를 확인 |
| GitHub Actions | 개선 브랜치 push와 지정한 base 브랜치의 pull request를 검증 대상으로 설정. CI는 MOCK만 실행 |

브랜드명과 표 컴포넌트가 바뀐 기존 UI 테스트는 같은 확인을 새 화면 요소에 적용하도록 갱신했다. 기록 추가, 중복 방지, 수정·취소, 추천의 기록 분리, 목표 없음·유효하지 않음·초과, 소수점 표시, 원문 검색, 시스템 상태 확인에 테스트를 추가했다.

## 브라우저와 접근성

Linux Chromium 156.0.8078.79의 실제 렌더링에서 아래 뷰포트를 검증했다.

| 크기 | 결과 |
| --- | --- |
| 1920×1080 | 본문·하단 입력창 정렬, 목표 사이드바, 전체 시연 통과 |
| 1366×768 | 표와 입력창이 뷰포트 안에 배치되고, 실제 PNG 파비콘 및 전체 시연 확인 |
| 768×1024 | 사이드바 열기·닫기, 목표 입력과 전체 시연 통과 |
| 390×844 | 가로 넘침 없는 음식별 표, 사이드바 열기·닫기, 하단 입력창과 전체 시연 통과 |

각 화면에서 예시 문장을 입력창에 채우고 확인 버튼으로 371 kcal를 기록했다. 820 kcal와 단백질 60 g 목표를 설정해 남은 449 kcal와 단백질 47.42 g을 확인했다. 저녁 추천 및 두부 150 g 대체 후에도 확정 기록은 371 kcal였다. 모호한 양에 대한 추가 질문과 통곡물 PDF 발췌의 출처·페이지도 확인했다. 같은 섭취 예시로 만든 1366px 전후 화면, 다른 크기의 V1.4 화면, 두 파비콘 비교 캡처는 최종 보고에 첨부했다.

주요 텍스트 토큰의 대비는 밝은 화면에서 기본 글자 15.16:1, 보조 글자 6.19:1, 흰색 브랜드 버튼 글자 5.03:1, 미기록 상태 글자 7.03:1이었다. 진행 막대와 트랙은 4.00:1이다. 이 수치는 지정한 색상 쌍을 검증한 결과다.

### 긴 대화 비교

1280×900 Chromium에서 같은 MOCK 식사 계산 요청을 버전별로 30회 제출했다. 두 버전 모두 최근 3턴만 상세 표를 렌더링했다. 30번째 제출의 수신 WebSocket 페이로드는 58,680 → 59,456바이트로 1.3% 증가했고 수신 프레임은 270 → 226개로 줄었다. 새 화면 스타일과 대시보드를 포함해 첫 번째 제출의 페이로드는 15,714 → 24,518바이트로 증가했다.

위쪽으로 2,200px 이동한 세 차례의 휠 입력 동안 양쪽 버전 모두 WebSocket 송수신이 없었다. 최종 V1.4의 브라우저 프레임 간격 p95는 세 번 모두 16.7ms였다. 이 결과는 Linux Chromium의 스크롤 동작에 한정하며, Windows RTX PC의 브라우저와 실제 모델 성능은 미검증이다.

## 실제 모델

클라우드에서 실제 Qwen3.5:9B와 Qwen3:8B 테스트를 실행했으나 두 경우 모두 Ollama 연결 단계에서 중단됐다. V1.4 GPU 적재율, 처리량, 응답 시간은 미검증이다. 사용자 제공 V1.3 수치는 짧은 인사 65.58 tok/s·248.51ms와 별도의 실추론 평가 9건·23.84초였으며 V1.4 측정값으로 사용하지 않았다.

## RTX 2080 SUPER 실행 및 재검증

Python 3.11.9, Ollama 0.40.17, 대상 모델이 준비된 PC에서 PowerShell을 실행한다. 원본 K-FIND 워크북을 `data/raw/음식 DB.xlsx`에 놓고 `-RequireSource` 옵션으로 대조할 수 있다.

```powershell
git clone --branch feature/nutriagent-ui-branding-v1 https://github.com/dddiaeik/nutriagent.git
Set-Location nutriagent
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama list
$env:NUTRIAGENT_MODE = "OLLAMA"
$env:NUTRIAGENT_MODEL = "qwen3.5:9b-q4_K_M"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Ollama 서버가 활성화되어 있는지 확인하고, 별도 PowerShell에서 검증을 실행한다. 두 모델의 설치 여부를 확인하고 설치되어 있는 모델에 같은 사례를 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_nutrigap.ps1 -RequireSource -Live
ollama ps
```
