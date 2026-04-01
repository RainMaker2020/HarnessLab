import pytest
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from prompt_generator import PromptGenerator


@pytest.fixture
def tmp_harness(tmp_path):
    """Create a minimal harness directory structure in tmp_path."""
    arch = tmp_path / "ARCHITECTURE.md"
    arch.write_text("# Architecture Rules\n\nRule 1: Be correct.")
    spec = tmp_path / "SPEC.md"
    spec.write_text("# Spec\n\nBuild something useful.")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history = tmp_path / "docs" / "history.json"
    history.parent.mkdir()
    history.write_text("[]")

    class FakeConfig:
        architecture_doc = arch
        spec_doc = spec
        workspace_dir = workspace
        history_file = history

    return tmp_path, FakeConfig()


def test_generate_writes_harness_prompt_md(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    path = gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    assert path == config.workspace_dir / ".harness_prompt.md"
    assert path.exists()


def test_generate_contains_architecture_rules(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "Architecture Rules" in content
    assert "Rule 1: Be correct." in content


def test_generate_contains_spec(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "Build something useful." in content


def test_generate_contains_task_id_and_description(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "TASK_01" in content
    assert "Create hello_world.py" in content


def test_generate_injects_last_failure_on_retry(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    failure = {
        "task_id": "TASK_01",
        "attempt": 1,
        "claude_exit_code": 1,
        "evaluator_passed": False,
        "evaluator_output": "SyntaxError: invalid syntax",
        "claude_stdout": "",
        "claude_stderr": "Error: bad code",
    }
    gen.generate("TASK_01", "Create hello_world.py", attempt=2, last_failure=failure)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "SyntaxError: invalid syntax" in content
    assert "Error: bad code" in content


def test_generate_includes_contract_when_path_provided(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    contract = config.workspace_dir / "TASK_01.contract.test.ts"
    contract.write_text("expect(true).toBe(true);")
    gen.generate(
        "TASK_01",
        "Create hello_world.py",
        attempt=1,
        last_failure=None,
        contract_path=contract,
    )
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "The CONTRACT" in content
    assert "NOT allowed to modify" in content
    assert "expect(true)" in content


def test_generate_no_retry_section_on_first_attempt(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.generate("TASK_01", "Create hello_world.py", attempt=1, last_failure=None)
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "PREVIOUS FAILURE" not in content


def test_generate_includes_wisdom_lessons(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    lessons = [
        {
            "task_id": "TASK_99",
            "task_description": "Similar work",
            "error": "ImportError: missing module",
            "fix": "Added dependency to package.json",
        }
    ]
    gen.generate(
        "TASK_01",
        "Create hello_world.py",
        attempt=1,
        last_failure=None,
        wisdom_lessons=lessons,
    )
    content = (config.workspace_dir / ".harness_prompt.md").read_text()
    assert "Lessons from Experience (Level 5)" in content
    assert "ImportError: missing module" in content
    assert "Added dependency" in content
    assert "Do not repeat the mistake" in content


def test_write_changelog_creates_file(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.write_changelog("TASK_01", "Create hello_world.py")
    changelog = config.workspace_dir / "CHANGELOG.md"
    assert changelog.exists()
    content = changelog.read_text()
    assert "TASK_01" in content
    assert "Create hello_world.py" in content


def test_write_changelog_appends_on_multiple_tasks(tmp_harness):
    _, config = tmp_harness
    gen = PromptGenerator(config)
    gen.write_changelog("TASK_01", "First task")
    gen.write_changelog("TASK_02", "Second task")
    content = (config.workspace_dir / "CHANGELOG.md").read_text()
    assert "TASK_01" in content
    assert "TASK_02" in content
