#!/usr/bin/env python3
"""
Fires after every Write/Edit. Runs build command.
Exit 1 feeds the failure back to CC as context — it cannot ignore it.
"""
import subprocess, sys, json, os
from pathlib import Path

# Only trigger on workspace writes
tool_input = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
try:
    inp = json.loads(tool_input)
    path = inp.get("path", "")
except Exception:
    sys.exit(0)

if "workspace/" not in path and not path.startswith("workspace/"):
    sys.exit(0)

# Read build command from harness.yaml
try:
    import yaml
    cfg = yaml.safe_load(Path("harness.yaml").read_text())
    build_cmd = cfg["evaluation"]["build_command"]
except Exception:
    sys.exit(0)

# Skip placeholder
if "EVALUATOR_PLACEHOLDER" in build_cmd or "echo" in build_cmd:
    sys.exit(0)

result = subprocess.run(build_cmd, shell=True, cwd="workspace", capture_output=True, text=True)
if result.returncode != 0:
    # Print to stdout — CC receives this as tool feedback
    print(f"BUILD FAILED after writing {path}")
    print(f"Command: {build_cmd}")
    print(f"Error:\n{result.stderr[-1000:]}")
    print("Fix the build error before proceeding.")
    sys.exit(1)

print(f"Build passed after writing {path}")
sys.exit(0)