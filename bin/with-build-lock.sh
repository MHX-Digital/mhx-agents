#!/usr/bin/env bash
# Simple flock-based semaphore for heavy commands (npm ci, docker build,
# npm run build, etc) on resource-constrained hosts. Motivated by a real
# 2026-07-28 incident: the KVM4 VPS (4 vCPU) has a single self-hosted CI
# runner, and multiple PRs' Test/npm-audit/docker jobs queued up and ran
# serially, taking much longer than expected. This doesn't fix CI queuing
# itself, but gives interactive/manual heavy commands on the same box a way
# to not step on each other (or on a CI job already running).
#
# Usage: with-build-lock.sh [--timeout SECONDS] [--lock-name NAME] -- <command> [args...]
set -euo pipefail

TIMEOUT=600
LOCK_NAME="build"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    --lock-name)
      LOCK_NAME="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -h|--help)
      echo "usage: with-build-lock.sh [--timeout SECONDS] [--lock-name NAME] -- <command> [args...]"
      exit 0
      ;;
    *)
      echo "with-build-lock: unknown argument: $1 (did you forget '--'?)" >&2
      exit 2
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  echo "usage: with-build-lock.sh [--timeout SECONDS] [--lock-name NAME] -- <command> [args...]" >&2
  exit 2
fi

LOCK_DIR="${AAK_STATE_ROOT:-/srv/agent-architecture/state}/locks"
mkdir -p "$LOCK_DIR"
LOCK_FILE="$LOCK_DIR/${LOCK_NAME}.lock"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -w "$TIMEOUT" "$LOCK_FD"; then
  echo "with-build-lock: timed out after ${TIMEOUT}s waiting for lock '$LOCK_NAME' ($LOCK_FILE)" >&2
  exit 1
fi

echo "with-build-lock: acquired '$LOCK_NAME', running: $*" >&2
"$@"
