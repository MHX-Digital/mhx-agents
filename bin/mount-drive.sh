#!/usr/bin/env bash
# Mounts Google Drive read-only via rclone with a size-limited VFS cache.
# Requires the "gdrive" rclone remote to already be configured - that's a
# one-time interactive OAuth step a human has to do (see
# docs/rclone-drive-setup.md), this script does not and cannot do it.
set -euo pipefail

REMOTE_NAME="${RCLONE_REMOTE:-gdrive}"
MOUNT_POINT="${RCLONE_MOUNT_POINT:-$HOME/gdrive}"
CACHE_MAX_SIZE="${RCLONE_CACHE_MAX_SIZE:-2G}"

if ! rclone listremotes | grep -q "^${REMOTE_NAME}:$"; then
  echo "mount-drive: remote '${REMOTE_NAME}:' not found in rclone config." >&2
  echo "Run 'rclone config' first (see docs/rclone-drive-setup.md) - this needs interactive OAuth, can't be scripted." >&2
  exit 1
fi

mkdir -p "$MOUNT_POINT"

exec rclone mount "${REMOTE_NAME}:" "$MOUNT_POINT" \
  --vfs-cache-mode full \
  --vfs-cache-max-size "$CACHE_MAX_SIZE" \
  --vfs-cache-max-age 24h \
  --dir-cache-time 1h \
  --read-only \
  --umask 022 \
  --log-level INFO
