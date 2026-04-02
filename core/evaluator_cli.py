#!/usr/bin/env python3
"""Shim: stable path `core/evaluator_cli.py` — implementation in `harness.evaluator_cli`."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from harness.evaluator_cli import main  # noqa: E402

if __name__ == "__main__":
    main()
