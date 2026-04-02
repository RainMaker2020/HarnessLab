import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness_plan import PlanParser, Task


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text(
        "# Plan\n\n"
        "- [ ] TASK_01: Create hello_world.py\n"
        "- [ ] TASK_02: Add farewell() function\n"
        "- [x] TASK_00: Already done\n"
    )
    return p


def test_next_task_returns_first_unchecked(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    assert task is not None
    assert task.task_id == "TASK_01"
    assert task.description == "Create hello_world.py"


def test_next_task_skips_checked_tasks(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text("- [x] TASK_01: Done\n- [ ] TASK_02: Not done\n")
    parser = PlanParser(p)
    task = parser.next_task()
    assert task.task_id == "TASK_02"


def test_next_task_returns_none_when_all_done(tmp_path):
    p = tmp_path / "PLAN.md"
    p.write_text("- [x] TASK_01: Done\n- [x] TASK_02: Also done\n")
    parser = PlanParser(p)
    assert parser.next_task() is None


def test_mark_done_checks_off_task(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    parser.mark_done(task)
    content = plan_file.read_text()
    assert "- [x] TASK_01" in content
    assert "- [ ] TASK_02" in content


def test_task_id_format_is_deterministic(plan_file):
    parser = PlanParser(plan_file)
    task = parser.next_task()
    assert task.task_id == "TASK_01"
