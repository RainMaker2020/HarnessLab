"""Tests for core/hooks/pre_stop_check.sh — path resolution and silent-failure prevention."""
import subprocess
from pathlib import Path
import pytest

SCRIPT = Path(__file__).parent.parent / "core" / "hooks" / "pre_stop_check.sh"


def _make_harness(root: Path, plan_rel: str, tasks: list[str]) -> None:
    """Write a minimal harness.yaml and a PLAN.md with given task lines."""
    plan_path = root / plan_rel
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("\n".join(tasks) + "\n", encoding="utf-8")
    (root / "harness.yaml").write_text(
        f'paths:\n  plan_file: "./{plan_rel}"\n', encoding="utf-8"
    )


def _run(root: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    # Override HARNESS_ROOT so the script operates on the temp directory
    env["HARNESS_ROOT"] = str(root)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def test_blocks_when_tasks_pending(tmp_path):
    """Script must exit 1 and print HARNESS BLOCK when unchecked tasks exist."""
    _make_harness(tmp_path, "project/workspace/PLAN.md", ["- [ ] TASK_01: foo"])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "HARNESS BLOCK" in r.stdout


def test_passes_when_all_tasks_done(tmp_path):
    """Script must exit 0 when all tasks are checked."""
    _make_harness(tmp_path, "project/workspace/PLAN.md", ["- [x] TASK_01: foo"])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_grep_fallback_finds_correct_path_when_python_yaml_unavailable(tmp_path):
    """When Python resolution produces empty output, grep fallback must read harness.yaml
    to find the correct plan_file path and still block on pending tasks."""
    # Write harness.yaml with a non-default path
    _make_harness(tmp_path, "project/workspace/PLAN.md", ["- [ ] TASK_01: pending"])
    # Force Python path to /nonexistent so the Python block silently fails
    r = _run(tmp_path, env_extra={"PATH": "/nonexistent:/usr/bin:/bin"})
    # Should still exit 1 (found plan via grep), NOT exit 0 silently
    assert r.returncode == 1
    assert "HARNESS BLOCK" in r.stdout


def test_fails_loudly_when_harness_yaml_missing_and_python_fails(tmp_path):
    """When harness.yaml is absent and Python resolution fails, script must exit 1
    with a clear error — NOT silently exit 0."""
    # No harness.yaml, no plan file — nothing
    r = _run(tmp_path, env_extra={"PATH": "/nonexistent:/usr/bin:/bin"})
    assert r.returncode == 1
    # Should print an error message, not silently pass
    assert r.stdout.strip() != "" or r.stderr.strip() != ""
