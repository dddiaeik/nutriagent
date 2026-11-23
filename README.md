# NutriAgent

Qwen3:8B로 자연어를 해석하고 Python으로 영양성분을 계산하는 로컬 영양 분석 및 식단 추천 프로젝트입니다. 현재 초기 화면과 Ollama 모델 설치 확인 기능을 제공합니다.

## 개발 환경 설치

저장소 루트에서 Python 3.11.9로 가상환경을 만듭니다. 아래 명령은 Bash 기준입니다.

```bash
python --version  # Python 3.11.9 확인
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 앱 실행

```bash
python -m streamlit run app.py
```

터미널에 표시된 주소를 브라우저로 엽니다. 화면을 띄우는 데는 Ollama 서버가 필요 없으며, 모델 확인 버튼은 서버의 모델 목록을 조회합니다.

## Ollama 서버와 모델 확인

Python 의존성에는 Ollama 클라이언트가 포함됩니다. [공식 설치 안내](https://ollama.com/download)에 따라 서버를 설치한 뒤, 서버가 실행 중이지 않으면 별도 터미널에서 `ollama serve`를 실행합니다.

```bash
ollama --version
ollama pull qwen3:8b
ollama list
ollama run qwen3:8b "한 문장으로 인사해 줘."
```

모델 목록에서 `qwen3:8b`를 확인하고 마지막 명령으로 실제 응답을 검증합니다. 원격 Ollama 서버를 사용한다면 Streamlit을 시작하는 쉘에서 `OLLAMA_HOST`를 설정합니다.

## 초기 환경 검증

```bash
python -m py_compile app.py agent.py nutrition.py
python -c "import streamlit, ollama, pymupdf, pytest; import agent, nutrition"
python -m pip check
```
