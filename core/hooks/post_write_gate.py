#!/usr/bin/env python3
"""
Fires after every Write/Edit. Runs build command.
Exit 1 feeds the failure back to CC as context — it cannot ignore it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _workspace_dir_from_harness(repo: Path) -> Path | None:
    if yaml is None:
        return None
    cfg_path = repo / "harness.yaml"
    if not cfg_path.exists():
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text())
    except Exception:
        return None
    paths = cfg.get("paths") or {}
    wd = paths.get("workspace_dir") or cfg.get("workspace_dir")
    if not wd:
        return None
    p = Path(wd)
    return p.resolve() if p.is_absolute() else (repo / p).resolve()


def _path_is_under_workspace(repo: Path, written: str, workspace_abs: Path) -> bool:
    written = written.replace("\\", "/").strip()
    if not written:
        return False
    try:
        candidate = Path(written)
        if not candidate.is_absolute():
            candidate = (repo / written).resolve()
        else:
            candidate = candidate.resolve()
        candidate.relative_to(workspace_abs)
        return True
    except ValueError:
        return False
    except Exception:
        return False


# Only trigger on workspace writes
tool_input = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
try:
    inp = json.loads(tool_input)
    path = inp.get("path", "")
except Exception:
    sys.exit(0)

repo = _repo_root()
ws = _workspace_dir_from_harness(repo)
if ws is None:
    if "workspace/" not in path and not path.startswith("workspace/"):
        sys.exit(0)
else:
    if not _path_is_under_workspace(repo, path, ws):
        sys.exit(0)

# Read build command from harness.yaml
try:
    if yaml is None:
        sys.exit(0)
    cfg = yaml.safe_load((repo / "harness.yaml").read_text())
    eval_section = cfg.get("evaluation") or {}
    build_cmd = eval_section.get("build_command") or cfg.get("build_command")
    if not build_cmd:
        sys.exit(0)
except Exception:
    sys.exit(0)

# Skip placeholder
if "EVALUATOR_PLACEHOLDER" in build_cmd or build_cmd.strip() == "echo 'EVALUATOR_PLACEHOLDER: always passes'":
    sys.exit(0)

# Run build in workspace directory (same as ExitCodeEvaluator)
cwd = ws if ws is not None else repo / "workspace"
if not cwd.is_dir():
    cwd = repo / "workspace"

result = subprocess.run(build_cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
if result.returncode != 0:
    print(f"BUILD FAILED after writing {path}")
    print(f"Command: {build_cmd}")
    print(f"Error:\n{result.stderr[-1000:]}")
    print("Fix the build error before proceeding.")
    sys.exit(1)

print(f"Build passed after writing {path}")
sys.exit(0)
