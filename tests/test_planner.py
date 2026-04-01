"""Tests for ContractPlanner."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from exceptions import HarnessError
from model_router import ModelRouter
from planner import ContractPlanner


class _Cfg:
    workspace_dir = Path("/tmp/ws")
    spec_doc = Path("/tmp/spec.md")


@pytest.fixture
def tmp_ws(tmp_path):
    spec = tmp_path / "SPEC.md"
    spec.write_text("# Spec\n\nMust do X.")
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg = _Cfg()
    cfg.workspace_dir = ws
    cfg.spec_doc = spec
    return cfg


def test_strip_code_fence():
    raw = "```typescript\nconst x = 1;\n```"
    assert "const x" in ContractPlanner._strip_code_fence(raw)


def test_generate_contract_writes_file(tmp_ws):
    cfg = tmp_ws
    router = ModelRouter(type("M", (), {"models": {"planner": "p"}})())

    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = "import { expect, test } from 'vitest';\ntest('a', () => expect(1).toBe(1));"
    proc.stderr = ""

    with patch("planner.subprocess.run", return_value=proc):
        planner = ContractPlanner(cfg, router)
        path = planner.generate_contract("TASK_01", "Do the thing")

    assert path.name == "TASK_01.contract.test.ts"
    assert "vitest" in path.read_text()


def test_generate_contract_claude_failure_raises(tmp_ws):
    cfg = tmp_ws
    router = ModelRouter(type("M", (), {"models": {}})())

    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "boom"

    with patch("planner.subprocess.run", return_value=proc), pytest.raises(HarnessError, match="Contract planner"):
        ContractPlanner(cfg, router).generate_contract("TASK_01", "x")
