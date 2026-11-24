# 도구 구조 A/B 평가 프로토콜

## 데이터셋

- **A `tool-architecture-baseline-v1`**은 V1.4.1의 동일한 15개 요청, 기준 식단, 목표, 원본 기대 인수와 기존 영양 수치를 사용한다. `serving`의 기존 선택지인 직접 질문과 엔진이 거부하는 인분 계산을 모두 유지한다. SPLIT에서만 명시적 중량 대체의 도구 이름이 달라진다.
- **B `tool-architecture-robustness-v1`**은 부정, 상대량, 범위, 혼합 수치, 같은 중량의 명시적 재지정, 한국어·영어 표현, 후속 답변, 기준 식단 없음 등을 포함한 18개 새 사례다.
- 파일 버전, 수량, SHA-256은 [평가셋 매니페스트](../evaluation/datasets/manifest.json)에 있다. Windows 체크아웃에서도 LF를 유지한다. 두 평가셋의 기대값을 확정한 뒤 구현과 검증을 진행했다. 개발용 모의 호출은 테스트 코드의 별도 문장을 사용한다. 고정 평가셋 재현 테스트에서는 기대 호출을 주입해 채점과 엔진 연동만 확인한다.

## 실행

기본 설정은 `qwen3:8b`와 `qwen3.5:9b-q4_K_M`, LEGACY 및 SPLIT, 세 번 반복이다. A 180건과 B 216건을 따로 집계한다. Runner는 공정한 비교를 위해 `think=false`, `temperature=0`, `num_ctx=4096`, `num_predict=512`, `keep_alive=30m`를 두 구조에 고정한다. 같은 Ollama 서버와 장치에서 실행한다.

모델 하나의 평가를 마친 뒤 다음 모델로 넘어간다. 모델별 첫 짧은 인사 예열은 지표에서 제외한다. 반복별 순서는 LEGACY–SPLIT, SPLIT–LEGACY, LEGACY–SPLIT이다. 모델 설치 여부 및 가능한 경우 digest, 서버 버전, GPU 장치 정보, Git SHA를 기록한다. `ollama ps`에 표시되는 적재 비율은 실시간 GPU 사용률과 별개다.

Python 3.11.9 가상환경에 의존성을 설치한 저장소 루트에서 Windows PowerShell로 실행한다. `ollama list`에서 모델 태그를 먼저 확인한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\evaluate_tool_architecture.ps1 -Repeats 3
```

특정 경로를 지정하려면 `-OutputDirectory .\evaluation-results\rtx-v1.4.2`를 붙인다. 기본 결과는 `evaluation-results/tool-architecture-<UTC 시간>-<ID>/`와 같은 이름의 인접 ZIP이다. 표시된 경로에서 아래 파일을 확인한다.

모델·구조·데이터셋을 지정할 때는 PowerShell 세션에서 배열을 전달할 수 있다. 예를 들어 `& .\scripts\evaluate_tool_architecture.ps1 -Models @('qwen3:8b') -Architectures @('LEGACY','SPLIT') -Datasets @('baseline')`으로 한 모델의 A/B 기준 비교만 실행한다.

- `metadata.json`에는 실제 사용한 설정, 고정 평가셋 해시, 계획된 사례와 완료 상태를 기록한다.
- `results.jsonl`은 한 줄에 한 사례의 기대값, 원본 호출, 실행 호출, 보정과 이유, 결과, 점수, 각 Ollama 호출의 토큰과 시간을 기록한다. 사례마다 쓰기 버퍼를 비워 완료된 결과를 중단 후에도 보존한다.
- `summary.json`, `summary.csv`, `summary.md`는 전체 및 사례별 비교 결과다. 실제 기록이 없는 그룹의 비율은 null 또는 빈 셀이다.
- 측정 경로와 ZIP은 Git에서 제외된다. 데이터셋에는 고정된 실험용 식단만 사용한다.

중단된 실행은 다음 명령으로 저장된 줄까지만 집계할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m evaluation.analyze_tool_architecture .\evaluation-results\rtx-v1.4.2
```

## 지표와 해석

| 항목 | 정의 |
| --- | --- |
| 원본 도구 이름 | 허용된 기대 도구 중 마지막으로 생성한 호출 기준. 없으면 마지막 생성 호출을 검사 |
| 원본 인수 | 이름 조건 없이 기대 인수와 정확히 일치하는 비율과 이름이 맞은 사례에서의 조건부 비율을 각각 기록 |
| 원본 호출 | 도구와 인수가 같은 기대 항목과 모두 일치. 150g과 0.15kg은 원본 비교에서는 다른 인수 |
| 최종 실행 | 음식명, 행별 중량, 네 영양소, 목표 부족량, 결과 유형 또는 올바른 질문 종류, 확정 식단 스냅샷 불변 여부 |
| 추가 질문 | 기대 질문 도구가 직접 생성된 비율, 최종 결과가 올바른 질문인 비율, 명확한 사례에서 불필요한 질문 비율 |
| 보정 또는 차단 | 해당 사례에서 실행 도구 변경, 인수 추가·수정·제거, 차단 중 하나가 발생한 비율. 보정 후 여전히 틀린 사례도 별도 집계 |
| 일관성 | 같은 모델·구조·사례에 평가된 반복이 두 개 이상이면 원본 호출 목록, 최종 결과, 질문 여부·종류를 비교 |
| 지연 | Agent 전체 시간의 평균·중앙값·nearest-rank P95. 호출 중 로딩 시간이 100ms 이상이면 Cold, 모두 그 미만이면 Warm, 측정값이 빠지면 Unknown으로 분류 |
| 생성 속도 | 유효한 호출의 총 출력 토큰을 총 생성 시간으로 나눈 값 |

모델 미설치, 연결 실패, 시간 초과, Ollama 오류와 평가 오류를 정확도 분모에서 제외하고 따로 기록한다. 누락·중복·잘못된 줄을 감지한다. A/B 차이는 양쪽에서 평가된 동일 사례와 반복만 비교하며, 짝 수와 완료 여부를 표시한다. 결과 유형이 추천인 경우 저장 버튼을 제공하지 않는지 Streamlit 회귀 테스트에서도 확인한다.
