# Templates

Starting point for onboarding a new Tier 1/2 repo (master plan section 8.1/8.2). See the
main `README.md`'s "Reusing this kit in a new repo" section for the full walkthrough.

## Convention

Most files here end in `.template` and contain `<PLACEHOLDER>` markers: copy the file, fill in
the placeholders, drop the `.template` suffix, done.

**Two files in `templates/repository/` don't follow that pattern, on purpose:**

- **`.claude/settings.json`** has no `.template` suffix and no placeholders because it's already
  complete and repo-independent -- the hook command path (`/home/mhx/agent-architecture-kit/bin/aak`)
  is a fixed cross-repo convention (see the main README's Setup section), not something that
  varies per repo. Copy it byte-for-byte.
- **`.mcp.example.json`** follows the master plan's own naming convention instead (section 8.2:
  committed `*.example.json` files are materialized locally, e.g. into a gitignored `.mcp.json`,
  by whoever sets up the repo -- not renamed by dropping a suffix). It does contain a
  `<repo>` placeholder to fill in.

If you add a new file to `templates/repository/` that's repo-independent like `.claude/settings.json`,
skip the `.template` suffix for it too and note why here.
