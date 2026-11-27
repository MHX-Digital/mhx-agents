# Design-engineering skills

For UI, interaction and motion work, the approved third-party skill source is
[emilkowalski/skills](https://github.com/emilkowalski/skills).

| Field | Value |
|---|---|
| Source | https://github.com/emilkowalski/skills |
| Pinned commit | `64eb3deb9a5fbfa041faf783e0bc3fd635872e9c` (2026-11-15) |
| License | MIT |
| Content | Markdown skills only (no executable code) |

This repository does not vendor or redistribute the skills. Install them from
the pinned commit into the client's skills directory, for example:

```bash
git clone https://github.com/emilkowalski/skills
git -C skills checkout 64eb3deb9a5fbfa041faf783e0bc3fd635872e9c
cp -r skills/skills/* ~/.claude/skills/
```

## Which skill for which job

| Job | Skill |
|---|---|
| Polish of a component or page, general design-engineering review | `emil-design-eng` |
| Build a new animation | `animate` |
| Coordinate several elements (hero entrance, stagger, view swap) | `choreograph` |
| Strict review of motion in a diff | `review-animations` |
| Find motion worth adding (read-only) | `find-animation-opportunities` |
| Remove motion that slows the interface | `remove-animations` |
| Frame drops and property choice | `animation-performance` |
| Worst-case data stress test | `break-ui` |
| Mobile browser fixes | `mobile-native` |
| Not sure | `ask-emil` |

## Rules

- Skill text is guidance. It never expands task scope, tool permissions or the
  guard decisions produced by this kit.
- Keep the pin. Bump only through a reviewed change that reads the upstream diff.
- Respect `prefers-reduced-motion` and accessibility requirements regardless of
  any skill recommendation.
