"""Frozen cases and independent raw-call and execution scoring."""

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date
from pathlib import Path

from agent import Mode, QUESTIONS, REPLACEMENT_QUESTION, run_turn
from nutrition import calculate
from nutrigap import IntakeRecord, confirmed_totals

DATASETS = Path(__file__).with_name("datasets")
EVALUATION_VERSION = "1.4.2"


def load_dataset(name):
    manifest = json.loads((DATASETS / "manifest.json").read_text(encoding="utf-8"))
    spec = manifest[name]
    content = (DATASETS / spec["file"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != spec["sha256"]:
        raise ValueError(f"Dataset {name} SHA-256 mismatch")
    data = json.loads(content)
    case_ids = [case["id"] for case in data["cases"]]
    if data["version"] != spec["version"] or len(case_ids) != spec["count"] or len(set(case_ids)) != len(case_ids):
        raise ValueError(f"Dataset {name} manifest mismatch")
    return data, spec


def raw_scores(calls, expected):
    names = {call["tool"] for call in expected}
    # As in the original strict check, use the last call with a permitted name.
    chosen = next((call for call in reversed(calls) if call["tool"] in names), calls[-1] if calls else None)
    name_ok = chosen is not None and chosen["tool"] in names
    arguments_ok = chosen is not None and any(chosen["input"] == call["input"] for call in expected)
    full = chosen in expected
    return {"name": name_ok, "arguments": arguments_ok, "arguments_given_name": full if name_ok else None,
            "calling": full}


def _clarification_kind(text):
    if text == QUESTIONS["meal"]:
        return "meal"
    if text == QUESTIONS["food"]:
        return "food"
    if "등록되지 않았습니다" in text:
        return "unregistered"
    if text in {QUESTIONS["quantity"], REPLACEMENT_QUESTION} or "1인분 중량은 검증되지" in text:
        return "quantity"
    return "other"


def _result(reply, records_unchanged):
    if reply.meal is not None:
        return {
            "type": reply.kind,
            "lines": [[line.food["name"], line.grams] for line in reply.meal.lines],
            "nutrients": reply.meal.totals,
            "goal_gap": asdict(reply.impact) if reply.impact else None,
            "candidate": reply.candidates[0].name if reply.candidates else None,
            "records_unchanged": records_unchanged,
        }
    if reply.food is not None:
        return {"type": "lookup", "food": reply.food["name"], "nutrients": reply.food["per_100g"],
                "records_unchanged": records_unchanged}
    if reply.needs_clarification:
        return {"type": "clarification", "kind": _clarification_kind(reply.text),
                "question": reply.text, "records_unchanged": records_unchanged}
    return {"type": "none", "records_unchanged": records_unchanged}


def _matches(actual, expected):
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isclose(actual, expected, abs_tol=1e-8))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            _matches(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _matches(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def _corrections(entries, clarified, effective_ok):
    actions = []
    applied = False
    for entry in entries:
        executed = entry.get("executed_tool")
        if executed is not None and executed != entry["tool"]:
            actions.append({"type": "tool_corrected", "reason": "user_amount_selected_other_swap_tool"})
            applied = True
        if "effective_input" in entry:
            original, actual = entry["input"], entry["effective_input"]
            if original.keys() - actual.keys():
                actions.append({"type": "arguments_removed", "reason": "arguments_not_grounded_or_not_supported"})
            if any(original.get(key) != value or key not in original for key, value in actual.items()):
                actions.append({"type": "arguments_corrected", "reason": "quantity_and_unit_grounded_in_request"})
            applied = True
        if entry["validation"] == "blocked":
            actions.append({"type": "execution_blocked", "reason": entry["status"]})
    if clarified and any(action["type"] == "execution_blocked" for action in actions):
        actions.append({"type": "clarification_redirected", "reason": "validation_block"})
    if applied and not effective_ok:
        actions.append({"type": "corrected_result_failed", "reason": "execution_did_not_meet_case_expectation"})
    return actions


def evaluate_case(case, fixture, architecture, settings, client):
    prior_items = fixture["prior_meals"].get(case["prior_meal"])
    previous = calculate(prior_items) if prior_items is not None else None
    confirmed = calculate(fixture["confirmed_meal"])
    day = date.fromisoformat(fixture["confirmed_date"])
    ledger = [IntakeRecord(day, confirmed)]
    snapshot = [asdict(record) for record in ledger]
    totals = confirmed_totals(ledger, day)
    original_totals = totals.copy()
    reply = run_turn(case["history"], previous, mode=Mode.OLLAMA, goals=fixture["goals"],
                     today_totals=totals, settings=settings, architecture=architecture, client=client)
    telemetry = {"served_model": reply.served_model, "agent_ms": reply.agent_ms,
                 "calls": [asdict(call) for call in reply.inference], "raw_calls": reply.raw_calls}
    executed = [{
        "tool": entry.get("executed_tool"),
        "input": entry.get("effective_input", entry["input"]) if entry.get("executed_tool") else None,
        "validation": entry["validation"], "reason": entry["status"],
    } for entry in reply.tool_log]
    telemetry["executed_calls"] = executed
    if reply.infrastructure_error:
        return {"status": reply.infrastructure_error, **telemetry}

    expected = case["effective"]
    actual = _result(reply, [asdict(record) for record in ledger] == snapshot and totals == original_totals)
    failures = [key for key, value in expected.items() if not _matches(actual.get(key), value)]
    raw = raw_scores(reply.raw_calls, case["raw"][architecture])
    expects_question = expected["type"] == "clarification"
    expected_tools = case["raw"][architecture]
    question_tools = [call for call in expected_tools if call["tool"] == "ask_clarification"]
    if expects_question and expected["kind"] in {"food", "meal", "quantity"} and not question_tools:
        question_tools = [{"tool": "ask_clarification", "input": {"missing": expected["kind"]}}]
    raw_question = raw_scores(reply.raw_calls, question_tools)["calling"] if question_tools else None
    actions = _corrections(reply.tool_log, actual["type"] == "clarification", not failures)
    return {
        "status": "evaluated", **telemetry, "actual": actual,
        "scores": {"raw": raw, "effective": not failures, "expects_clarification": expects_question,
                   "raw_clarification": raw_question if expects_question else None,
                   "effective_clarification": not failures if expects_question else None,
                   "unnecessary_clarification": actual["type"] == "clarification" if not expects_question else None},
        "corrections": actions,
        "failure_reasons": (["raw_tool_name"] if not raw["name"] else [])
                           + (["raw_arguments"] if not raw["arguments"] else [])
                           + (["raw_tool_calling"] if not raw["calling"] else [])
                           + [f"effective_{key}" for key in failures],
    }
