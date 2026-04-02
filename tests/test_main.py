"""Tests for manage.py CLI (e.g. ``--init``)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "core"))

from harness.exceptions import HarnessError


def test_main_init_invokes_scaffolder():
    import manage as main_mod

    with patch.object(main_mod, "Scaffolder") as MockScaff, patch.object(main_mod, "ModelRouter") as MockRoute:
        with patch.object(sys, "argv", ["prog", "--init", "my idea", "-y"]):
            main_mod.main()
        MockScaff.assert_called_once()
        cfg_passed = MockScaff.call_args[0][0]
        MockRoute.assert_called_once_with(cfg_passed)
        MockScaff.return_value.run.assert_called_once_with("my idea", force=True)


def test_main_init_harness_error_exits_with_code_1():
    import manage as main_mod

    with patch.object(main_mod, "Scaffolder") as MockScaff, patch.object(main_mod, "ModelRouter"):
        MockScaff.return_value.run.side_effect = HarnessError("bad")
        with patch.object(sys, "argv", ["prog", "--init", "x"]):
            with pytest.raises(SystemExit) as ei:
                main_mod.main()
            assert ei.value.code == 1
