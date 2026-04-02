"""Tests for nested + flat harness.yaml parsing."""

import textwrap
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.exceptions import HarnessError
from harness.config.harness_config import HarnessConfig


def _write_docs(root: Path) -> None:
    (root / "ARCHITECTURE.md").write_text("arch")
    (root / "SPEC.md").write_text("spec")
    (root / "workspace").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "history.json").write_text("[]")


def test_flat_legacy_yaml(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
        build_command: "echo ok"
        max_retries: 2
        evaluator: exit_code
        playwright_target: index.html
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.max_retries == 2
    assert c.evaluation.strategy == "exit_code"
    assert c.paths.workspace_dir == (tmp_path / "workspace").resolve()


def test_nested_overrides_flat(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
        build_command: "echo flat"
        max_retries: 9
        evaluation:
          strategy: multimodal
          build_command: "npm run build"
          vision_rubric: |
            Custom rubric line one
        orchestration:
          max_retries_per_task: 2
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.evaluation.strategy == "multimodal"
    assert c.evaluation.build_command == "npm run build"
    assert "Custom rubric" in c.evaluation.vision_rubric
    assert c.orchestration.max_retries_per_task == 2


def test_multimodal_maps_to_playwright_evaluator_type(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
        build_command: "echo ok"
        evaluation:
          strategy: multimodal
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.evaluator_type == "playwright"


def test_models_section_includes_brain_provider_keys(tmp_path: Path) -> None:
    """Optional evaluator_provider / base_url are stored on config.models (strings)."""
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        build_command: "echo ok"
        models:
          evaluator: "gpt-4o"
          evaluator_provider: "openai"
          contract_verifier: "deepseek-reasoner"
          contract_verifier_provider: "openai-compatible"
          contract_verifier_base_url: "https://api.deepseek.com"
        paths:
          workspace_dir: ./workspace
          architecture_doc: ./ARCHITECTURE.md
          specification_doc: ./SPEC.md
          plan_file: ./workspace/PLAN.md
          history_log: ./docs/history.json
        evaluation:
          strategy: exit_code
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.models["evaluator"] == "gpt-4o"
    assert c.models["evaluator_provider"] == "openai"
    assert c.models["contract_verifier_base_url"] == "https://api.deepseek.com"


def test_effective_models_env_overrides_yaml(tmp_path: Path, monkeypatch) -> None:
    """HARNESS_MODEL_EVALUATOR overrides harness.yaml model id."""
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        build_command: "echo ok"
        models:
          planner: p
          generator: g
          evaluator: claude-from-yaml
        paths:
          workspace_dir: ./workspace
          architecture_doc: ./ARCHITECTURE.md
          specification_doc: ./SPEC.md
          plan_file: ./workspace/PLAN.md
          history_log: ./docs/history.json
        evaluation:
          strategy: exit_code
    """
        ).strip()
    )
    monkeypatch.setenv("HARNESS_MODEL_EVALUATOR", "gpt-4.1")
    c = HarnessConfig.from_yaml(y)
    assert c.models["evaluator"] == "claude-from-yaml"
    assert c.effective_models["evaluator"] == "gpt-4.1"


def test_effective_models_single_model_preserves_provider_and_base_url_keys(
    tmp_path: Path,
) -> None:
    """single_model_mode flattens only role model ids; *_provider / *_base_url stay intact."""
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        build_command: "echo ok"
        models:
          planner: "planner-model"
          generator: "generator-model"
          evaluator: "evaluator-model"
          contract_verifier: "cv-model"
          evaluator_provider: "openai"
          contract_verifier_provider: "openai-compatible"
          contract_verifier_base_url: "https://api.deepseek.com"
        paths:
          workspace_dir: ./workspace
          architecture_doc: ./ARCHITECTURE.md
          specification_doc: ./SPEC.md
          plan_file: ./workspace/PLAN.md
          history_log: ./docs/history.json
        evaluation:
          strategy: exit_code
        ablation:
          single_model_mode: true
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    gen = c.models["generator"]
    em = c.effective_models
    assert em["planner"] == gen
    assert em["generator"] == gen
    assert em["evaluator"] == gen
    assert em["contract_verifier"] == gen
    assert em["evaluator_provider"] == "openai"
    assert em["contract_verifier_provider"] == "openai-compatible"
    assert em["contract_verifier_base_url"] == "https://api.deepseek.com"


def test_paths_section_aliases(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        build_command: "echo ok"
        models:
          planner: p
          generator: g
          evaluator: e
        paths:
          workspace_dir: ./workspace
          architecture_doc: ./ARCHITECTURE.md
          specification_doc: ./SPEC.md
          plan_file: ./workspace/PLAN.md
          history_log: ./docs/history.json
        evaluation:
          strategy: exit_code
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.paths.spec_doc == (tmp_path / "SPEC.md").resolve()
    assert c.paths.history_file == (tmp_path / "docs" / "history.json").resolve()


def test_missing_required_key_raises(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
    """
        ).strip()
    )
    with pytest.raises(HarnessError, match="build_command"):
        HarnessConfig.from_yaml(y)


def test_vision_rubric_supplement_resolves(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    (tmp_path / "design_extra.md").write_text("SUPPLEMENT_TEXT", encoding="utf-8")
    y = tmp_path / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
        build_command: "echo ok"
        evaluation:
          strategy: exit_code
          vision_rubric: "Rubric body."
          vision_rubric_supplement: ./design_extra.md
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.evaluation.vision_rubric_supplement == (tmp_path / "design_extra.md").resolve()
