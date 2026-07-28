#!/usr/bin/env bash
# Daily standup: reads open issues, recent CI runs, and recent duplication
# incidents, produces a prioritized text summary on stdout. Read-only -
# never creates, edits, closes, comments on, or merges anything. Run it
# from inside the repo you want a standup for, or pass --repo OWNER/NAME.
#
# Usage: daily-standup.sh [--repo OWNER/NAME]
set -euo pipefail

REPO_ARGS=()
if [[ "${1:-}" == "--repo" ]]; then
  REPO_ARGS=(--repo "$2")
fi

echo "=== Daily standup: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo

echo "--- Open issues (priority:high/medium first) ---"
gh issue list "${REPO_ARGS[@]}" --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --jq '
    sort_by(
      if (.labels | map(.name) | any(startswith("priority:high"))) then 0
      elif (.labels | map(.name) | any(startswith("priority:medium"))) then 1
      else 2 end
    )
    | .[]
    | "#\(.number)  \(.title)  [\(.labels | map(.name) | join(","))]"
  '
echo

echo "--- Recent CI runs (last 10) ---"
gh run list "${REPO_ARGS[@]}" --limit 10 \
  --json displayTitle,status,conclusion \
  --jq '.[] | "\(.status)/\(.conclusion // "-")  \(.displayTitle)"'
echo

INCIDENTS_FILE="docs/architecture/DUPLICATION_INCIDENTS.json"
if [[ -f "$INCIDENTS_FILE" ]]; then
  echo "--- Duplication incidents in the last 30 days ($INCIDENTS_FILE) ---"
  python3 - "$INCIDENTS_FILE" << 'PYEOF'
import json
import sys
from datetime import datetime, timedelta, timezone

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    incidents = json.load(f)

cutoff = datetime.now(timezone.utc) - timedelta(days=30)
recent = []
for inc in incidents:
    try:
        d = datetime.fromisoformat(inc["date"]).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        continue
    if d >= cutoff:
        recent.append(inc)

if not recent:
    print("(none in the last 30 days)")
else:
    for inc in recent:
        target = inc.get("canonicalTarget", {})
        print(
            f"{inc.get('date', '?')}  {inc.get('duplicateArtifact', '?')} -> "
            f"{target.get('path', '?')} ({target.get('symbol', '?')})"
        )
PYEOF
else
  echo "--- $INCIDENTS_FILE not found, skipping duplication-incident section ---"
fi

echo
echo "(read-only summary - nothing was created, edited, commented on, or merged by this script)"
