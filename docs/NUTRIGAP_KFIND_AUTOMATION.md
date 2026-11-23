# NutriGap V1.2 — data integration and validation

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
- GitHub Actions runs offline checks on pushes to the improvement branch and on PRs targeting either protected branch. The job pins Ubuntu 24.04, which has a published Python 3.11.9 build.

## Demo prompts in actual OLLAMA mode
- "김치찌개 200g과 쌀밥 150g의 영양소를 계산해 줘"
- "제육볶음 150g의 단백질은?"
- "김치찌개 1인분 먹었어" → ask for grams; do not guess.
- "흰쌀밥 100g" → existing USDA example stays supported.
- Confirm the kimchi stew and rice meal, set the demo goals to 820 kcal and 60 g protein, then ask "오늘 목표에 맞춰 저녁을 추천해 줘".
- Ask "닭가슴살 대신 두부" to compare the next meal's nutrients and target gap after a same-weight substitution.

## Recommendation and session scope

- Today's total includes only confirmed, active records dated to the app host's local day. Each chat result can be confirmed once. Weight changes replace the saved meal; withdrawal excludes it from the total.
- Qwen selects the tool. Python evaluates six fixed meals on the explicitly entered goals. Each target contributes its absolute gap divided by the goal value. The response shows up to three meals that improve the combined score and keeps them separate from intake records.
- The latest three responses show full tables. Earlier replies show summaries, with full details available from the sidebar. Original calculation precision is retained.

## Scroll reproduction

In MOCK mode, submit the same valid meal calculation 30 times at 1280 × 900. From the bottom of the chat, wheel up quickly on the conversation pane. Measure scroll movement and any WebSocket messages during the wheel gesture separately from the server's rerun when submitting a chat message. Run the same steps in Chrome and Edge for a browser-specific manual check.

## V1.2 verification results

- The attached original workbook matched the pinned SHA-256. All 98 curated food codes, names, source basis, analysis methods, and four nutrient values matched the workbook.
- The baseline passed 26 offline tests. The scroll and recommendation changes brought this to 31 passing tests. The opt-in model test is skipped by the offline suite.
- In headless Chromium at 30 turns, the final submission produced 58,523 bytes of incoming WebSocket payload, down from 133,560 bytes at baseline. Three upward wheel gestures each moved the view by 2,200 pixels without a WebSocket message. Chrome and Edge manual confirmation is pending.
- The separate live test could not connect to Ollama in the cloud, so no Qwen3:8B inference was verified there.
