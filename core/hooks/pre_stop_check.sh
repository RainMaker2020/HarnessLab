#!/usr/bin/env bash
PLAN="workspace/PLAN.md"
[ ! -f "$PLAN" ] && exit 0

REMAINING=$(grep -c '^\- \[ \]' "$PLAN" 2>/dev/null || echo 0)
if [ "$REMAINING" -gt 0 ]; then
  echo "HARNESS BLOCK: $REMAINING tasks still pending in PLAN.md."
  echo "Run the next task before stopping."
  exit 1   # non-zero blocks the Stop event
fi
echo "HARNESS: All tasks complete. Safe to stop."
exit 0