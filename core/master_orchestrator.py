#!/usr/bin/env python3
"""Master Orchestrator — EPIC.md, contract-first interfaces.json, isolated Sub-Orchestrators."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from exceptions import HarnessError
from evaluator import build_evaluator
from git_isolation import provision_subrepo_workspace, provision_worktree_workspace
from harness_config import HarnessConfig
from ui import ObservationDeck


def orchestrator_class_from_main() -> type:
    """Phase 2: the Python SubOrchestrator loop was removed; tests patch this to inject a stub."""
    raise HarnessError(
        "The Python SubOrchestrator loop was removed in Phase 2 (agentic-native). "
        "Use Claude Code with /harness-run in each module workspace. "
        "Tests may patch `master_orchestrator.orchestrator_class_from_main`."
    )


@dataclass
class EpicModule:
    """One unchecked module line from EPIC.md."""

    module_id: str
    title: str
    description: str
    line_index: int


class EpicParser:
    """Parses EPIC.md for MODULE_* checklist items (mirrors PlanParser for tasks)."""

    UNCHECKED_RE = re.compile(r"^- \[ \] (MODULE_\d+):\s*(.+)$")

    def __init__(self, epic_file: Path) -> None:
        self.epic_file = epic_file

    def next_module(self) -> Optional[EpicModule]:
        """Return the first unchecked module, or None if all are done."""
        lines = self.epic_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = self.UNCHECKED_RE.match(line.strip())
            if m:
                rest = m.group(2).strip()
                if " — " in rest:
                    title, desc = rest.split(" — ", 1)
                else:
                    title, desc = rest, ""
                return EpicModule(
                    module_id=m.group(1),
                    title=title.strip(),
                    description=desc.strip(),
                    line_index=i,
                )
        return None

    def mark_done(self, module: EpicModule) -> None:
        """Replace `- [ ]` with `- [x]` for the given module line."""
        lines = self.epic_file.read_text(encoding="utf-8").splitlines()
        lines[module.line_index] = lines[module.line_index].replace("- [ ]", "- [x]", 1)
        self.epic_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def slugify(title: str) -> str:
    """Directory name for a module under workspace/modules/ or worktrees/."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "module"


def parse_interface_blocks(epic_text: str) -> dict[str, str]:
    """Parse `###` headings under `## Global Interface Contracts` in EPIC.md (optional prose)."""
    if "## Global Interface Contracts" not in epic_text:
        return {}
    start = epic_text.index("## Global Interface Contracts")
    rest = epic_text[start:]
    blocks: dict[str, str] = {}
    parts = re.split(r"^###\s+", rest, flags=re.MULTILINE)
    for chunk in parts[1:]:
        if not chunk.strip():
            continue
        header_line, _sep, body = chunk.partition("\n")
        key = header_line.strip()
        blocks[key] = body.strip()
    return blocks


def interface_body_for_module(
    blocks: dict[str, str],
    module_id: str,
    title: str,
) -> str:
    """Resolve optional EPIC prose block by MODULE_XX or title."""
    slug = slugify(title)
    for key in (module_id, title, slug):
        if key in blocks:
            return blocks[key]
    return ""


def load_interfaces_json(path: Path) -> dict[str, Any]:
    """Load docs/interfaces.json (authoritative public contracts)."""
    if not path.exists():
        raise HarnessError(
            f"docs/interfaces.json is required for recursive mode but was not found: {path}"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"{path} must contain a JSON object at the root.")
    return data


def _nonempty_public_interface(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    pi = entry.get("public_interface")
    if isinstance(pi, dict) and len(pi) > 0:
        return True
    exports = entry.get("exports")
    if isinstance(exports, list) and len(exports) > 0:
        return True
    sig = entry.get("signatures")
    if isinstance(sig, list) and len(sig) > 0:
        return True
    return False


def resolve_module_interface_entry(data: dict[str, Any], module: EpicModule) -> dict[str, Any]:
    """Return the module's public contract from interfaces.json (must exist before any Sub run)."""
    modules = data.get("modules")
    if not isinstance(modules, dict):
        raise HarnessError("docs/interfaces.json must contain a top-level 'modules' object.")
    slug = slugify(module.title)
    for key in (module.module_id, slug):
        if key in modules and _nonempty_public_interface(modules[key]):
            return modules[key]
    raise HarnessError(
        f"docs/interfaces.json must define a non-empty public interface for '{module.module_id}' "
        f"or slug '{slug}' under `modules`. Add `public_interface`, `exports`, or `signatures`."
    )


def default_module_spec(module: EpicModule, parent_spec: Path) -> str:
    """MODULE_SPEC.md body for a new sub-workspace."""
    spec_hint = ""
    if parent_spec.exists():
        spec_hint = f"See also the project specification: `{parent_spec}`.\n\n"
    desc = (
        f"**Description:** {module.description}\n\n"
        if module.description
        else ""
    )
    return (
        f"# Module Specification: {module.title}\n\n"
        f"**Module ID:** `{module.module_id}`\n\n"
        f"{desc}"
        f"{spec_hint}"
        "## Scope\n\n"
        "Describe what this module owns and what it explicitly does not own.\n\n"
        "## Deliverables\n\n"
        "- Implement behavior aligned with GLOBAL_INTERFACE.md (rendered from docs/interfaces.json).\n"
        "- Keep all code changes under this module directory unless the Master contract says otherwise.\n"
    )


def default_plan_md(module: EpicModule) -> str:
    """Initial PLAN.md so the Sub-Orchestrator has at least one task."""
    return (
        f"# Plan — {module.title}\n\n"
        f"- [ ] TASK_01: Implement {module.title} per MODULE_SPEC.md and GLOBAL_INTERFACE.md\n"
    )


def write_sub_harness_yaml(module_dir: Path, parent: HarnessConfig) -> None:
    """Emit harness.yaml for audit; paths are relative to module_dir where possible."""
    arch = parent.architecture_doc.resolve()
    mod = module_dir.resolve()
    try:
        arch_rel = os.path.relpath(arch, mod)
    except ValueError:
        arch_rel = str(arch)

    data = {
        "project": {
            "name": parent.project.name,
            "version": parent.project.version,
            "env": parent.project.env,
        },
        "paths": {
            "workspace_dir": ".",
            "architecture_doc": arch_rel,
            "specification_doc": "./MODULE_SPEC.md",
            "plan_file": "./PLAN.md",
            "history_log": "./history.json",
            "prompt_buffer": "./.harness_prompt.md",
            "screenshot_target": "./.harness_screenshot.png",
        },
        "models": parent.models,
        "runtime": {
            "mode": parent.runtime.mode,
            "image": parent.runtime.image,
            "memory_limit": parent.runtime.memory_limit,
            "network_access": parent.runtime.network_access,
        },
        "evaluation": {
            "strategy": parent.evaluation.strategy,
            "build_command": parent.evaluation.build_command,
            "playwright_target": parent.evaluation.playwright_target,
            "vision_rubric": parent.evaluation.vision_rubric,
        },
        "orchestration": {
            "mode": "linear",
            "max_retries_per_task": parent.orchestration.max_retries_per_task,
            "interactive_mode": parent.orchestration.interactive_mode,
            "auto_rollback": parent.orchestration.auto_rollback,
            "distillation_mode": False,
            "test_first": parent.orchestration.test_first,
            "contract_negotiation_max_retries": parent.orchestration.contract_negotiation_max_retries,
        },
    }
    (module_dir / "harness.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class MasterOrchestrator:
    """Epic coordinator: EPIC.md → isolated dirs → Orchestrator from main.py (same class as linear)."""

    def __init__(self, config: HarnessConfig, ui: ObservationDeck) -> None:
        self.config = config
        self.ui = ui
        if config.epic_path is None:
            raise HarnessError("MasterOrchestrator requires orchestration.epic_file in harness.yaml.")
        self.epic_path = config.epic_path.resolve()
        if config.interfaces_path is None:
            raise HarnessError("MasterOrchestrator requires paths.interfaces_file (docs/interfaces.json).")
        self.interfaces_path = config.interfaces_path.resolve()
        self.modules_root = (config.workspace_dir / "modules").resolve()
        self._project_root = self.config.spec_doc.resolve().parent
        self._orchestrator_class = orchestrator_class_from_main

    def run(self) -> None:
        """Process every unchecked EPIC module until EPIC.md is complete."""
        if not self.epic_path.exists():
            raise HarnessError(f"EPIC file not found: {self.epic_path}")

        self.epic_path.parent.mkdir(parents=True, exist_ok=True)

        epic_text = self.epic_path.read_text(encoding="utf-8")
        interface_blocks = parse_interface_blocks(epic_text)

        self.ui.master_epic_started(self.epic_path)
        parser = EpicParser(self.epic_path)
        interfaces_data = load_interfaces_json(self.interfaces_path)

        while True:
            module = parser.next_module()
            if module is None:
                self.ui.epic_all_done()
                break

            self.ui.epic_module_start(module.module_id, module.title)

            contract_entry = resolve_module_interface_entry(interfaces_data, module)

            module_dir = self._provision_isolated_workspace(module)
            self._write_module_artifacts(module, module_dir, contract_entry, interface_blocks)

            write_sub_harness_yaml(module_dir, self.config)

            sub_cfg = HarnessConfig.sub_workspace_config(self.config, module_dir)
            evaluator = build_evaluator(sub_cfg)
            Orchestrator = self._orchestrator_class()
            orchestrator = Orchestrator(config=sub_cfg, evaluator=evaluator, ui=self.ui)
            orchestrator.run()

            parser.mark_done(module)
            self.ui.epic_module_complete(module.module_id, module.title)

    def _worktrees_root(self) -> Path:
        if self.config.worktrees_root_path is not None:
            return self.config.worktrees_root_path.resolve()
        return (self._project_root / ".harness" / "worktrees").resolve()

    def _provision_isolated_workspace(self, module: EpicModule) -> Path:
        """Separate subrepo or git worktree — never share a working tree between Sub-Orchestrators."""
        slug = slugify(module.title)
        iso = self.config.sub_workspace_isolation

        if iso == "worktree":
            main_repo = self.config.workspace_dir.resolve()
            worktree_path = self._worktrees_root() / slug
            branch = f"harness/module-{slug.replace('-', '/')}"
            return provision_worktree_workspace(main_repo, worktree_path, branch)

        if iso == "subrepo":
            module_dir = (self.modules_root / slug).resolve()
            if not str(module_dir).startswith(str(self.modules_root.resolve())):
                raise HarnessError(f"Invalid module path: {module_dir}")
            return provision_subrepo_workspace(module_dir)

        raise HarnessError(
            f"Unknown orchestration.sub_workspace_isolation: {iso!r}. Use 'subrepo' or 'worktree'."
        )

    def _write_module_artifacts(
        self,
        module: EpicModule,
        module_dir: Path,
        contract_entry: dict[str, Any],
        epic_blocks: dict[str, str],
    ) -> None:
        """Write MODULE_SPEC, GLOBAL_INTERFACE (from JSON + optional EPIC prose), PLAN, history."""
        module_dir.mkdir(parents=True, exist_ok=True)

        snapshot = module_dir / "PUBLIC_INTERFACE.json"
        snapshot.write_text(json.dumps(contract_entry, indent=2), encoding="utf-8")

        prose = interface_body_for_module(epic_blocks, module.module_id, module.title)
        gi_body = (
            f"# Global Interface Contract — {module.title} ({module.module_id})\n\n"
            "## Authoritative contract (from docs/interfaces.json)\n\n"
            f"```json\n{json.dumps(contract_entry, indent=2)}\n```\n"
        )
        if prose.strip():
            gi_body += "\n## Notes from EPIC.md (optional)\n\n" + prose.strip() + "\n"

        (module_dir / "GLOBAL_INTERFACE.md").write_text(gi_body, encoding="utf-8")

        spec_path = module_dir / "MODULE_SPEC.md"
        if not spec_path.exists():
            spec_path.write_text(
                default_module_spec(module, self.config.spec_doc),
                encoding="utf-8",
            )

        plan_path = module_dir / "PLAN.md"
        if not plan_path.exists():
            plan_path.write_text(default_plan_md(module), encoding="utf-8")

        hist = module_dir / "history.json"
        if not hist.exists():
            hist.write_text("[]", encoding="utf-8")
