"""Unit tests for ContractVerifier (mocked Anthropic)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from evaluator import ContractVerifier


class _Cfg:
    spec_doc = None
    models = {"contract_verifier": "claude-3-5-sonnet-20241022"}


def test_verify_contract_passes_on_final_line_approve(tmp_path):
    spec = tmp_path / "SPEC.md"
    spec.write_text("# S\nDo X.")
    cfg = _Cfg()
    cfg.spec_doc = spec
    ct = tmp_path / "TASK_01.contract.test.ts"
    ct.write_text("test('x', () => {})")

    msg = MagicMock()
    msg.content = [MagicMock(type="text", text="Looks good.\nAPPROVE")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = msg

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ContractVerifier(cfg).verify_contract("TASK_01", "Do X", ct)

    assert result.passed is True


def test_verify_contract_fails_on_final_line_reject(tmp_path):
    spec = tmp_path / "SPEC.md"
    spec.write_text("# S\nDo X.")
    cfg = _Cfg()
    cfg.spec_doc = spec
    ct = tmp_path / "TASK_01.contract.test.ts"
    ct.write_text("test('x', () => {})")

    msg = MagicMock()
    msg.content = [MagicMock(type="text", text="Gaps found.\nREJECT")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = msg

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ContractVerifier(cfg).verify_contract("TASK_01", "Do X", ct)

    assert result.passed is False


def test_verify_contract_no_substring_reject_false_positive(tmp_path):
    """Mentioning REJECT in prose but ending APPROVE on last line must pass."""
    spec = tmp_path / "SPEC.md"
    spec.write_text("# S\nDo X.")
    cfg = _Cfg()
    cfg.spec_doc = spec
    ct = tmp_path / "TASK_01.contract.test.ts"
    ct.write_text("test('x', () => {})")

    msg = MagicMock()
    msg.content = [
        MagicMock(
            type="text",
            text="Earlier I considered REJECT but changed my mind.\nAPPROVE",
        )
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = msg

    with patch("evaluator.anthropic.Anthropic", return_value=mock_client):
        result = ContractVerifier(cfg).verify_contract("TASK_01", "Do X", ct)

    assert result.passed is True
