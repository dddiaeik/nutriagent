import json
import runpy
from pathlib import Path

import httpx
import ollama
import pytest

from agent import ToolArchitecture
from evaluation import run_tool_architecture as runner
from evaluation.analyze_tool_architecture import analyze, write_summary
from evaluation.core import evaluate_case, load_dataset, raw_scores

MODELS = ["qwen3:8b", "qwen3.5:9b-q4_K_M"]
A, B = ToolArchitecture


def test_dataset_a_preserves_all_fifteen_cases_and_experiment_has_180_baseline_trials():
    data, spec = load_dataset("baseline")
    original = runpy.run_path(str(Path(__file__).with_name("test_agent_v13.py")))
    expected = original["CASES"] + original["SWAP_CASES"]
    assert len(data["cases"]) == spec["count"] == len(expected) == 15
    for case, (ident, prompt, tool, args, kcal) in zip(data["cases"], expected, strict=True):
        assert case["id"] == ident and case["history"] == [{"role": "user", "content": prompt}]
        assert case["raw"]["LEGACY"][0] == {"tool": tool, "input": args}
        assert case["prior_meal"] == ("split" if ident.startswith("swap-split-") else "single")
        if kcal is not None:
            assert case["effective"]["nutrients"]["kcal"] == kcal
    assert data["fixture"]["goals"] == original["GOALS"]
    robust = load_dataset("robustness")
    assert robust[1]["count"] == 18
    plan = [row for row, _, _ in runner.schedule(MODELS, [A, B], {"baseline": (data, spec),
                                                                   "robustness": robust}, 3)]
    assert sum(row["dataset"] == "baseline" for row in plan) == 180
    assert len(plan) == 396
    assert all(row["model"] == MODELS[0] for row in plan[:198])
    assert [next(row["architecture"] for row in plan if row["repeat"] == n) for n in (1, 2, 3)] == [A, B, A]


def test_raw_name_arguments_and_exact_call_have_different_denominators():
    expected = [{"tool": "replace_food", "input": {"old_food": "x", "new_food": "y"}}]
    wrong_tool = [{"tool": "other", "input": expected[0]["input"]}]
    assert raw_scores(wrong_tool, expected) == {
        "name": False, "arguments": True, "arguments_given_name": None, "calling": False,
    }
    assert raw_scores(expected, expected)["calling"]
    assert not raw_scores([], expected)["calling"]


def test_frozen_expectations_replay_without_real_inference():
    from agent import InferenceConfig

    for dataset in ("baseline", "robustness"):
        data, _ = load_dataset(dataset)
        for case in data["cases"]:
            for architecture in (A, B):
                expected = case["raw"][architecture][0]

                def respond(request):
                    request_messages = json.loads(request.content)["messages"]
                    calls = [] if request_messages[-1]["role"] == "tool" else [
                        {"function": {"name": expected["tool"], "arguments": expected["input"]}}
                    ]
                    return httpx.Response(200, json={"message": {"role": "assistant", "tool_calls": calls}})

                with_client = ollama.Client(host="http://ollama.test", transport=httpx.MockTransport(respond))
                result = evaluate_case(case, data["fixture"], architecture, InferenceConfig(), with_client)
                assert result["scores"]["raw"]["calling"], (case["id"], architecture, result)
                # Legacy's rejected-amount bug is an expected difference in the defense layer.
                expected_execution = not (case["id"] == "negated-keep" and architecture == A)
                assert result["scores"]["effective"] == expected_execution, (case["id"], architecture, result)


def test_runner_persists_one_row_per_case_with_independent_scores(tmp_path, monkeypatch):
    # This fixture is for the transport test and is separate from the two frozen datasets.
    items = [{"food": "닭가슴살", "quantity": 50, "unit": "g"}]
    names = {"old_food": "닭가슴살", "new_food": "두부"}
    case = {"id": "test-fixture", "history": [{"role": "user", "content": "닭가슴살 대신 두부를 부탁해."}],
            "prior_meal": "single",
            "raw": {arch: [{"tool": "replace_food", "input": names}] for arch in (A, B)},
            "effective": {"type": "recommendation", "lines": [["두부", 50]], "records_unchanged": True}}
    fixture = {"prior_meals": {"single": items}, "confirmed_meal": items, "confirmed_date": "2026-01-01", "goals": {}}
    monkeypatch.setattr(runner, "load_dataset", lambda _: (
        {"version": "test", "cases": [case], "fixture": fixture}, {"version": "test", "sha256": "test"},
    ))
    requests = []

    def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"model": MODELS[0], "digest": "sha256:fake"}]})
        body = json.loads(request.content)
        requests.append(body)
        calls = [] if not body.get("tools") else [{"function": {"name": "replace_food_with_weight",
                                                                "arguments": {**names, "quantity": 50, "unit": "g"}}}]
        return httpx.Response(200, json={"model": MODELS[0], "message": {"role": "assistant", "tool_calls": calls},
                                        "prompt_eval_count": 40, "eval_count": 10,
                                        "load_duration": 0, "eval_duration": 100_000_000})

    client = ollama.Client(host="http://ollama.test", transport=httpx.MockTransport(respond))
    metadata = runner.run_experiment(tmp_path, MODELS, [B], ["baseline"], 2, client=client)
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert metadata["status"] == "complete" and metadata["source"] == "test_transport"
    assert len(requests) == 3 and not requests[0].get("tools")  # one untimed warm-up, then two trials
    assert len(rows) == 4 and rows[0]["model_digest"] == "sha256:fake"
    assert rows[0]["raw_calls"][0]["tool"] == "replace_food_with_weight"
    assert rows[0]["executed_calls"][0]["tool"] == "replace_food"
    assert rows[0]["scores"]["effective"] and not rows[0]["scores"]["raw"]["calling"]
    assert rows[2]["status"] == "model_not_installed" and rows[2]["scores"] is None
    summary = analyze(tmp_path)
    write_summary(tmp_path, summary)
    assert summary["infrastructure"] == {"model_not_installed": 2}
    assert all((tmp_path / filename).is_file() for filename in ("summary.json", "summary.csv", "summary.md"))
    with pytest.raises(FileExistsError):
        runner.run_experiment(tmp_path, MODELS, [B], ["baseline"], 1, client=client)


def test_analysis_statistics_infrastructure_missing_and_consistency(tmp_path):
    model = MODELS[0]
    ids = [{"model": model, "architecture": arch, "dataset": "baseline", "repeat": repetition, "case_id": "x"}
           for arch in (A, B) for repetition in range(1, 5)]
    meta = {"run_id": "fixed", "source": "test_transport", "evaluation_version": "test", "status": "running",
            "schedule": ids, "warm_cold": {"cold_load_ms_min": 100}}
    runner.dump(tmp_path / "metadata.json", meta)

    def evaluated(index, time, *, ok, cold=False, question=False):
        return {**ids[index], "status": "evaluated", "run_id": "fixed", "agent_ms": time,
                "calls": [{"load_ms": 120 if cold else 2, "prompt_tokens": 7, "output_tokens": 5,
                           "generation_ms": 50}],
                "scores": {"raw": {"name": ok, "arguments": True, "arguments_given_name": True if ok else None,
                                   "calling": ok}, "effective": not question, "raw_clarification": None,
                           "effective_clarification": None, "unnecessary_clarification": question},
                "actual": {"type": "clarification" if question else "recommendation"},
                "raw_calls": [{"tool": "correct" if ok else "other"}],
                "failure_reasons": [] if ok else ["raw_tool_name"],
                "corrections": [] if ok else [{"type": "tool_corrected"}]}

    rows = [evaluated(0, 100, ok=True), evaluated(1, 200, ok=False), evaluated(2, 500, ok=False, cold=True),
            {**ids[3], "status": "timeout", "run_id": "fixed"},
            evaluated(4, 200, ok=True), evaluated(5, 300, ok=True, question=True)]
    log = tmp_path / "results.jsonl"
    log.write_text("\n".join(json.dumps(row) for row in rows + [rows[0]]) + '\n{"partial":', encoding="utf-8")
    summary = analyze(tmp_path)
    assert not summary["complete"] and summary["infrastructure"] == {"timeout": 1}
    assert len(summary["missing"]) == 2 and summary["duplicate_lines"] == [7] and summary["malformed_lines"] == [8]
    legacy, split = summary["groups"]
    assert legacy["performance"]["agent_ms"] == {"count": 3, "mean": pytest.approx(800 / 3),
                                                   "median": 200, "p95": 500}
    assert legacy["performance"]["latency_by_load"]["warm"]["mean"] == 150
    assert legacy["performance"]["latency_by_load"]["cold"]["count"] == 1
    assert legacy["performance"]["generation_tokens_per_second"] == 100
    assert legacy["scores"]["raw_arguments"]["percent"] == 100
    assert legacy["scores"]["raw_arguments_given_name"] == {"passed": 1, "total": 1, "percent": 100}
    assert legacy["scores"]["corrected_or_blocked"]["passed"] == 2
    assert legacy["failure_types"] == {"raw_tool_name": 2}
    assert legacy["consistency"]["raw"]["percent"] == 0 and legacy["consistency"]["effective"]["percent"] == 100
    assert split["scores"]["unnecessary_clarification"]["percent"] == 50
    assert summary["ab"][0]["raw_delta_pp"] == 50 and summary["ab"][0]["paired_cases"] == 2
    assert not summary["ab"][0]["coverage_equal"]
