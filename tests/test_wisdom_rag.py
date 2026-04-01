"""Unit tests for Wisdom RAG helpers and indexing (no real Chroma when upsert is mocked)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from wisdom_rag import (
    WisdomRAG,
    extract_description_from_prompt,
    extract_previous_failure_block,
    format_wisdom_block,
    parse_plan_descriptions,
    source_fingerprint,
    stable_id,
)


def test_stable_id_deterministic() -> None:
    assert stable_id("a") == stable_id("a")
    assert stable_id("a") != stable_id("b")


def test_parse_plan_descriptions(tmp_path: Path) -> None:
    p = tmp_path / "PLAN.md"
    p.write_text("- [ ] TASK_01: First\n- [x] TASK_02: Done\n", encoding="utf-8")
    m = parse_plan_descriptions(p)
    assert m["TASK_01"] == "First"
    assert m["TASK_02"] == "Done"


def test_extract_description_from_prompt() -> None:
    body = "**Description:** Build the widget\n\n## Your Task"
    assert extract_description_from_prompt(body) == "Build the widget"


def test_extract_previous_failure_block() -> None:
    prompt = """
## Architecture
x
## ⚠️ PREVIOUS FAILURE — Learn From This
oops
"""
    block = extract_previous_failure_block(prompt)
    assert "PREVIOUS FAILURE" in block
    assert "oops" in block


def test_format_wisdom_block_uses_fences() -> None:
    lines = format_wisdom_block(
        [{"error": "bad * markdown `_`", "fix": "fix ** line", "task_id": "T", "task_description": "d"}]
    )
    text = "\n".join(lines)
    assert "Lessons from Experience (Level 5)" in text
    assert "```" in text
    assert "bad * markdown `_`" in text
    assert "fix ** line" in text


def test_source_fingerprint_changes(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    h.write_text("[]")
    pl = tmp_path / "PLAN.md"
    pl.write_text("x")
    t = tmp_path / "t.jsonl"
    t.write_text("")
    fp1 = source_fingerprint(h, t, pl)
    h.write_text("[{}]")
    fp2 = source_fingerprint(h, t, pl)
    assert fp1 != fp2


def test_index_from_files_skips_when_manifest_matches(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    h = docs / "history.json"
    h.write_text("[]")
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: alpha\n")
    traj = docs / "t.jsonl"
    traj.write_text("")
    store = tmp_path / "store"
    store.mkdir()
    w = WisdomRAG(store)
    w.upsert_lesson = MagicMock()  # type: ignore[method-assign]

    n1 = w.index_from_files(h, traj, plan)
    assert n1 == 0
    assert w.upsert_lesson.call_count == 0

    n2 = w.index_from_files(h, traj, plan)
    assert n2 == 0
    assert w.upsert_lesson.call_count == 0


def test_index_from_files_upserts_history_and_skips_duplicate_jsonl(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    h = docs / "history.json"
    entry = {
        "task_id": "TASK_01",
        "attempt": 1,
        "timestamp": "2025-01-01T00:00:00+00:00",
        "evaluator_output": "fail",
        "claude_stderr": "",
    }
    h.write_text(json.dumps([entry]))
    plan = tmp_path / "PLAN.md"
    plan.write_text("- [ ] TASK_01: alpha\n")
    traj = docs / "t.jsonl"
    traj.write_text(
        json.dumps(
            {
                "task_id": "TASK_01",
                "timestamp": "2025-01-02T00:00:00+00:00",
                "input": "**Description:** alpha\n",
                "output_git_diff": "diff --git a",
            }
        )
        + "\n"
    )
    store = tmp_path / "store2"
    store.mkdir()
    w = WisdomRAG(store)
    w.upsert_lesson = MagicMock()  # type: ignore[method-assign]

    n = w.index_from_files(h, traj, plan)
    # History produces one lesson; trajectory may produce same doc hash if identical — at least one upsert
    assert n >= 1
    assert w.upsert_lesson.call_count == n


def test_retrieve_lessons_empty_query() -> None:
    w = WisdomRAG(Path("/tmp/wisdom-x-test"))
    assert w.retrieve_lessons("   ", top_k=3) == []
    assert w.retrieve_lessons("", top_k=3) == []
