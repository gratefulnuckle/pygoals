# ISSUES — pygoals

All tracked items are **closed** as of 2026-08-20 (module split + tests).

Do **not** put Brightcove or Imgur secrets in this file.

| ID | Resolution |
|----|------------|
| PYG-001 / 016 / 025 | Imgur removed; cards served on LAN HTTP |
| PYG-002 | `BRIGHTCOVE_PK` from environment only |
| PYG-003 | Cards written under a temp dir / `--overlay-path` |
| PYG-004 | SIGINT/SIGTERM → `shutdown()`; no pynput |
| PYG-005 / 013 | Skip compilations and items without player/team |
| PYG-006 / 011 / 021 | `deque` + `Lock`; `GoalClip`; drain after play |
| PYG-007 | Highest MP4 by container/height, not `sources[-1]` |
| PYG-008 | Event id falls back to Brightcove id, never `0` |
| PYG-009 | `MediaStatusListener`; advance on `FINISHED` only |
| PYG-010 | `timeout=10` + `raise_for_status` |
| PYG-012 | One Zeroconf; `stop_discovery` on shutdown |
| PYG-014 | Seen-set updated after playback starts |
| PYG-015 / 024 | Theme table, ESPN slugs, RGBA paste, font fallback |
| PYG-017 / 023 / 030 | `--device`, `--list-devices`, `--dry-run`, validated picker |
| PYG-018 | README, requirements, tests, LICENSE, `.gitignore` |
| PYG-019 | `block_until_active` after every `play_media` |
| PYG-020 | `reset_queue()` is a real method (tests/internal) |
| PYG-022 | Unused SVG/reportlab/imgur/pynput imports gone |
| PYG-026 | `nhl_ingest`, `brightcove`, `cards`, `media_server`, `team_theme` |
| PYG-027 | `render_card` returns a path |
| PYG-028 / 032 | `logging`; card uses listing `title` |
| PYG-029 / 031 | Dead comments/typos/builtin shadow gone with the rewrite |
