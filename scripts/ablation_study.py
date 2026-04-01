"""
Scientifically measures the impact of each harness component.
Run against a fixed PLAN.md to get comparable results.

Usage:
    python scripts/ablation_study.py --plan workspace/PLAN.md
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RunResult:
    label: str
    disabled: list[str]
    tasks_total: int = 0
    tasks_first_attempt: int = 0
    total_retries: int = 0
    wall_seconds: float = 0.0
    error: str = ""

    def efficiency(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return self.tasks_first_attempt / self.tasks_total


ABLATION_MATRIX = [
    {"label": "Baseline (full harness)",   "disabled": []},
    {"label": "No WisdomRAG",              "disabled": ["wisdom_rag"]},
    {"label": "No contract negotiation",   "disabled": ["contract_negotiation"]},
    {"label": "Single model (no routing)", "disabled": ["model_routing"]},
    {"label": "No Playwright eval",        "disabled": ["playwright"]},
]


def patch_config(base_yaml: dict, disabled: list[str]) -> dict:
    """Return a deep-copied, patched config dict without mutating the original."""
    cfg = copy.deepcopy(base_yaml)
    if "wisdom_rag" in disabled:
        cfg.setdefault("orchestration", {})["wisdom_rag"] = False
    if "contract_negotiation" in disabled:
        cfg.setdefault("orchestration", {})["test_first"] = False
    if "model_routing" in disabled:
        cheapest = cfg.get("models", {}).get("generator", "claude-sonnet-4-6")
        for role in ("planner", "evaluator", "contract_verifier"):
            cfg.setdefault("models", {})[role] = cheapest
    if "playwright" in disabled:
        cfg.setdefault("evaluation", {})["strategy"] = "exit_code"
    return cfg


def run_harness(config_patch: dict, plan_path: str) -> RunResult:
    """Write a temp harness.yaml, run the orchestrator, read trajectories.jsonl."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, dir="."
    )
    yaml.dump(config_patch, tmp)
    tmp.close()

    start = time.time()
    proc = subprocess.run(
        ["python", "core/main.py", "--config", tmp.name, "--plan", plan_path],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    elapsed = time.time() - start
    os.unlink(tmp.name)

    result = RunResult(label="", disabled=[], wall_seconds=elapsed)
    if proc.returncode != 0:
        result.error = proc.stderr[-500:]
        return result

    traj_path = Path(
        config_patch.get("paths", {}).get("distillation_export", "docs/trajectories.jsonl")
    )
    if traj_path.exists():
        for line in traj_path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            result.tasks_total += 1
            result.total_retries += entry.get("attempts", 1) - 1
            if entry.get("attempts", 1) == 1:
                result.tasks_first_attempt += 1

    return result


def print_table(results: list[RunResult]) -> None:
    print("\n" + "=" * 80)
    print("HARNESS ABLATION STUDY — RESULTS")
    print("=" * 80)
    header = (
        f"{'Configuration':<36} {'Tasks':>6} {'1st-pass%':>10} "
        f"{'Retries':>8} {'Time(s)':>9} {'Verdict':>12}"
    )
    print(header)
    print("-" * 80)

    baseline = results[0] if results else None
    for r in results:
        if r.error:
            print(f"{r.label:<36} {'ERROR':>6}  {r.error[:30]}")
            continue

        pct = f"{r.efficiency() * 100:.0f}%"
        verdict = "baseline"
        if baseline and r.label != baseline.label:
            delta = r.efficiency() - baseline.efficiency()
            if delta < -0.05:
                verdict = "ESSENTIAL ✓"
            elif delta > 0.05:
                verdict = "redundant ✗"
            else:
                verdict = "neutral ~"

        print(
            f"{r.label:<36} {r.tasks_total:>6} {pct:>10} "
            f"{r.total_retries:>8} {r.wall_seconds:>9.1f} {verdict:>12}"
        )

    print("=" * 80)
    print("\nLegend:")
    print("  ESSENTIAL ✓  — removing this component drops first-pass rate >5%")
    print("  redundant ✗  — safe to remove for this model/task combination")
    print("  neutral   ~  — no measurable impact\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="HarnessLab ablation study")
    parser.add_argument("--plan",   default="workspace/PLAN.md")
    parser.add_argument("--config", default="harness.yaml")
    args = parser.parse_args()

    base_cfg = yaml.safe_load(Path(args.config).read_text())
    results: list[RunResult] = []

    for scenario in ABLATION_MATRIX:
        print(f"\nRunning: {scenario['label']} ...")
        patched = patch_config(base_cfg, scenario["disabled"])
        result = run_harness(patched, args.plan)
        result.label = scenario["label"]
        result.disabled = scenario["disabled"]
        results.append(result)
        print(
            f"  Done in {result.wall_seconds:.1f}s — "
            f"{result.tasks_first_attempt}/{result.tasks_total} first-pass"
        )

    print_table(results)

    out = Path("docs/ablation_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.__dict__ for r in results], indent=2))
    print(f"Full results written → {out}")


if __name__ == "__main__":
    main()
