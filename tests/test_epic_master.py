"""Tests for EPIC parsing, interface blocks, and recursive harness validation."""

import json
import textwrap
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from exceptions import HarnessError
from harness_config import HarnessConfig
from master_orchestrator import (
    EpicModule,
    EpicParser,
    interface_body_for_module,
    parse_interface_blocks,
    slugify,
)


def test_slugify_normalizes_title() -> None:
    assert slugify("Auth & API") == "auth-api"
    assert slugify("!!!") == "module"


def test_epic_parser_next_and_mark_done(tmp_path: Path) -> None:
    epic = tmp_path / "EPIC.md"
    epic.write_text(
        "# E\n"
        "- [ ] MODULE_01: Alpha — first\n"
        "- [ ] MODULE_02: Beta\n",
        encoding="utf-8",
    )
    p = EpicParser(epic)
    m = p.next_module()
    assert m is not None
    assert m.module_id == "MODULE_01"
    assert m.title == "Alpha"
    assert m.description == "first"
    p.mark_done(m)
    assert "- [x] MODULE_01" in epic.read_text()
    m2 = p.next_module()
    assert m2 is not None
    assert m2.module_id == "MODULE_02"


def test_epic_parser_all_done(tmp_path: Path) -> None:
    epic = tmp_path / "EPIC.md"
    epic.write_text("- [x] MODULE_01: Done\n", encoding="utf-8")
    assert EpicParser(epic).next_module() is None


def test_parse_interface_blocks() -> None:
    text = """# X
## Global Interface Contracts

### MODULE_01
```ts
export function a(): void;
```

### MODULE_02
plain text
"""
    blocks = parse_interface_blocks(text)
    assert "MODULE_01" in blocks
    assert "export function a()" in blocks["MODULE_01"]
    assert "plain text" in blocks["MODULE_02"]


def test_interface_body_for_module_prefers_module_id() -> None:
    blocks = {"MODULE_01": "one", "Auth": "two"}
    m = EpicModule("MODULE_01", "Auth", "", 0)
    assert interface_body_for_module(blocks, m.module_id, m.title) == "one"


def test_recursive_mode_requires_epic_file(tmp_path: Path) -> None:
    (tmp_path / "ARCHITECTURE.md").write_text("a")
    (tmp_path / "SPEC.md").write_text("s")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "history.json").write_text("[]")
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
        orchestration:
          mode: recursive
    """
        ).strip()
    )
    with pytest.raises(HarnessError, match="epic_file"):
        HarnessConfig.from_yaml(y)


def test_orchestration_mode_and_epic_file_parse(tmp_path: Path) -> None:
    (tmp_path / "ARCHITECTURE.md").write_text("a")
    (tmp_path / "SPEC.md").write_text("s")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "history.json").write_text("[]")
    (tmp_path / "docs" / "EPIC.md").write_text("- [ ] MODULE_01: X\n")
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
        paths:
          interfaces_file: ./docs/interfaces.json
        orchestration:
          mode: recursive
          epic_file: ./docs/EPIC.md
    """
        ).strip()
    )
    c = HarnessConfig.from_yaml(y)
    assert c.orchestration_mode == "recursive"
    assert c.epic_path == (tmp_path / "docs" / "EPIC.md").resolve()
    assert c.interfaces_path == (tmp_path / "docs" / "interfaces.json").resolve()


def test_recursive_requires_interfaces_file_in_yaml(tmp_path: Path) -> None:
    (tmp_path / "ARCHITECTURE.md").write_text("a")
    (tmp_path / "SPEC.md").write_text("s")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "history.json").write_text("[]")
    (tmp_path / "docs" / "EPIC.md").write_text("- [ ] MODULE_01: X\n")
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
        orchestration:
          mode: recursive
          epic_file: ./docs/EPIC.md
    """
        ).strip()
    )
    with pytest.raises(HarnessError, match="interfaces_file"):
        HarnessConfig.from_yaml(y)


def test_sub_workspace_config_points_to_module_paths(tmp_path: Path) -> None:
    (tmp_path / "ARCHITECTURE.md").write_text("a")
    (tmp_path / "SPEC.md").write_text("s")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "history.json").write_text("[]")
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
    """
        ).strip()
    )
    parent = HarnessConfig.from_yaml(y)
    mod = tmp_path / "workspace" / "modules" / "auth"
    mod.mkdir(parents=True)
    sub = HarnessConfig.sub_workspace_config(parent, mod)
    assert sub.workspace_dir == mod.resolve()
    assert sub.plan_file == mod / "PLAN.md"
    assert sub.history_file == mod / "history.json"
    assert sub.spec_doc == mod / "MODULE_SPEC.md"
    assert sub.global_interface_doc == mod / "GLOBAL_INTERFACE.md"


def test_master_provisions_module_and_skips_sub_run(tmp_path: Path) -> None:
    """Master creates module tree and writes contract files; Orchestrator from main is mocked."""
    root = tmp_path
    (root / "ARCHITECTURE.md").write_text("# A")
    (root / "SPEC.md").write_text("# S")
    ws = root / "workspace"
    ws.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "history.json").write_text("[]")
    epic = root / "docs" / "EPIC.md"
    epic.write_text("- [ ] MODULE_01: Auth — test module\n", encoding="utf-8")

    iface = root / "docs" / "interfaces.json"
    iface.write_text(
        json.dumps(
            {
                "modules": {
                    "MODULE_01": {
                        "public_interface": {"login": "() => void"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    y = root / "harness.yaml"
    y.write_text(
        textwrap.dedent(
            """
        workspace_dir: ./workspace
        architecture_doc: ./ARCHITECTURE.md
        spec_doc: ./SPEC.md
        plan_file: ./workspace/PLAN.md
        history_file: ./docs/history.json
        build_command: "echo ok"
        paths:
          interfaces_file: ./docs/interfaces.json
        orchestration:
          mode: recursive
          epic_file: ./docs/EPIC.md
          test_first: false
    """
        ).strip()
    )

    cfg = HarnessConfig.from_yaml(y)
    from master_orchestrator import MasterOrchestrator

    class _StubOrchestrator:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            return None

    with patch(
        "master_orchestrator.orchestrator_class_from_main",
        return_value=_StubOrchestrator,
    ):
        master = MasterOrchestrator(cfg, ui=ObservationDeckShim())
        master.run()

    mod_dir = ws / "modules" / "auth"
    assert mod_dir.is_dir()
    assert (mod_dir / "MODULE_SPEC.md").exists()
    assert (mod_dir / "GLOBAL_INTERFACE.md").exists()
    assert (mod_dir / "PUBLIC_INTERFACE.json").exists()
    assert (mod_dir / "PLAN.md").exists()
    assert (mod_dir / "history.json").exists()
    assert (mod_dir / "harness.yaml").exists()
    assert "- [x] MODULE_01" in epic.read_text()


class ObservationDeckShim:
    """Minimal UI stub for MasterOrchestrator."""

    def master_epic_started(self, *_a, **_k) -> None:
        pass

    def epic_module_start(self, *_a, **_k) -> None:
        pass

    def epic_module_complete(self, *_a, **_k) -> None:
        pass

    def epic_all_done(self) -> None:
        pass
