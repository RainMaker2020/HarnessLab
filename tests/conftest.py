"""Shared pytest fixtures for HarnessLab tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _auto_mock_worker_session_for_orchestrator_tests(request):
    """
    Patch WorkerSession inside sub_orchestrator for any test that uses the
    `config` fixture (i.e. orchestrator integration tests).

    Tests in test_worker_session.py import WorkerSession directly from the
    worker_session module and manage their own mocks, so they are unaffected.
    """
    if "config" not in request.fixturenames:
        yield
        return

    mock_session = MagicMock()
    mock_session.run_task.return_value = "Task complete."
    mock_session.session_cost_tokens = {"input": 0, "output": 0, "total": 0}

    with patch("sub_orchestrator.WorkerSession", return_value=mock_session):
        yield
