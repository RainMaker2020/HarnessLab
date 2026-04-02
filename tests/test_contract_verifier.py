"""Unit tests for ContractVerifier (mocked Brain client via brain_client_for_role)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from harness.eval.evaluator import ContractVerifier


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

    mock_client = MagicMock()
    mock_client.complete_text.return_value = "Looks good.\nAPPROVE"

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ContractVerifier(cfg).verify_contract("TASK_01", "Do X", ct)

    assert result.passed is True
    mock_client.complete_text.assert_called_once()


def test_verify_contract_fails_on_final_line_reject(tmp_path):
    spec = tmp_path / "SPEC.md"
    spec.write_text("# S\nDo X.")
    cfg = _Cfg()
    cfg.spec_doc = spec
    ct = tmp_path / "TASK_01.contract.test.ts"
    ct.write_text("test('x', () => {})")

    mock_client = MagicMock()
    mock_client.complete_text.return_value = "Gaps found.\nREJECT"

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
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

    mock_client = MagicMock()
    mock_client.complete_text.return_value = (
        "Earlier I considered REJECT but changed my mind.\nAPPROVE"
    )

    with patch("harness.eval.evaluator.brain_client_for_role", return_value=mock_client):
        result = ContractVerifier(cfg).verify_contract("TASK_01", "Do X", ct)

    assert result.passed is True
