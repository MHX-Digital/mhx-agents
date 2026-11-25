# Templates

Starting point for onboarding a new Tier 1/2 repo. See the
main `README.md`'s "Reusing this kit in a new repo" section for the full walkthrough.

## Convention

Most files here end in `.template` and contain `<PLACEHOLDER>` markers: copy the file, fill in
the placeholders, drop the `.template` suffix, done.

**Two files in `templates/repository/` don't follow that pattern, on purpose:**

- **`.claude/settings.json`** has no `.template` suffix and no placeholders because it's already
  syntactically complete. The example hook command path (`/opt/mhx-agents/bin/aak`)
  must match a separately provisioned runtime (see the main README's Setup section).
  Review the target project's scope and permissions before enabling it. Copying this
  template is not proof that the runtime is installed or the guard is enforced.
- **`.mcp.example.json`** uses a committed example naming convention (
  committed `*.example.json` files are materialized locally, e.g. into a gitignored `.mcp.json`,
  by whoever sets up the repo -- not renamed by dropping a suffix). It does contain a
  `<repo>` placeholder to fill in.

If you add a new file to `templates/repository/` that's repo-independent like `.claude/settings.json`,
skip the `.template` suffix for it too and note why here.
