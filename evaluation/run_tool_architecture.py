"""Run the fixed Ollama A/B experiment. Launch with python -m evaluation.run_tool_architecture."""

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import ollama

from agent import InferenceConfig, ToolArchitecture, ollama_error_kind, tool_definition
from evaluation.core import EVALUATION_VERSION, evaluate_case, load_dataset

MODELS = ("qwen3:8b", "qwen3.5:9b-q4_K_M")


def dump(path, value):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def _server_version():
    endpoint = os.getenv("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
    if "://" not in endpoint:
        endpoint = "http://" + endpoint
    try:
        host = urlsplit(endpoint)
        default_port = 443 if host.scheme == "https" else 11434
        netloc = host.netloc if host.port is not None else f"{host.netloc}:{default_port}"
        address = urlunsplit((host.scheme, netloc, host.path.rstrip("/") + "/api/version", "", ""))
        with httpx.Client(timeout=5) as client:
            response = client.get(address)
            response.raise_for_status()
            return response.json()["version"]
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def _git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _gpu_details():
    try:
        return subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).splitlines()
    except (OSError, subprocess.SubprocessError):
        return None


def schedule(models, architectures, datasets, repeats):
    for model in models:
        for repetition in range(1, repeats + 1):
            order = architectures if repetition % 2 else reversed(architectures)
            for architecture in order:
                for dataset, (data, _) in datasets.items():
                    for case in data["cases"]:
                        yield {"model": model, "architecture": architecture, "dataset": dataset,
                               "repeat": repetition, "case_id": case["id"]}, case, data["fixture"]


def _prompt_sizes(architectures):
    result = {}
    for arch in architectures:
        prompt, tools = tool_definition(arch)
        wire_tools = [ollama.Tool.model_validate(tool).model_dump(exclude_none=True) for tool in tools]
        result[arch] = {"system_utf8_bytes": len(prompt.encode("utf-8")),
                        "tool_json_utf8_bytes": len(json.dumps(wire_tools, ensure_ascii=False,
                                                               separators=(",", ":")).encode("utf-8"))}
    return result


def _warmup(client, settings):
    return client.chat(model=settings.model, messages=[{"role": "user", "content": "Say hello briefly."}],
                       think=settings.think, keep_alive=settings.keep_alive,
                       options={"temperature": settings.temperature, "num_ctx": settings.num_ctx,
                                "num_predict": settings.num_predict})


def _model_tag(model):
    return model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"


def run_experiment(output, models, architectures, datasets, repeats, *, client=None):
    if repeats < 1:
        raise ValueError("repeats must be positive")
    models = list(dict.fromkeys(models))
    architectures = list(dict.fromkeys(ToolArchitecture(value) for value in architectures))
    datasets = {name: load_dataset(name) for name in datasets}
    plan = list(schedule(models, architectures, datasets, repeats))
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "results.jsonl"
    metadata_path = output / "metadata.json"
    if metadata_path.exists() or log_path.exists():
        raise FileExistsError(f"Evaluation exists in {output}; choose a new directory")
    run_id = uuid4().hex
    source = "test_transport" if client is not None else "ollama"
    metadata = {"evaluation_version": EVALUATION_VERSION, "run_id": run_id, "source": source,
                "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                "git_sha": _git_head(), "platform": platform.platform(), "python": platform.python_version(),
                "gpu_inventory": _gpu_details() if source == "ollama" else None, "agent_mode": "OLLAMA",
                "datasets": {name: spec for name, (_, spec) in datasets.items()},
                "architectures": architectures, "models": {}, "repeat_count": repeats,
                "settings": asdict(InferenceConfig()), "architecture_sizes": _prompt_sizes(architectures),
                "warm_cold": {"cold_load_ms_min": 100, "missing_load_duration": "unknown"},
                "order": "model blocks; alternate architecture order; fixed dataset case order",
                "planned_rows": len(plan), "schedule": [ids for ids, _, _ in plan]}
    metadata["settings"].pop("model")
    dump(metadata_path, metadata)
    model_client = client if client is not None else ollama.Client(timeout=90)
    persisted = 0
    infrastructure = 0
    try:
        with log_path.open("x", encoding="utf-8", newline="\n") as stream:
            try:
                tags = {entry.model: entry for entry in model_client.list().models}
                connection_problem = None
                metadata["ollama_server_version"] = _server_version() if source == "ollama" else None
            except Exception as error:
                connection_problem = ollama_error_kind(error)
                tags = {}
            for model in models:
                tag = _model_tag(model)
                installed = tags.get(tag)
                settings = replace(InferenceConfig(), model=model)
                model_meta = {"digest": installed.digest if installed else None, "tag": tag,
                              "installed": None if connection_problem else installed is not None,
                              "warmup": "not_run"}
                metadata["models"][model] = model_meta
                problem = connection_problem or (None if installed is not None else "model_not_installed")
                if problem is None:
                    try:
                        warmup = _warmup(model_client, settings)
                        model_meta["warmup"] = "ok"
                        model_meta["served_model"] = warmup.model
                    except Exception as error:
                        problem = ollama_error_kind(error)
                        model_meta["warmup"] = problem
                dump(metadata_path, metadata)
                for ids, case, fixture in plan:
                    if ids["model"] != model:
                        continue
                    arch = ids["architecture"]
                    row = {**ids, "evaluation_version": EVALUATION_VERSION, "run_id": run_id,
                           "dataset_version": metadata["datasets"][ids["dataset"]]["version"],
                           "model_digest": model_meta["digest"], "settings": asdict(settings),
                           "request": case["history"][-1]["content"], "history": case["history"],
                           "prior_meal": fixture["prior_meals"].get(case["prior_meal"]),
                           "confirmed_fixture": fixture["confirmed_meal"], "goals": fixture["goals"],
                           "expected_raw": case["raw"][arch], "expected_effective": case["effective"],
                           "calls": [], "raw_calls": [], "executed_calls": [], "actual": None, "scores": None,
                           "agent_ms": None, "corrections": [], "failure_reasons": []}
                    if problem is None:
                        try:
                            row.update(evaluate_case(case, fixture, arch, settings, model_client))
                        except Exception as error:
                            row.update(status=ollama_error_kind(error), error_type=type(error).__name__)
                    else:
                        row["status"] = problem
                    if row["status"] != "evaluated":
                        infrastructure += 1
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    persisted += 1
                    print(f"[{persisted}/{len(plan)}] {model} {arch} {ids['dataset']}/{ids['case_id']} "
                          f"repeat {ids['repeat']} {row['status']}", flush=True)
    finally:
        metadata.update(status="complete" if persisted == len(plan) else "incomplete",
                        written_rows=persisted, infrastructure_rows=infrastructure,
                        finished_at=datetime.now(timezone.utc).isoformat())
        dump(metadata_path, metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument("--architectures", nargs="+", choices=list(ToolArchitecture),
                        default=list(ToolArchitecture))
    parser.add_argument("--datasets", nargs="+", choices=("baseline", "robustness"),
                        default=["baseline", "robustness"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = (args.output_dir or Path("evaluation-results") / f"tool-architecture-{stamp}-{uuid4().hex[:6]}").resolve()
    print(f"Evaluation output: {output}", flush=True)
    metadata = run_experiment(output, args.models, args.architectures, args.datasets, args.repeats)
    return 2 if metadata["status"] != "complete" or metadata["infrastructure_rows"] else 0


if __name__ == "__main__":
    sys.exit(main())
