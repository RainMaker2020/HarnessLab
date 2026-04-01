"""HarnessConfig — nested + legacy flat harness.yaml parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from evaluator import DEFAULT_VISION_RUBRIC
from exceptions import HarnessError


def _resolve(base: Path, value: str | Path | None) -> Optional[Path]:
    if value is None:
        return None
    p = Path(value)
    return p.resolve() if p.is_absolute() else (base / p).resolve()


@dataclass
class ProjectConfig:
    name: str
    version: str
    env: str


@dataclass
class PathsConfig:
    workspace_dir: Path
    architecture_doc: Path
    spec_doc: Path
    plan_file: Path
    history_file: Path
    distillation_export: Optional[Path]
    prompt_buffer: Optional[Path]
    screenshot_target: Optional[Path]


@dataclass
class RuntimeConfig:
    mode: str
    image: str
    memory_limit: str
    network_access: bool


@dataclass
class EvaluationConfig:
    strategy: str
    build_command: str
    playwright_target: str
    vision_rubric: str


@dataclass
class OrchestrationConfig:
    max_retries_per_task: int
    interactive_mode: bool
    auto_rollback: bool
    distillation_mode: bool


@dataclass
class HarnessConfig:
    """Loaded from harness.yaml. Nested sections are authoritative when present."""

    project: ProjectConfig
    paths: PathsConfig
    models: dict[str, str]
    runtime: RuntimeConfig
    evaluation: EvaluationConfig
    orchestration: OrchestrationConfig

    # --- Backward-compatible properties (flat API) ---

    @property
    def workspace_dir(self) -> Path:
        return self.paths.workspace_dir

    @property
    def architecture_doc(self) -> Path:
        return self.paths.architecture_doc

    @property
    def spec_doc(self) -> Path:
        return self.paths.spec_doc

    @property
    def plan_file(self) -> Path:
        return self.paths.plan_file

    @property
    def history_file(self) -> Path:
        return self.paths.history_file

    @property
    def build_command(self) -> str:
        return self.evaluation.build_command

    @property
    def max_retries(self) -> int:
        return self.orchestration.max_retries_per_task

    @property
    def worker_mode(self) -> str:
        return self.runtime.mode

    @property
    def evaluator_type(self) -> str:
        return _strategy_to_evaluator_type(self.evaluation.strategy)

    @property
    def interactive_mode(self) -> bool:
        return self.orchestration.interactive_mode

    @property
    def playwright_target(self) -> str:
        return self.evaluation.playwright_target

    @property
    def vision_rubric(self) -> str:
        return self.evaluation.vision_rubric

    @property
    def distillation_export(self) -> Optional[Path]:
        return self.paths.distillation_export

    @property
    def distillation_mode(self) -> bool:
        return self.orchestration.distillation_mode

    @property
    def auto_rollback(self) -> bool:
        return self.orchestration.auto_rollback

    @property
    def prompt_buffer_path(self) -> Path:
        if self.paths.prompt_buffer is not None:
            return self.paths.prompt_buffer
        return self.paths.workspace_dir / ".harness_prompt.md"

    @property
    def screenshot_path(self) -> Path:
        if self.paths.screenshot_target is not None:
            return self.paths.screenshot_target
        return self.paths.workspace_dir / ".harness_screenshot.png"

    @property
    def docker_image(self) -> str:
        return self.runtime.image

    @property
    def docker_memory_limit(self) -> str:
        return self.runtime.memory_limit

    @property
    def docker_network_access(self) -> bool:
        return self.runtime.network_access

    @classmethod
    def from_yaml(cls, path: Path) -> "HarnessConfig":
        """Parse harness.yaml. Nested keys override flat legacy keys."""
        try:
            text = path.read_text()
        except OSError as exc:
            raise HarnessError(f"Cannot read harness.yaml: {exc}") from exc

        raw = yaml.safe_load(text)
        if raw is None:
            raise HarnessError("harness.yaml is empty or invalid YAML")

        base = path.parent.resolve()
        merged = _merge_raw(raw, base)
        return cls._from_merged(merged, base)

    @classmethod
    def _from_merged(cls, merged: dict[str, Any], base: Path) -> "HarnessConfig":
        _require_present(
            merged,
            "workspace_dir",
            "architecture_doc",
            "spec_doc",
            "plan_file",
            "history_file",
            "build_command",
        )

        workspace_dir = _resolve(base, merged["workspace_dir"])
        assert workspace_dir is not None

        models: dict[str, str] = merged.get("models") or {}
        if not models:
            models = {
                "planner": merged.get("claude_model", "claude-sonnet-4-6"),
                "generator": merged.get("claude_model", "claude-sonnet-4-6"),
                "evaluator": merged.get("vision_model", "claude-3-5-sonnet-20241022"),
            }

        eval_strategy = str(merged.get("evaluator_flat") or "exit_code")

        vision_rubric = merged.get("vision_rubric")
        if not vision_rubric or not str(vision_rubric).strip():
            vision_rubric = DEFAULT_VISION_RUBRIC
        else:
            vision_rubric = str(vision_rubric).strip()

        project = ProjectConfig(
            name=str(merged.get("project_name") or "HarnessLab"),
            version=str(merged.get("project_version") or "0.0.0"),
            env=str(merged.get("project_env") or "development"),
        )

        paths = PathsConfig(
            workspace_dir=workspace_dir,
            architecture_doc=_resolve(base, merged["architecture_doc"]) or workspace_dir,
            spec_doc=_resolve(base, merged["spec_doc"]) or workspace_dir,
            plan_file=_resolve(base, merged["plan_file"]) or workspace_dir,
            history_file=_resolve(base, merged["history_file"]) or workspace_dir,
            distillation_export=_resolve(base, merged.get("distillation_export")),
            prompt_buffer=_resolve(base, merged.get("prompt_buffer")),
            screenshot_target=_resolve(base, merged.get("screenshot_target")),
        )

        runtime = RuntimeConfig(
            mode=str(merged.get("worker_mode") or "local"),
            image=str(merged.get("runtime_image") or "harnesslab-sandbox:latest"),
            memory_limit=str(merged.get("runtime_memory_limit") or "2g"),
            network_access=bool(merged.get("runtime_network_access", True)),
        )

        evaluation = EvaluationConfig(
            strategy=eval_strategy,
            build_command=str(merged["build_command"]),
            playwright_target=str(merged.get("playwright_target") or "index.html"),
            vision_rubric=vision_rubric,
        )

        orchestration = OrchestrationConfig(
            max_retries_per_task=int(merged.get("max_retries") or 3),
            interactive_mode=bool(merged.get("interactive_mode", False)),
            auto_rollback=bool(merged.get("auto_rollback", True)),
            distillation_mode=bool(merged.get("distillation_mode", False)),
        )

        return cls(
            project=project,
            paths=paths,
            models=models,
            runtime=runtime,
            evaluation=evaluation,
            orchestration=orchestration,
        )


def _strategy_to_evaluator_type(strategy: str) -> str:
    s = (strategy or "exit_code").strip().lower()
    if s in ("playwright", "multimodal"):
        return "playwright"
    if s in ("exit_code", "unit_test"):
        return "exit_code"
    return s


def _merge_raw(raw: dict[str, Any], base: Path) -> dict[str, Any]:
    """Merge flat legacy keys with nested sections (nested wins)."""
    out: dict[str, Any] = {}

    # Legacy flat keys (defaults); nested sections override below
    out["workspace_dir"] = raw.get("workspace_dir")
    out["architecture_doc"] = raw.get("architecture_doc")
    out["spec_doc"] = raw.get("spec_doc")
    out["plan_file"] = raw.get("plan_file")
    out["history_file"] = raw.get("history_file")
    out["build_command"] = raw.get("build_command")
    out["models"] = raw.get("models") or {}
    out["evaluator_flat"] = raw.get("evaluator")
    out["playwright_target"] = raw.get("playwright_target")
    out["max_retries"] = raw.get("max_retries")
    out["worker_mode"] = raw.get("worker_mode")
    out["interactive_mode"] = raw.get("interactive_mode")
    out["vision_rubric"] = raw.get("vision_rubric")
    out["distillation_export"] = raw.get("distillation_export")
    out["prompt_buffer"] = raw.get("prompt_buffer")
    out["screenshot_target"] = raw.get("screenshot_target")
    if raw.get("auto_rollback") is not None:
        out["auto_rollback"] = raw["auto_rollback"]
    if raw.get("distillation_mode") is not None:
        out["distillation_mode"] = raw["distillation_mode"]

    proj = raw.get("project") or {}
    if isinstance(proj, dict):
        out["project_name"] = proj.get("name")
        out["project_version"] = proj.get("version")
        out["project_env"] = proj.get("env")

    paths = raw.get("paths") or {}
    if isinstance(paths, dict):
        for key, yaml_key in (
            ("workspace_dir", "workspace_dir"),
            ("architecture_doc", "architecture_doc"),
            ("plan_file", "plan_file"),
            ("distillation_export", "distillation_export"),
            ("prompt_buffer", "prompt_buffer"),
            ("screenshot_target", "screenshot_target"),
        ):
            if paths.get(yaml_key) is not None:
                out[key] = paths[yaml_key]
        if paths.get("specification_doc") is not None:
            out["spec_doc"] = paths["specification_doc"]
        elif paths.get("spec_doc") is not None:
            out["spec_doc"] = paths["spec_doc"]
        if paths.get("history_log") is not None:
            out["history_file"] = paths["history_log"]
        elif paths.get("history_file") is not None:
            out["history_file"] = paths["history_file"]

    models = raw.get("models")
    if isinstance(models, dict) and models:
        out["models"] = models

    runtime = raw.get("runtime") or {}
    if isinstance(runtime, dict):
        if runtime.get("mode") is not None:
            out["worker_mode"] = runtime["mode"]
        out["runtime_image"] = runtime.get("image")
        out["runtime_memory_limit"] = runtime.get("memory_limit")
        if runtime.get("network_access") is not None:
            out["runtime_network_access"] = runtime["network_access"]

    evaluation = raw.get("evaluation") or {}
    if isinstance(evaluation, dict):
        if evaluation.get("strategy") is not None:
            out["eval_strategy"] = evaluation["strategy"]
        if evaluation.get("build_command") is not None:
            out["build_command"] = evaluation["build_command"]
        if evaluation.get("playwright_target") is not None:
            out["playwright_target"] = evaluation["playwright_target"]
        if evaluation.get("vision_rubric") is not None:
            out["vision_rubric"] = evaluation["vision_rubric"]

    orch = raw.get("orchestration") or {}
    if isinstance(orch, dict):
        if orch.get("max_retries_per_task") is not None:
            out["max_retries"] = orch["max_retries_per_task"]
        if orch.get("interactive_mode") is not None:
            out["interactive_mode"] = orch["interactive_mode"]
        if orch.get("auto_rollback") is not None:
            out["auto_rollback"] = orch["auto_rollback"]
        if orch.get("distillation_mode") is not None:
            out["distillation_mode"] = orch["distillation_mode"]

    # evaluator strategy: nested evaluation.strategy > flat evaluator
    if out.get("eval_strategy") is not None:
        out["evaluator_flat"] = out["eval_strategy"]

    return out


def _require_present(merged: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if merged.get(k) in (None, "")]
    if missing:
        raise HarnessError(
            f"harness.yaml missing required keys: {', '.join(missing)}. "
            "See docs or use nested `paths` / legacy flat keys."
        )
