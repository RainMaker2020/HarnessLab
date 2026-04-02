"""HarnessConfig — nested + legacy flat harness.yaml parsing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

# Roles whose *model id* can be overridden via HARNESS_MODEL_<ROLE> env vars.
_MODEL_ROLE_KEYS = frozenset({"planner", "generator", "evaluator", "contract_verifier"})
_ENV_MODEL_VARS: dict[str, str] = {
    "planner": "HARNESS_MODEL_PLANNER",
    "generator": "HARNESS_MODEL_GENERATOR",
    "evaluator": "HARNESS_MODEL_EVALUATOR",
    "contract_verifier": "HARNESS_MODEL_CONTRACT_VERIFIER",
}

from harness.eval.evaluator import DEFAULT_VISION_RUBRIC
from harness.exceptions import HarnessError


def _resolve(base: Path, value: str | Path | None) -> Optional[Path]:
    if value is None:
        return None
    p = Path(value)
    return p.resolve() if p.is_absolute() else (base / p).resolve()


@dataclass
class AblationConfig:
    """Flags to disable individual harness components for ablation studies."""
    disable_wisdom_rag: bool = False
    disable_contract_negotiation: bool = False
    single_model_mode: bool = False
    disable_playwright: bool = False


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
    global_interface_doc: Optional[Path]
    interfaces_file: Optional[Path]
    wisdom_store: Optional[Path]


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
    contract_test_command: Optional[str] = None
    planner_timeout_seconds: int = 900
    # Optional path (relative to harness.yaml or absolute): appended to vision_rubric for harness_eval.
    vision_rubric_supplement: Optional[Path] = None


@dataclass
class OrchestrationConfig:
    mode: str
    max_retries_per_task: int
    interactive_mode: bool
    auto_rollback: bool
    distillation_mode: bool
    test_first: bool
    contract_negotiation_max_retries: int
    epic_file: Optional[Path]
    sub_workspace_isolation: str
    worktrees_root: Optional[Path]
    wisdom_rag: bool


@dataclass
class HarnessConfig:
    """Loaded from harness.yaml. Nested sections are authoritative when present."""

    project: ProjectConfig
    paths: PathsConfig
    models: dict[str, str]
    runtime: RuntimeConfig
    evaluation: EvaluationConfig
    orchestration: OrchestrationConfig
    ablation: AblationConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.ablation is None:
            self.ablation = AblationConfig()

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
        if self.ablation.disable_playwright:
            strategy = self.evaluation.strategy or "exit_code"
            if _strategy_to_evaluator_type(strategy) not in ("exit_code",):
                return "exit_code"
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
    def vision_rubric_supplement(self) -> Optional[Path]:
        return self.evaluation.vision_rubric_supplement

    @property
    def contract_test_command(self) -> Optional[str]:
        return self.evaluation.contract_test_command

    @property
    def planner_timeout_seconds(self) -> int:
        return self.evaluation.planner_timeout_seconds

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

    @property
    def test_first(self) -> bool:
        return self.orchestration.test_first and not self.ablation.disable_contract_negotiation

    @property
    def effective_models(self) -> dict[str, str]:
        """YAML ``models`` plus ablation flatten and per-role env overrides.

        ``HARNESS_MODEL_PLANNER``, ``HARNESS_MODEL_GENERATOR``,
        ``HARNESS_MODEL_EVALUATOR``, ``HARNESS_MODEL_CONTRACT_VERIFIER`` override
        the corresponding model id when set (after ``single_model_mode`` flatten).
        Non-role keys (e.g. ``evaluator_provider``) are preserved from YAML.
        """
        base = dict(self.models)
        if self.ablation.single_model_mode:
            generator = base.get("generator", "claude-sonnet-4-6")
            for key in list(base.keys()):
                if key in _MODEL_ROLE_KEYS:
                    base[key] = generator
        for role, env_key in _ENV_MODEL_VARS.items():
            val = os.environ.get(env_key)
            if val is not None and str(val).strip():
                base[role] = str(val).strip()
        return base

    @property
    def contract_negotiation_max_retries(self) -> int:
        return self.orchestration.contract_negotiation_max_retries

    @property
    def orchestration_mode(self) -> str:
        return (self.orchestration.mode or "linear").strip().lower()

    @property
    def epic_path(self) -> Optional[Path]:
        return self.orchestration.epic_file

    @property
    def global_interface_doc(self) -> Optional[Path]:
        return self.paths.global_interface_doc

    @property
    def interfaces_path(self) -> Optional[Path]:
        return self.paths.interfaces_file

    @property
    def sub_workspace_isolation(self) -> str:
        return (self.orchestration.sub_workspace_isolation or "subrepo").strip().lower()

    @property
    def worktrees_root_path(self) -> Optional[Path]:
        return self.orchestration.worktrees_root

    @property
    def wisdom_rag_enabled(self) -> bool:
        return self.orchestration.wisdom_rag and not self.ablation.disable_wisdom_rag

    @property
    def resolved_wisdom_store(self) -> Path:
        """Directory for ChromaDB persistence; defaults next to ``history_file``."""
        if self.paths.wisdom_store is not None:
            return self.paths.wisdom_store
        return self.history_file.parent / "wisdom_chroma"

    @classmethod
    def sub_workspace_config(cls, parent: "HarnessConfig", module_dir: Path) -> "HarnessConfig":
        """Build a HarnessConfig for a module sub-workspace (isolated PLAN, history, spec)."""
        module_dir = module_dir.resolve()
        spec = module_dir / "MODULE_SPEC.md"
        gi = module_dir / "GLOBAL_INTERFACE.md"
        paths = PathsConfig(
            workspace_dir=module_dir,
            architecture_doc=parent.paths.architecture_doc,
            spec_doc=spec,
            plan_file=module_dir / "PLAN.md",
            history_file=module_dir / "history.json",
            distillation_export=None,
            prompt_buffer=module_dir / ".harness_prompt.md",
            screenshot_target=module_dir / ".harness_screenshot.png",
            global_interface_doc=gi,
            interfaces_file=parent.paths.interfaces_file,
            wisdom_store=None,
        )
        orch = OrchestrationConfig(
            mode="linear",
            max_retries_per_task=parent.orchestration.max_retries_per_task,
            interactive_mode=parent.orchestration.interactive_mode,
            auto_rollback=parent.orchestration.auto_rollback,
            distillation_mode=False,
            test_first=parent.orchestration.test_first,
            contract_negotiation_max_retries=parent.orchestration.contract_negotiation_max_retries,
            epic_file=None,
            sub_workspace_isolation="subrepo",
            worktrees_root=None,
            wisdom_rag=False,
        )
        return cls(
            project=parent.project,
            paths=paths,
            models=parent.models,
            runtime=parent.runtime,
            evaluation=parent.evaluation,
            orchestration=orch,
            ablation=parent.ablation,
        )

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
            global_interface_doc=_resolve(base, merged.get("global_interface_doc")),
            interfaces_file=_resolve(base, merged.get("interfaces_file")),
            wisdom_store=_resolve(base, merged.get("wisdom_store")),
        )

        runtime = RuntimeConfig(
            mode=str(merged.get("worker_mode") or "local"),
            image=str(merged.get("runtime_image") or "harnesslab-sandbox:latest"),
            memory_limit=str(merged.get("runtime_memory_limit") or "2g"),
            network_access=bool(merged.get("runtime_network_access", True)),
        )

        ct_cmd = merged.get("contract_test_command")
        if ct_cmd is not None and str(ct_cmd).strip() == "":
            ct_cmd = None
        elif ct_cmd is not None:
            ct_cmd = str(ct_cmd).strip()

        vrs_raw = merged.get("vision_rubric_supplement")
        vrs_path: Optional[Path] = None
        if vrs_raw is not None and str(vrs_raw).strip():
            vrs_path = _resolve(base, str(vrs_raw).strip())

        evaluation = EvaluationConfig(
            strategy=eval_strategy,
            build_command=str(merged["build_command"]),
            playwright_target=str(merged.get("playwright_target") or "index.html"),
            vision_rubric=vision_rubric,
            contract_test_command=ct_cmd,
            planner_timeout_seconds=int(merged.get("planner_timeout_seconds") or 900),
            vision_rubric_supplement=vrs_path,
        )

        orch_mode = str(merged.get("orchestration_mode") or "linear").strip().lower()
        epic_resolved = _resolve(base, merged.get("epic_file"))
        iso = str(merged.get("sub_workspace_isolation") or "subrepo").strip().lower()
        wtr = _resolve(base, merged.get("worktrees_root"))

        orchestration = OrchestrationConfig(
            mode=orch_mode,
            max_retries_per_task=int(merged.get("max_retries") or 3),
            interactive_mode=bool(merged.get("interactive_mode", False)),
            auto_rollback=bool(merged.get("auto_rollback", True)),
            distillation_mode=bool(merged.get("distillation_mode", False)),
            test_first=bool(merged.get("test_first", False)),
            contract_negotiation_max_retries=int(merged.get("contract_negotiation_max_retries") or 3),
            epic_file=epic_resolved,
            sub_workspace_isolation=iso,
            worktrees_root=wtr,
            wisdom_rag=bool(merged.get("wisdom_rag", False)),
        )

        ablation_raw = merged.get("ablation") or {}
        ablation = AblationConfig(
            disable_wisdom_rag=bool(ablation_raw.get("disable_wisdom_rag", False)),
            disable_contract_negotiation=bool(ablation_raw.get("disable_contract_negotiation", False)),
            single_model_mode=bool(ablation_raw.get("single_model_mode", False)),
            disable_playwright=bool(ablation_raw.get("disable_playwright", False)),
        )

        cfg = cls(
            project=project,
            paths=paths,
            models=models,
            runtime=runtime,
            evaluation=evaluation,
            orchestration=orchestration,
            ablation=ablation,
        )
        if cfg.orchestration_mode == "recursive" and cfg.orchestration.epic_file is None:
            raise HarnessError(
                "orchestration.mode is 'recursive' but 'epic_file' is missing. "
                "Set paths.epic_file or orchestration.epic_file in harness.yaml."
            )
        if cfg.orchestration_mode == "recursive":
            if cfg.paths.interfaces_file is None:
                raise HarnessError(
                    "orchestration.mode is 'recursive' but 'interfaces_file' is missing. "
                    "Set paths.interfaces_file (e.g. ./project/docs/interfaces.json)."
                )
        return cfg


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
    out["contract_test_command"] = raw.get("contract_test_command")
    out["planner_timeout_seconds"] = raw.get("planner_timeout_seconds")
    out["distillation_export"] = raw.get("distillation_export")
    out["wisdom_store"] = raw.get("wisdom_store")
    out["prompt_buffer"] = raw.get("prompt_buffer")
    out["screenshot_target"] = raw.get("screenshot_target")
    out["epic_file"] = raw.get("epic_file")
    out["orchestration_mode"] = raw.get("orchestration_mode")
    out["global_interface_doc"] = raw.get("global_interface_doc")
    out["interfaces_file"] = raw.get("interfaces_file")
    out["sub_workspace_isolation"] = raw.get("sub_workspace_isolation")
    out["worktrees_root"] = raw.get("worktrees_root")
    if raw.get("auto_rollback") is not None:
        out["auto_rollback"] = raw["auto_rollback"]
    if raw.get("distillation_mode") is not None:
        out["distillation_mode"] = raw["distillation_mode"]
    if raw.get("test_first") is not None:
        out["test_first"] = raw["test_first"]
    if raw.get("contract_negotiation_max_retries") is not None:
        out["contract_negotiation_max_retries"] = raw["contract_negotiation_max_retries"]
    if raw.get("wisdom_rag") is not None:
        out["wisdom_rag"] = raw["wisdom_rag"]

    proj = raw.get("project") or {}
    if isinstance(proj, dict):
        out["project_name"] = proj.get("name")
        out["project_version"] = proj.get("version")
        out["project_env"] = proj.get("env")

    paths = raw.get("paths") or {}
    if isinstance(paths, dict):
        if paths.get("epic_file") is not None:
            out["epic_file"] = paths["epic_file"]
        if paths.get("global_interface_doc") is not None:
            out["global_interface_doc"] = paths["global_interface_doc"]
        if paths.get("interfaces_file") is not None:
            out["interfaces_file"] = paths["interfaces_file"]
        for key, yaml_key in (
            ("workspace_dir", "workspace_dir"),
            ("architecture_doc", "architecture_doc"),
            ("plan_file", "plan_file"),
            ("distillation_export", "distillation_export"),
            ("prompt_buffer", "prompt_buffer"),
            ("screenshot_target", "screenshot_target"),
            ("wisdom_store", "wisdom_store"),
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
        if evaluation.get("vision_rubric_supplement") is not None:
            out["vision_rubric_supplement"] = evaluation["vision_rubric_supplement"]
        if evaluation.get("contract_test_command") is not None:
            out["contract_test_command"] = evaluation["contract_test_command"]
        if evaluation.get("planner_timeout_seconds") is not None:
            out["planner_timeout_seconds"] = evaluation["planner_timeout_seconds"]

    orch = raw.get("orchestration") or {}
    if isinstance(orch, dict):
        if orch.get("mode") is not None:
            out["orchestration_mode"] = orch["mode"]
        if orch.get("epic_file") is not None:
            out["epic_file"] = orch["epic_file"]
        if orch.get("max_retries_per_task") is not None:
            out["max_retries"] = orch["max_retries_per_task"]
        if orch.get("interactive_mode") is not None:
            out["interactive_mode"] = orch["interactive_mode"]
        if orch.get("auto_rollback") is not None:
            out["auto_rollback"] = orch["auto_rollback"]
        if orch.get("distillation_mode") is not None:
            out["distillation_mode"] = orch["distillation_mode"]
        if orch.get("test_first") is not None:
            out["test_first"] = orch["test_first"]
        if orch.get("contract_negotiation_max_retries") is not None:
            out["contract_negotiation_max_retries"] = orch["contract_negotiation_max_retries"]
        if orch.get("sub_workspace_isolation") is not None:
            out["sub_workspace_isolation"] = orch["sub_workspace_isolation"]
        if orch.get("worktrees_root") is not None:
            out["worktrees_root"] = orch["worktrees_root"]
        if orch.get("wisdom_rag") is not None:
            out["wisdom_rag"] = orch["wisdom_rag"]

    # evaluator strategy: nested evaluation.strategy > flat evaluator
    if out.get("eval_strategy") is not None:
        out["evaluator_flat"] = out["eval_strategy"]

    ablation = raw.get("ablation") or {}
    if isinstance(ablation, dict) and ablation:
        out["ablation"] = ablation

    return out


def _require_present(merged: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if merged.get(k) in (None, "")]
    if missing:
        raise HarnessError(
            f"harness.yaml missing required keys: {', '.join(missing)}. "
            "See docs or use nested `paths` / legacy flat keys."
        )
