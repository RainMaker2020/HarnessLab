#!/usr/bin/env bash
set -euo pipefail
# HARNESS_ROOT can be overridden for testing; defaults to repo root derived from script location
ROOT="${HARNESS_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# Escape hatch: set HARNESS_SKIP_STOP_HOOK=1 during initial project setup
if [ "${HARNESS_SKIP_STOP_HOOK:-0}" = "1" ]; then
  echo "HARNESS: Stop hook bypassed (HARNESS_SKIP_STOP_HOOK=1)."
  exit 0
fi
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
# Grep fallback: read plan_file from harness.yaml without Python
if [ -z "$PLAN" ]; then
  if [ -f "$ROOT/harness.yaml" ]; then
    PLAN_REL=$(grep -E 'plan_file:' "$ROOT/harness.yaml" | head -1 \
      | sed 's/.*plan_file:[[:space:]]*//' \
      | tr -d '"'"'" \
      | xargs)
    if [ -n "$PLAN_REL" ]; then
      # Strip leading ./ if present
      PLAN_REL="${PLAN_REL#./}"
      PLAN="$ROOT/$PLAN_REL"
    fi
  fi
fi
# Cannot resolve PLAN.md — fail loudly, do NOT silently exit 0
if [ -z "$PLAN" ] || [ ! -f "$PLAN" ]; then
  echo "HARNESS BLOCK: Cannot resolve PLAN.md path from harness.yaml. Fix harness.yaml or Python env." >&2
  exit 1
fi

REMAINING=$(grep -c '^\- \[ \]' "$PLAN" 2>/dev/null || echo 0)
# shellcheck disable=SC2086
if [ "$REMAINING" -gt 0 ] 2>/dev/null; then
  echo "HARNESS BLOCK: $REMAINING tasks still pending in PLAN.md ($PLAN)." >&2
  echo "Run the next task before stopping." >&2
  exit 1
fi
echo "HARNESS: All tasks complete. Safe to stop."
exit 0
