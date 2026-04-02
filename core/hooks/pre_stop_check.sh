#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLAN=""
if command -v python3 >/dev/null 2>&1; then
  PLAN="$(cd "$ROOT" && python3 - <<'PY'
import sys
from pathlib import Path
try:
    import yaml
except ImportError:
    sys.exit(0)
p = Path("harness.yaml")
if not p.exists():
    print("")
    sys.exit(0)
try:
    d = yaml.safe_load(p.read_text()) or {}
except Exception:
    print("")
    sys.exit(0)
paths = d.get("paths") or {}
pf = paths.get("plan_file") or d.get("plan_file")
if not pf:
    print("")
    sys.exit(0)
print((Path.cwd() / pf).resolve())
PY
)"
fi
if [ -z "$PLAN" ] || [ ! -f "$PLAN" ]; then
  PLAN="$ROOT/workspace/PLAN.md"
fi
if [ ! -f "$PLAN" ]; then
  exit 0
fi

REMAINING=$(grep -c '^\- \[ \]' "$PLAN" 2>/dev/null || echo 0)
# shellcheck disable=SC2086
if [ "$REMAINING" -gt 0 ] 2>/dev/null; then
  echo "HARNESS BLOCK: $REMAINING tasks still pending in PLAN.md ($PLAN)."
  echo "Run the next task before stopping."
  exit 1
fi
echo "HARNESS: All tasks complete. Safe to stop."
exit 0
