"""Tests for ProjectMapper and dependency graph."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from project_mapper import (
    ProjectMapper,
    PROJECT_MAP_LINE_THRESHOLD,
    count_project_map_lines,
    dependency_pruning,
    direct_files_from_task,
    dumps_project_map_deterministic,
    impacted_files,
    line_count_from_text,
    task_description_for_task_id,
)


def test_project_mapper_writes_and_graph(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.ts").write_text(
        "export function foo() { return 1; }\nimport { bar } from './b';\n",
        encoding="utf-8",
    )
    (ws / "src" / "b.ts").write_text(
        "export function bar() { return 2; }\n",
        encoding="utf-8",
    )
    (ws / "src" / "c.ts").write_text(
        "import { foo } from './a';\nexport const x = foo();\n",
        encoding="utf-8",
    )

    pm = ProjectMapper(ws).scan_and_write()
    assert (ws / ".project_map.json").exists()
    data = json.loads((ws / ".project_map.json").read_text(encoding="utf-8"))
    assert "files" in data and "reverse_deps" in data
    assert "src/a.ts" in pm.files
    assert pm.reverse_deps.get("src/a.ts") == ["src/c.ts"]


def test_direct_files_from_task_and_impacted(tmp_path: Path) -> None:
    ws = tmp_path / "w"
    (ws / "lib" / "x.ts").parent.mkdir(parents=True)
    (ws / "lib" / "x.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (ws / "lib" / "y.ts").write_text("import { x } from './x';\nexport const y = x;\n", encoding="utf-8")

    pm = ProjectMapper(ws).scan()
    direct = direct_files_from_task("Update lib/x.ts for the API", ws)
    assert "lib/x.ts" in direct
    imp = impacted_files(direct, pm)
    assert "lib/y.ts" in imp


def test_prompt_situational_injection(tmp_path: Path) -> None:
    from prompt_generator import PromptGenerator
    from project_mapper import SituationalContext

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Update src/a.ts\n", encoding="utf-8")
    small_map = {
        "version": 1,
        "files": {"src/a.ts": {"exports": [], "imports": []}},
        "reverse_deps": {},
    }
    (ws / ".project_map.json").write_text(
        __import__("json").dumps(small_map, indent=2), encoding="utf-8"
    )

    class Cfg:
        architecture_doc = tmp_path / "A.md"
        spec_doc = tmp_path / "S.md"
        workspace_dir = ws
        plan_file = plan
        prompt_buffer_path = ws / ".harness_prompt.md"

    (tmp_path / "A.md").write_text("# A")
    (tmp_path / "S.md").write_text("# S")

    pg = PromptGenerator(Cfg())
    ctx = SituationalContext(direct_files=["src/a.ts"], impacted_files=["src/b.ts", "src/c.ts"])
    path = pg.generate(
        task_id="TASK_01",
        task_description="Update src/a.ts",
        attempt=1,
        last_failure=None,
        situational_context=ctx,
    )
    text = path.read_text(encoding="utf-8")
    assert "Situational Awareness" in text
    assert "src/a.ts" in text
    assert "src/b.ts" in text
    assert "same sprint" in text.lower() or "sprint" in text
    assert "Structured dependency data" in text
    assert "full map" in text.lower() or "≤" in text
    assert '"files"' in text


def test_prompt_injects_full_map_when_plan_file_missing(tmp_path: Path) -> None:
    """Small map: full JSON even if config has no ``plan_file`` (pruning not needed)."""
    from prompt_generator import PromptGenerator
    from project_mapper import SituationalContext

    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    small_map = {
        "version": 1,
        "files": {"src/a.ts": {"exports": [], "imports": []}},
        "reverse_deps": {},
    }
    (ws / ".project_map.json").write_text(
        __import__("json").dumps(small_map, indent=2), encoding="utf-8"
    )

    class Cfg:
        architecture_doc = tmp_path / "A2.md"
        spec_doc = tmp_path / "S2.md"
        workspace_dir = ws
        prompt_buffer_path = ws / ".harness_prompt.md"

    (tmp_path / "A2.md").write_text("# A")
    (tmp_path / "S2.md").write_text("# S")

    pg = PromptGenerator(Cfg())
    ctx = SituationalContext(direct_files=["src/a.ts"], impacted_files=[])
    text = pg.generate(
        task_id="TASK_01",
        task_description="Update src/a.ts",
        attempt=1,
        last_failure=None,
        situational_context=ctx,
    ).read_text(encoding="utf-8")
    assert "Structured dependency data" in text
    assert "full map" in text.lower() or "≤" in text
    assert '"files"' in text


def test_count_project_map_lines_matches_line_count_from_text(tmp_path: Path) -> None:
    p = tmp_path / ".project_map.json"
    body = '{\n  "a": 1\n}\n'
    p.write_text(body, encoding="utf-8")
    raw = p.read_text(encoding="utf-8")
    assert count_project_map_lines(p) == line_count_from_text(raw)


def test_task_description_for_task_id_reads_plan(tmp_path: Path) -> None:
    p = tmp_path / "PLAN.md"
    p.write_text("- [ ] TASK_02: hello world\n", encoding="utf-8")
    assert task_description_for_task_id(p, "TASK_02") == "hello world"
    assert task_description_for_task_id(p, "TASK_99") is None


def test_dependency_pruning_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("import { x } from './b';\n", encoding="utf-8")
    (tmp_path / "src" / "b.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "c.ts").write_text("import { x } from './a';\n", encoding="utf-8")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Fix src/a.ts\n", encoding="utf-8")
    pm = ProjectMapper(tmp_path).scan()
    data = pm.to_json_dict()
    o1 = dumps_project_map_deterministic(
        dependency_pruning("TASK_01", plan_file=plan, workspace=tmp_path, project_map=data)
    )
    o2 = dumps_project_map_deterministic(
        dependency_pruning("TASK_01", plan_file=plan, workspace=tmp_path, project_map=data)
    )
    assert o1 == o2


def test_dependency_pruning_malformed_reverse_deps_does_not_crash(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Fix src/a.ts\n", encoding="utf-8")
    bad = {
        "version": 1,
        "files": {"src/a.ts": {"exports": [], "imports": []}},
        "reverse_deps": {"src/a.ts": "not-a-list"},
    }
    pruned = dependency_pruning("TASK_01", plan_file=plan, workspace=tmp_path, project_map=bad)
    assert pruned["seed_files"] == ["src/a.ts"]


def test_seed_paths_not_in_graph_when_file_missing_from_map(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "only_on_disk.ts").write_text("export const x = 1;\n", encoding="utf-8")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Edit src/only_on_disk.ts\n", encoding="utf-8")
    stale = {"version": 1, "files": {}, "reverse_deps": {}}
    pruned = dependency_pruning("TASK_01", plan_file=plan, workspace=tmp_path, project_map=stale)
    assert pruned["seed_files"] == []
    assert pruned["seed_paths_not_in_graph"] == ["src/only_on_disk.ts"]
    assert "pruning_note" in pruned


def test_pruning_large_map_stays_under_token_budget(tmp_path: Path) -> None:
    """Simulate a 1000+ line project_map.json; pruned payload must stay small."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "seed.ts").write_text("export const S = 1;\n", encoding="utf-8")
    files: dict = {}
    reverse: dict = {"src/seed.ts": []}
    for i in range(1200):
        key = f"src/f{i:04d}.ts"
        files[key] = {"exports": [{"name": f"e{i}", "kind": "const"}], "imports": []}
    files["src/seed.ts"] = {"exports": [], "imports": []}
    big = {"version": 1, "workspace_root": str(tmp_path), "files": files, "reverse_deps": reverse}
    raw = __import__("json").dumps(big, indent=2)
    map_path = tmp_path / ".project_map.json"
    map_path.write_text(raw, encoding="utf-8")
    assert len(map_path.read_text(encoding="utf-8").splitlines()) > PROJECT_MAP_LINE_THRESHOLD

    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Refactor src/seed.ts\n", encoding="utf-8")
    pruned = dependency_pruning("TASK_01", plan_file=plan, workspace=tmp_path, project_map=big)
    out = dumps_project_map_deterministic(pruned)
    # Reasonable budget: far smaller than full map, bounded character count (~4 chars/token heuristic)
    assert len(out) < 50_000
    assert len(out) < len(raw) // 10
    assert "src/seed.ts" in pruned["neighborhood_files"]


def test_prompt_injects_pruned_header_when_map_exceeds_threshold(tmp_path: Path) -> None:
    from prompt_generator import PromptGenerator
    from project_mapper import SituationalContext

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "seed.ts").write_text("export const x = 1;\n", encoding="utf-8")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: Edit src/seed.ts\n", encoding="utf-8")
    big_files = {f"src/p{i}.ts": {"exports": [], "imports": []} for i in range(800)}
    big_files["src/seed.ts"] = {"exports": [], "imports": []}
    big = {"version": 1, "files": big_files, "reverse_deps": {}}
    (ws / ".project_map.json").write_text(__import__("json").dumps(big, indent=2), encoding="utf-8")
    assert len((ws / ".project_map.json").read_text().splitlines()) > PROJECT_MAP_LINE_THRESHOLD

    class Cfg:
        architecture_doc = tmp_path / "A.md"
        spec_doc = tmp_path / "S.md"
        workspace_dir = ws
        plan_file = plan
        prompt_buffer_path = ws / ".harness_prompt.md"

    (tmp_path / "A.md").write_text("# A")
    (tmp_path / "S.md").write_text("# S")

    pg = PromptGenerator(Cfg())
    ctx = SituationalContext(direct_files=["src/seed.ts"], impacted_files=[])
    text = pg.generate(
        task_id="TASK_01",
        task_description="Edit src/seed.ts",
        attempt=1,
        last_failure=None,
        situational_context=ctx,
    ).read_text(encoding="utf-8")
    assert "Pruned: Global map size exceeds threshold" in text
    assert '"pruned": true' in text
