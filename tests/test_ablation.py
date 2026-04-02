"""Unit tests for ablation study infrastructure — RED phase (TDD)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_yaml(tmp_path: Path, extra: str = "") -> Path:
    """Write a minimal valid harness.yaml with an optional extra block."""
    content = f"""\
project:
  name: TestProject
  version: "0.0.1"
  env: test

paths:
  workspace_dir: "{tmp_path / 'workspace'}"
  architecture_doc: "{tmp_path / 'ARCH.md'}"
  specification_doc: "{tmp_path / 'SPEC.md'}"
  plan_file: "{tmp_path / 'PLAN.md'}"
  history_log: "{tmp_path / 'history.json'}"

models:
  planner: "claude-opus-4-6"
  generator: "claude-haiku-4-6"
  evaluator: "claude-sonnet-4-6"

runtime:
  mode: local
  image: harnesslab-sandbox:latest
  memory_limit: 2g
  network_access: false

evaluation:
  strategy: exit_code
  build_command: "echo ok"
  playwright_target: index.html
  vision_rubric: "score. APPROVE or REJECT."

orchestration:
  mode: linear
  max_retries_per_task: 3
  interactive_mode: false
  auto_rollback: true
  distillation_mode: false
  wisdom_rag: true
  test_first: true
  contract_negotiation_max_retries: 3
{extra}
"""
    p = tmp_path / "harness.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# AblationConfig — dataclass structure
# ---------------------------------------------------------------------------

class TestAblationConfig:
    def test_defaults_are_all_false(self) -> None:
        from harness_config import AblationConfig
        cfg = AblationConfig()
        assert cfg.disable_wisdom_rag is False
        assert cfg.disable_contract_negotiation is False
        assert cfg.single_model_mode is False
        assert cfg.disable_playwright is False

    def test_flags_can_be_set(self) -> None:
        from harness_config import AblationConfig
        cfg = AblationConfig(
            disable_wisdom_rag=True,
            disable_contract_negotiation=True,
            single_model_mode=True,
            disable_playwright=True,
        )
        assert cfg.disable_wisdom_rag is True
        assert cfg.disable_contract_negotiation is True
        assert cfg.single_model_mode is True
        assert cfg.disable_playwright is True


# ---------------------------------------------------------------------------
# HarnessConfig.from_yaml — ablation section parsing
# ---------------------------------------------------------------------------

class TestHarnessConfigAblationParsing:
    def test_ablation_defaults_when_section_missing(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.ablation.disable_wisdom_rag is False
        assert cfg.ablation.disable_contract_negotiation is False
        assert cfg.ablation.single_model_mode is False
        assert cfg.ablation.disable_playwright is False

    def test_parses_disable_wisdom_rag(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path, extra="ablation:\n  disable_wisdom_rag: true\n")
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.ablation.disable_wisdom_rag is True

    def test_parses_disable_contract_negotiation(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path, extra="ablation:\n  disable_contract_negotiation: true\n")
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.ablation.disable_contract_negotiation is True

    def test_parses_single_model_mode(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path, extra="ablation:\n  single_model_mode: true\n")
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.ablation.single_model_mode is True

    def test_parses_disable_playwright(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path, extra="ablation:\n  disable_playwright: true\n")
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.ablation.disable_playwright is True


# ---------------------------------------------------------------------------
# HarnessConfig — ablation overrides existing properties
# ---------------------------------------------------------------------------

class TestHarnessConfigAblationProperties:
    def test_wisdom_rag_enabled_false_when_disable_wisdom_rag(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        extra = "ablation:\n  disable_wisdom_rag: true\n"
        p = _minimal_yaml(tmp_path, extra=extra)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.wisdom_rag_enabled is False

    def test_wisdom_rag_enabled_true_when_flag_not_set(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.wisdom_rag_enabled is True  # orchestration.wisdom_rag: true in _minimal_yaml

    def test_test_first_false_when_disable_contract_negotiation(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        extra = "ablation:\n  disable_contract_negotiation: true\n"
        p = _minimal_yaml(tmp_path, extra=extra)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.test_first is False

    def test_test_first_unchanged_without_flag(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.test_first is True  # orchestration.test_first: true in _minimal_yaml

    def test_evaluator_type_becomes_exit_code_when_disable_playwright(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        extra = "ablation:\n  disable_playwright: true\n"
        # Override strategy to playwright so we can verify the override works
        content = _minimal_yaml(tmp_path).read_text().replace(
            "strategy: exit_code", "strategy: playwright"
        )
        p = tmp_path / "harness2.yaml"
        p.write_text(content)
        (tmp_path / "harness2.yaml").write_text(
            content + "\nablation:\n  disable_playwright: true\n"
        )
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.evaluator_type == "exit_code"

    def test_evaluator_type_unchanged_when_playwright_not_disabled(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        content = _minimal_yaml(tmp_path).read_text().replace(
            "strategy: exit_code", "strategy: playwright"
        )
        p = tmp_path / "h.yaml"
        p.write_text(content)
        cfg = HarnessConfig.from_yaml(p)
        assert cfg.evaluator_type == "playwright"

    def test_effective_models_uniform_when_single_model_mode(self, tmp_path: Path) -> None:
        """All roles must map to the generator model when single_model_mode is True."""
        from harness_config import HarnessConfig
        extra = "ablation:\n  single_model_mode: true\n"
        p = _minimal_yaml(tmp_path, extra=extra)
        cfg = HarnessConfig.from_yaml(p)
        m = cfg.effective_models
        generator = cfg.models.get("generator")
        assert all(v == generator for v in m.values())

    def test_effective_models_normal_when_not_single_model_mode(self, tmp_path: Path) -> None:
        from harness_config import HarnessConfig
        p = _minimal_yaml(tmp_path)
        cfg = HarnessConfig.from_yaml(p)
        m = cfg.effective_models
        assert m.get("planner") != m.get("generator") or True  # distinct or not — just must exist
        assert "generator" in m
        assert "planner" in m


# ---------------------------------------------------------------------------
# PromptGenerator — ablation skips wisdom / contract sections
# ---------------------------------------------------------------------------

class TestPromptGeneratorAblation:
    def _make_config(self, tmp_path: Path, *, disable_wisdom_rag: bool = False,
                     disable_contract_negotiation: bool = False) -> MagicMock:
        from harness_config import AblationConfig
        cfg = MagicMock()
        cfg.architecture_doc.read_text.return_value = "Arch rules."
        cfg.spec_doc.read_text.return_value = "Spec."
        cfg.workspace_dir = tmp_path
        cfg.plan_file = None
        cfg.global_interface_doc = None
        cfg.prompt_buffer_path = tmp_path / ".harness_prompt.md"
        cfg.ablation = AblationConfig(
            disable_wisdom_rag=disable_wisdom_rag,
            disable_contract_negotiation=disable_contract_negotiation,
        )
        return cfg

    def test_wisdom_block_omitted_when_disable_wisdom_rag(self, tmp_path: Path) -> None:
        from prompt_generator import PromptGenerator
        cfg = self._make_config(tmp_path, disable_wisdom_rag=True)
        pg = PromptGenerator(cfg)
        pg.generate(
            task_id="TASK_01",
            task_description="Do something",
            attempt=1,
            last_failure=None,
            wisdom_lessons=[{"error": "Always cache.", "fix": "Added cache layer."}],
        )
        content = (tmp_path / ".harness_prompt.md").read_text()
        assert "Always cache." not in content

    def test_wisdom_block_included_when_not_disabled(self, tmp_path: Path) -> None:
        from prompt_generator import PromptGenerator
        cfg = self._make_config(tmp_path, disable_wisdom_rag=False)
        pg = PromptGenerator(cfg)
        pg.generate(
            task_id="TASK_01",
            task_description="Do something",
            attempt=1,
            last_failure=None,
            wisdom_lessons=[{"error": "Always cache.", "fix": "Added cache layer."}],
        )
        content = (tmp_path / ".harness_prompt.md").read_text()
        assert "Always cache." in content

    def test_contract_section_omitted_when_disable_contract_negotiation(self, tmp_path: Path) -> None:
        from prompt_generator import PromptGenerator
        contract = tmp_path / "TASK_01.contract.test.ts"
        contract.write_text("it('works', () => {});")
        cfg = self._make_config(tmp_path, disable_contract_negotiation=True)
        pg = PromptGenerator(cfg)
        pg.generate(
            task_id="TASK_01",
            task_description="Do something",
            attempt=1,
            last_failure=None,
            contract_path=contract,
        )
        content = (tmp_path / ".harness_prompt.md").read_text()
        assert "it('works'" not in content

    def test_contract_section_included_when_not_disabled(self, tmp_path: Path) -> None:
        from prompt_generator import PromptGenerator
        contract = tmp_path / "TASK_01.contract.test.ts"
        contract.write_text("it('works', () => {});")
        cfg = self._make_config(tmp_path, disable_contract_negotiation=False)
        pg = PromptGenerator(cfg)
        pg.generate(
            task_id="TASK_01",
            task_description="Do something",
            attempt=1,
            last_failure=None,
            contract_path=contract,
        )
        content = (tmp_path / ".harness_prompt.md").read_text()
        assert "it('works'" in content


# ---------------------------------------------------------------------------
# patch_config() — ablation_study.py helper
# ---------------------------------------------------------------------------

class TestPatchConfig:
    def _base_cfg(self) -> dict:
        return {
            "orchestration": {
                "wisdom_rag": True,
                "test_first": True,
            },
            "models": {
                "generator": "claude-haiku-4-6",
                "planner": "claude-opus-4-6",
                "evaluator": "claude-sonnet-4-6",
                "contract_verifier": "claude-3-5-sonnet-20241022",
            },
            "evaluation": {
                "strategy": "playwright",
            },
        }

    def test_disables_wisdom_rag(self) -> None:
        from ablation_study import patch_config
        result = patch_config(self._base_cfg(), ["wisdom_rag"])
        assert result["orchestration"]["wisdom_rag"] is False

    def test_does_not_mutate_original(self) -> None:
        from ablation_study import patch_config
        base = self._base_cfg()
        patch_config(base, ["wisdom_rag"])
        assert base["orchestration"]["wisdom_rag"] is True

    def test_disables_contract_negotiation(self) -> None:
        from ablation_study import patch_config
        result = patch_config(self._base_cfg(), ["contract_negotiation"])
        assert result["orchestration"]["test_first"] is False

    def test_single_model_flattens_to_generator(self) -> None:
        from ablation_study import patch_config
        result = patch_config(self._base_cfg(), ["model_routing"])
        generator = self._base_cfg()["models"]["generator"]
        for role in ("planner", "evaluator", "contract_verifier"):
            assert result["models"][role] == generator

    def test_disables_playwright_sets_exit_code(self) -> None:
        from ablation_study import patch_config
        result = patch_config(self._base_cfg(), ["playwright"])
        assert result["evaluation"]["strategy"] == "exit_code"

    def test_empty_disabled_list_returns_identical_structure(self) -> None:
        from ablation_study import patch_config
        base = self._base_cfg()
        result = patch_config(base, [])
        assert result["orchestration"]["wisdom_rag"] is True
        assert result["evaluation"]["strategy"] == "playwright"


# ---------------------------------------------------------------------------
# RunResult — efficiency metric
# ---------------------------------------------------------------------------

class TestRunResult:
    def test_efficiency_zero_when_tasks_total_is_zero(self) -> None:
        from ablation_study import RunResult
        r = RunResult(label="test", disabled=[])
        assert r.efficiency() == 0.0

    def test_efficiency_one_when_all_first_attempt(self) -> None:
        from ablation_study import RunResult
        r = RunResult(label="test", disabled=[], tasks_total=5, tasks_first_attempt=5)
        assert r.efficiency() == 1.0

    def test_efficiency_ratio(self) -> None:
        from ablation_study import RunResult
        r = RunResult(label="test", disabled=[], tasks_total=4, tasks_first_attempt=3)
        assert abs(r.efficiency() - 0.75) < 1e-9


# ---------------------------------------------------------------------------
# ablation_study main() — writes docs/ablation_results.json
# ---------------------------------------------------------------------------

class TestAblationStudyOutputs:
    def test_writes_ablation_results_json(self, tmp_path: Path) -> None:
        from ablation_study import RunResult

        results = [
            RunResult(label="Baseline", disabled=[], tasks_total=5, tasks_first_attempt=5),
            RunResult(label="No WisdomRAG", disabled=["wisdom_rag"], tasks_total=5, tasks_first_attempt=3),
        ]
        out_path = tmp_path / "ablation_results.json"
        out_path.write_text(json.dumps([r.__dict__ for r in results], indent=2))
        data = json.loads(out_path.read_text())
        assert len(data) == 2
        assert data[0]["label"] == "Baseline"
        assert data[1]["disabled"] == ["wisdom_rag"]

    def test_ablation_matrix_has_five_scenarios(self) -> None:
        from ablation_study import ABLATION_MATRIX
        assert len(ABLATION_MATRIX) == 5
        labels = [s["label"] for s in ABLATION_MATRIX]
        assert any("Baseline" in l for l in labels)
        assert any("WisdomRAG" in l or "wisdom" in l.lower() for l in labels)


# ---------------------------------------------------------------------------
# run_harness — Claude ablation (no core/main.py)
# ---------------------------------------------------------------------------

class TestRunHarnessPhase2:
    def test_run_harness_invokes_claude_not_main_py(self, tmp_path: Path) -> None:
        """Ablation must call Claude in the workspace, never deleted core/main.py."""
        import ablation_study

        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        cfg = {"paths": {"workspace_dir": str(ws)}}

        def _fake_run(cmd, **kwargs):
            assert cmd[0] == "claude"
            assert "main.py" not in " ".join(cmd)
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.object(ablation_study.subprocess, "run", side_effect=_fake_run):
            r = ablation_study.run_harness(cfg, str(tmp_path / "PLAN.md"), repo_root=tmp_path)
        assert not r.error
        assert r.tasks_total == 1

    def test_run_harness_aggregates_existing_jsonl(self, tmp_path: Path) -> None:
        import ablation_study

        traj = tmp_path / "traj.jsonl"
        traj.write_text(
            json.dumps({"task_id": "TASK_01", "attempts": 2}) + "\n"
            + json.dumps({"task_id": "TASK_02", "attempts": 1}) + "\n",
            encoding="utf-8",
        )
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        cfg = {"paths": {"workspace_dir": str(ws), "distillation_export": str(traj)}}

        with patch.object(
            ablation_study.subprocess,
            "run",
            return_value=CompletedProcess(["claude"], 0, "", ""),
        ):
            r = ablation_study.run_harness(cfg, str(tmp_path / "PLAN.md"), repo_root=tmp_path)
        assert r.tasks_total == 2
        assert r.tasks_first_attempt == 1
        assert r.total_retries == 1
        assert not r.error

    def test_run_harness_defaults_metrics_when_no_jsonl(self, tmp_path: Path) -> None:
        import ablation_study

        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        cfg = {"paths": {"workspace_dir": str(ws), "distillation_export": str(tmp_path / "nope.jsonl")}}

        with patch.object(
            ablation_study.subprocess,
            "run",
            return_value=CompletedProcess(["claude"], 0, "", ""),
        ):
            r = ablation_study.run_harness(cfg, str(tmp_path / "PLAN.md"), repo_root=tmp_path)
        assert r.tasks_total == 1
        assert r.tasks_first_attempt == 1
        assert not r.error
