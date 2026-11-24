"""Analyze a run directory. Launch with python -m evaluation.analyze_tool_architecture DIRECTORY."""

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from evaluation.run_tool_architecture import dump


def _identity(row):
    return tuple(row[key] for key in ("model", "architecture", "dataset", "repeat", "case_id"))


def _count_rate(values):
    values = [value for value in values if value is not None]
    passed = sum(bool(value) for value in values)
    return {"passed": passed, "total": len(values), "percent": 100 * passed / len(values) if values else None}


def _statistics(values):
    values = sorted(value for value in values if value is not None)
    return {"count": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None,
            "p95": values[math.ceil(0.95 * len(values)) - 1] if values else None}


def _call_sum(calls, field):
    values = [call.get(field) for call in calls]
    return sum(values) if values and all(value is not None for value in values) else None


def _temperature_class(calls, threshold):
    values = [call.get("load_ms") for call in calls]
    if any(value is not None and value >= threshold for value in values):
        return "cold"
    if values and all(value is not None for value in values):
        return "warm"
    return "unknown"


def _performance(rows, threshold):
    grouped = defaultdict(list)
    prompts, completions, call_counts = [], [], []
    generation_tokens, generation_ms = 0, 0
    for row in rows:
        calls = row.get("calls", [])
        grouped[_temperature_class(calls, threshold)].append(row.get("agent_ms"))
        prompts.append(_call_sum(calls, "prompt_tokens"))
        completions.append(_call_sum(calls, "output_tokens"))
        call_counts.append(len(calls))
        for call in calls:
            if call.get("output_tokens") is not None and call.get("generation_ms"):
                generation_tokens += call["output_tokens"]
                generation_ms += call["generation_ms"]
    return {"agent_ms": _statistics([row.get("agent_ms") for row in rows]),
            "latency_by_load": {name: _statistics(grouped[name]) for name in ("warm", "cold", "unknown")},
            "prompt_tokens": _statistics(prompts), "output_tokens": _statistics(completions),
            "inference_calls": _statistics(call_counts),
            "generation_tokens_per_second": 1000 * generation_tokens / generation_ms if generation_ms else None}


def _fingerprint(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _consistency(rows):
    cases = defaultdict(list)
    for row in rows:
        cases[row["case_id"]].append(row)
    repeats = [values for values in cases.values() if len(values) >= 2]
    return {
        "raw": _count_rate(len({_fingerprint(row.get("raw_calls", [])) for row in values}) == 1 for values in repeats),
        "effective": _count_rate(len({_fingerprint(row["actual"]) for row in values}) == 1 for values in repeats),
        "clarification": _count_rate(
            len({(row["actual"]["type"] == "clarification", row["actual"].get("kind")) for row in values}) == 1
            for values in repeats
        ),
    }


def _summary(rows, planned, threshold):
    assessed = [row for row in rows if row["status"] == "evaluated"]
    return {
        "planned": planned, "recorded": len(rows), "missing": planned - len(rows), "evaluated": len(assessed),
        "infrastructure": dict(Counter(row["status"] for row in rows if row["status"] != "evaluated")),
        "scores": {
            **{f"raw_{key}": _count_rate(row["scores"]["raw"][key] for row in assessed)
               for key in ("name", "arguments", "arguments_given_name", "calling")},
            **{key: _count_rate(row["scores"][key] for row in assessed)
               for key in ("effective", "raw_clarification", "effective_clarification", "unnecessary_clarification")},
            "corrected_or_blocked": _count_rate(bool(row["corrections"]) for row in assessed),
        },
        "failure_types": dict(Counter(reason for row in assessed for reason in row["failure_reasons"])),
        "correction_types": dict(Counter(action["type"] for row in assessed for action in row["corrections"])),
        "consistency": _consistency(assessed), "performance": _performance(assessed, threshold),
    }


def _ab(groups, rows_by_group, threshold):
    pairs = defaultdict(dict)
    for group in groups:
        pairs[(group["model"], group["dataset"])][group["architecture"]] = group

    def diff(a, b, *, relative=False):
        if a is None or b is None or (relative and a == 0):
            return None
        return 100 * (b - a) / a if relative else b - a

    results = []
    for (model, dataset), group in pairs.items():
        if set(group) != {"LEGACY", "SPLIT"}:
            continue
        a, b = group["LEGACY"], group["SPLIT"]
        indices = {
            arch: {(row["case_id"], row["repeat"]): row for row in rows_by_group[(model, arch, dataset)]
                   if row["status"] == "evaluated"}
            for arch in ("LEGACY", "SPLIT")
        }
        paired = sorted(indices["LEGACY"].keys() & indices["SPLIT"].keys())
        match_a, match_b = (
            _summary([indices[arch][key] for key in paired], len(paired), threshold)
            for arch in ("LEGACY", "SPLIT")
        )
        results.append({"model": model, "dataset": dataset,
                        "raw_delta_pp": diff(match_a["scores"]["raw_calling"]["percent"],
                                             match_b["scores"]["raw_calling"]["percent"]),
                        "effective_delta_pp": diff(match_a["scores"]["effective"]["percent"],
                                                   match_b["scores"]["effective"]["percent"]),
                        "agent_latency_change_percent": diff(match_a["performance"]["agent_ms"]["mean"],
                                                             match_b["performance"]["agent_ms"]["mean"], relative=True),
                        "warm_latency_change_percent": diff(match_a["performance"]["latency_by_load"]["warm"]["mean"],
                                                            match_b["performance"]["latency_by_load"]["warm"]["mean"],
                                                            relative=True),
                        "paired_cases": len(paired),
                        "coverage_equal": indices["LEGACY"].keys() == indices["SPLIT"].keys(),
                        "complete_evaluation": a["evaluated"] == a["planned"] and b["evaluated"] == b["planned"]})
    return results


def analyze(directory):
    meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    planned = {_identity(row): row for row in meta["schedule"]}
    valid, malformed, duplicate, unexpected = {}, [], [], []
    log = directory / "results.jsonl"
    if log.is_file():
        with log.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                    key = _identity(row)
                    if row["run_id"] != meta["run_id"] or key not in planned:
                        unexpected.append(number)
                    elif key in valid:
                        duplicate.append(number)
                    elif row["status"] == "evaluated" and not {"scores", "actual", "corrections",
                                                               "failure_reasons"}.issubset(row):
                        malformed.append(number)
                    else:
                        valid[key] = row
                except (ValueError, KeyError, TypeError):
                    malformed.append(number)

    threshold = meta["warm_cold"]["cold_load_ms_min"]
    by_group, by_case = defaultdict(list), defaultdict(list)
    case_plan = Counter()
    group_plan = Counter()
    missing = []
    for key, ids in planned.items():
        group_key = key[:3]
        case_key = (*group_key, key[4])
        group_plan[group_key] += 1
        case_plan[case_key] += 1
        if key in valid:
            by_group[group_key].append(valid[key])
            by_case[case_key].append(valid[key])
        else:
            missing.append(ids)
    group_fields = ("model", "architecture", "dataset")
    groups = [{**dict(zip(group_fields, key, strict=True)),
               **_summary(by_group[key], count, threshold)} for key, count in group_plan.items()]
    cases = [{**dict(zip((*group_fields, "case_id"), key, strict=True)),
              **_summary(by_case[key], count, threshold)} for key, count in case_plan.items()]
    return {"evaluation_version": meta["evaluation_version"], "run_id": meta["run_id"], "source": meta["source"],
            "complete": meta["status"] == "complete" and not (missing or malformed or duplicate or unexpected),
            "planned": len(planned), "recorded": len(valid), "missing": missing,
            "malformed_lines": malformed, "duplicate_lines": duplicate, "unexpected_lines": unexpected,
            "infrastructure": dict(Counter(row["status"] for row in valid.values() if row["status"] != "evaluated")),
            "groups": groups, "cases": cases, "ab": _ab(groups, by_group, threshold)}


def write_summary(directory, result):
    dump(directory / "summary.json", result)
    with (directory / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["model", "architecture", "dataset", "case", "planned", "recorded", "evaluated",
                         "raw_name_percent", "raw_arguments_percent", "raw_arguments_given_name_percent",
                         "raw_calling_percent", "effective_percent", "raw_clarification_percent",
                         "effective_clarification_percent", "unnecessary_clarification_percent",
                         "corrected_or_blocked_percent", "mean_ms", "median_ms", "p95_ms", "warm_mean_ms",
                         "cold_mean_ms", "prompt_tokens_mean", "inference_calls_mean", "generation_tokens_per_second"])
        score_keys = ("raw_name", "raw_arguments", "raw_arguments_given_name", "raw_calling", "effective",
                      "raw_clarification", "effective_clarification", "unnecessary_clarification",
                      "corrected_or_blocked")
        for item in result["groups"] + result["cases"]:
            perf = item["performance"]
            writer.writerow([item["model"], item["architecture"], item["dataset"], item.get("case_id", ""),
                             item["planned"], item["recorded"], item["evaluated"],
                             *(item["scores"][key]["percent"] for key in score_keys),
                             *(perf["agent_ms"][key] for key in ("mean", "median", "p95")),
                             perf["latency_by_load"]["warm"]["mean"], perf["latency_by_load"]["cold"]["mean"],
                             perf["prompt_tokens"]["mean"], perf["inference_calls"]["mean"],
                             perf["generation_tokens_per_second"]])

    def number(value):
        return "—" if value is None else f"{value:.2f}"

    markdown = ["# Tool architecture evaluation", "",
                f"Source **{result['source']}** · {'complete' if result['complete'] else 'incomplete'}",
                f"Recorded {result['recorded']}/{result['planned']} · "
                f"infrastructure {sum(result['infrastructure'].values())} · missing {len(result['missing'])}", "",
                "| Model | Architecture | Dataset | Evaluated | Raw % | Effective % | Mean ms | P95 ms |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for item in result["groups"]:
        scores, timings = item["scores"], item["performance"]["agent_ms"]
        markdown.append(f"| {item['model']} | {item['architecture']} | {item['dataset']} | {item['evaluated']} | "
                        f"{number(scores['raw_calling']['percent'])} | {number(scores['effective']['percent'])} | "
                        f"{number(timings['mean'])} | {number(timings['p95'])} |")
    markdown += ["", "## SPLIT minus LEGACY", "",
                 "| Model | Dataset | Paired | Raw Δ pp | Effective Δ pp | Mean latency Δ % | Complete evaluation |",
                 "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for pair in result["ab"]:
        markdown.append(f"| {pair['model']} | {pair['dataset']} | {pair['paired_cases']} | {number(pair['raw_delta_pp'])} | "
                        f"{number(pair['effective_delta_pp'])} | {number(pair['agent_latency_change_percent'])} | "
                        f"{pair['complete_evaluation']} |")
    markdown += ["", "See summary.json for case counts, clarification, corrections, and repeat consistency."]
    (directory / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    summary = analyze(args.directory)
    write_summary(args.directory, summary)
    print(f"Summary output: {args.directory.resolve()}")
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
