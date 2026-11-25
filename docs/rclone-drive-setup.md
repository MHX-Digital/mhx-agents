# Google Drive mount on your VPS (rclone) — setup

Prepared by the agent; **the OAuth step below needs you interactively** —
it can't be scripted or completed by an agent.

## 1. One-time OAuth (you do this, on the VPS)

```
ssh your-vps
rclone config
```

Then:
1. `n` (new remote)
2. Name: `gdrive` (the scripts here assume this exact name)
3. Storage type: `drive` (Google Drive) — type `drive` or its number in the list
4. Client ID / Client Secret: leave blank (uses rclone's default) unless you
   want your own Google Cloud OAuth app
5. Scope: `1` (full access) or `2` (read-only) — `2` is enough and safer
   for this read-only mount
6. Root folder ID: leave blank (whole Drive) unless you want to scope to one folder
7. Service account file: leave blank
8. Edit advanced config: `n`
9. **Use auto config: `n`** (the VPS has no browser) — rclone will print a
   command to run on a machine that DOES have a browser (your PC), or a URL
   to open manually; paste the resulting verification code back into the
   VPS prompt
10. Confirm, `y` to keep, `q` to quit config

Verify: `rclone lsd gdrive:` should list your Drive's top-level folders.

## 2. Install the mount as a systemd user service

```
ssh your-vps
mkdir -p ~/.config/systemd/user
cp ~/mhx-agents/rclone-drive.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rclone-drive.service
```

**Enable lingering** so the mount survives you logging out of SSH (user
services stop when the last session for that user ends, unless lingering is on):

```
sudo loginctl enable-linger "$USER"
```

## 3. Verify

```
systemctl --user status rclone-drive.service
ls ~/gdrive
```

`~/gdrive` should show your real Drive contents (read-only — writes will
fail on purpose, this mount is for reading, not syncing).

## Notes

- VFS cache capped at 2GB (`RCLONE_CACHE_MAX_SIZE` env var to override),
  24h max age — bounded disk usage, not the whole Drive cached forever.
- To unmount manually: `systemctl --user stop rclone-drive.service`
- `bin/mount-drive.sh` refuses to run (exits 1 with a clear message) if the
  `gdrive` remote isn't configured yet — safe to enable the systemd unit
  before step 1 is done, it'll just fail closed and retry (`Restart=always`)
  until the remote exists.
