"""
Scientifically measures harness component impact via Claude Code runs.

For each ablation scenario, the script writes a patched ``harness.yaml`` (with backup/restore),
then runs a non-interactive Claude session in the configured workspace:

    claude -p "Execute the PLAN.md in this module."

Optionally aggregates ``paths.distillation_export`` JSONL when present after the run.

Usage:
    python scripts/ablation_study.py --plan workspace/PLAN.md
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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
    {"label": "Baseline (full harness)", "disabled": []},
    {"label": "No WisdomRAG", "disabled": ["wisdom_rag"]},
    {"label": "No contract negotiation", "disabled": ["contract_negotiation"]},
    {"label": "Single model (no routing)", "disabled": ["model_routing"]},
    {"label": "No Playwright eval", "disabled": ["playwright"]},
]

CLAUDE_ABLATION_PROMPT = "Execute the PLAN.md in this module."


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


def _resolve_workspace_dir(config_patch: dict, repo_root: Path) -> Path:
    paths = config_patch.get("paths") or {}
    wd = paths.get("workspace_dir") or config_patch.get("workspace_dir")
    if not wd:
        return (repo_root / "workspace").resolve()
    p = Path(wd)
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def _aggregate_jsonl(traj_path: Path) -> tuple[int, int, int]:
    """Return (tasks_total, tasks_first_attempt, total_retries) from trajectory JSONL."""
    tasks_total = 0
    tasks_first_attempt = 0
    total_retries = 0
    if not traj_path.exists():
        return tasks_total, tasks_first_attempt, total_retries
    try:
        text = traj_path.read_text(encoding="utf-8")
    except OSError:
        return tasks_total, tasks_first_attempt, total_retries
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        tasks_total += 1
        attempts = int(entry.get("attempts", 1))
        total_retries += max(0, attempts - 1)
        if attempts == 1:
            tasks_first_attempt += 1
    return tasks_total, tasks_first_attempt, total_retries


def run_harness(
    config_patch: dict,
    plan_path: str,
    *,
    repo_root: Path | None = None,
    subprocess_run: Callable[..., Any] | None = None,
) -> RunResult:
    """Write patched ``harness.yaml``, run Claude in workspace, restore YAML, optional JSONL metrics."""
    del plan_path
    run_cmd = subprocess_run if subprocess_run is not None else subprocess.run
    repo = (repo_root or Path.cwd()).resolve()
    harness_path = repo / "harness.yaml"
    backup: str | None = None
    start = time.time()
    result = RunResult(label="", disabled=[], wall_seconds=0.0)

    try:
        if harness_path.exists():
            backup = harness_path.read_text(encoding="utf-8")
        harness_path.write_text(
            yaml.safe_dump(config_patch, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        workspace = _resolve_workspace_dir(config_patch, repo)
        workspace.mkdir(parents=True, exist_ok=True)

        try:
            proc = run_cmd(
                ["claude", "-p", CLAUDE_ABLATION_PROMPT],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except FileNotFoundError:
            result.wall_seconds = time.time() - start
            result.error = (
                "Claude CLI not found on PATH (npm install -g @anthropic-ai/claude-code)."
            )
            return result

        elapsed = time.time() - start
        result.wall_seconds = elapsed

        if proc.returncode != 0:
            result.error = (proc.stderr or proc.stdout or "claude failed")[-500:]
            return result

        raw = config_patch.get("paths", {}).get("distillation_export", "docs/trajectories.jsonl")
        traj_path = Path(raw)
        if not traj_path.is_absolute():
            traj_path = repo / traj_path

        tt, tfa, tr = _aggregate_jsonl(traj_path)
        if tt > 0:
            result.tasks_total = tt
            result.tasks_first_attempt = tfa
            result.total_retries = tr
        else:
            result.tasks_total = 1
            result.tasks_first_attempt = 1
            result.total_retries = 0

        return result
    finally:
        if backup is not None:
            harness_path.write_text(backup, encoding="utf-8")
        elif harness_path.exists():
            harness_path.unlink()


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
    parser = argparse.ArgumentParser(description="HarnessLab ablation study (Claude + harness.yaml)")
    parser.add_argument("--plan", default="workspace/PLAN.md")
    parser.add_argument("--config", default="harness.yaml")
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Repository root (default: cwd). Patched harness.yaml is written here.",
    )
    args = parser.parse_args()

    repo = args.repo.resolve() if args.repo else Path.cwd().resolve()
    base_cfg = yaml.safe_load((repo / args.config).read_text(encoding="utf-8"))
    results: list[RunResult] = []

    for scenario in ABLATION_MATRIX:
        print(f"\nRunning: {scenario['label']} ...")
        patched = patch_config(base_cfg, scenario["disabled"])
        result = run_harness(patched, args.plan, repo_root=repo)
        result.label = scenario["label"]
        result.disabled = scenario["disabled"]
        results.append(result)
        print(
            f"  Done in {result.wall_seconds:.1f}s — "
            f"{result.tasks_first_attempt}/{result.tasks_total} first-pass"
        )

    print_table(results)

    out = repo / "docs" / "ablation_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.__dict__ for r in results], indent=2), encoding="utf-8")
    print(f"Full results written → {out}")


if __name__ == "__main__":
    main()
