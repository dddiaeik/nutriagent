# NutriGap K-FIND V1 — data integration and automation

## Protected baseline
- Baseline: feature/nutriagent-mvp, commit a874a1cb2837e47e9ce101b4acda202a77c988fd.
- Only edit feature/nutrigap-kfind-v1. Do not merge automatically.
- Existing USDA 12 food records and MOCK/OLLAMA separation remain available.

## Source and scope
- Official download portal: https://various.foodsafetykorea.go.kr/nutrient/general/down/list.do
- Downloaded "음식 DB.xlsx" source: 19,617 rows, 160 columns, 2026-08-28 version.
- Frozen source SHA-256: 1ef3551f9a1d0ee87891d6306fa22bbd6a7ffcc90f2c70a4a184dbfe3fce6ea6
- Curated output: data/foods_kfind_v1.json; 98 foods, 16 categories, 100g basis only.
- Four required macro fields present (kcal / carbs / protein / fat), analysis method "분석".
- Full original spreadsheet is local-only in data/raw/음식 DB.xlsx, not tracked by Git.
- Do not treat missing sodium/micronutrients as 0; do not treat 100ml as 100g.
- Exact food name preference: K-FIND exact names first, legacy USDA exact names second, then aliases. "쌀밥" selects K-FIND; "흰쌀밥" remains USDA.
- K-FIND food portions **must** be entered in g or kg. No validated serving weight is available; a claimed "1인분" triggers a clarification instead of a guessed 100g.

## One-command Windows verification
From project root with the Python 3.11.9 .venv installed:

    powershell -ExecutionPolicy Bypass -File .\scripts\validate_nutrigap.ps1

Optional full original Excel proof (requires data/raw/음식 DB.xlsx):

    powershell -ExecutionPolicy Bypass -File .\scripts\validate_nutrigap.ps1 -RequireSource

Optional real Ollama tool-calling test on a machine where qwen3:8b is installed:

    powershell -ExecutionPolicy Bypass -File .\scripts\validate_nutrigap.ps1 -Live

- Offline pytest and validation require no Ollama service. The live test is opt-in.
- The validator reads the XLSX without modifying it; exact source SHA-256 and every selected food's code/metadata/macro values must agree.
- GitHub Actions (.github/workflows/nutrigap-tests.yml) automatically tests on pushes to this feature branch and PRs targeting main. If branch CI is not available, run the local script and report its output.

## Demo prompts in actual OLLAMA mode
- "김치찌개 200g과 쌀밥 150g의 영양소를 계산해 줘"
- "제육볶음 150g의 단백질은?"
- "김치찌개 1인분 먹었어" → ask for grams; do not guess.
- "흰쌀밥 100g" → existing USDA example stays supported.

## Next stage (separate acceptance checkpoint)
The present change extends **food lookup and arithmetic only**. It does not imply that recommendations are truly based on the confirmed daily intake. Next implement:
1. Aggregate only confirmed session meal records; no double saving.
2. Calculate gaps only for user-configured calorie/macro targets, not clinical deficiencies.
3. Use a bounded, Python-ranked menu candidate list with traceable sources and explicit assumptions.
4. Explain top candidates, after-target impacts and substitution deltas; keep suggestions separate from actually eaten food.
5. Investigate Chrome+Edge shared wheel-scroll lag. Profile reruns and large Streamlit tables; do not claim CSS hacks solved it without browser verification.
6. Add offline tests + real Qwen regression demo. Merge only with user approval.
