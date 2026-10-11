# ROADMAP — pygoals

Built from the 2026-08-20 multi-agent review. Personal LAN tool: NHL goal
clips on a Chromecast with a player card.

Related: [ISSUES.md](ISSUES.md) · [openspec/](openspec/) · [README.md](README.md)

---

## Phase 0 — Make it runnable by someone else (now)

**Goal:** A second machine can start, not crash on page 1, and exit.

- Rotate Imgur credentials; move Brightcove PK to `BRIGHTCOVE_PK` (PYG-001/002).
- Temp overlay path (PYG-003).
- Default `playerId`/`team` to `None`; skip incomplete tags (PYG-005).
- Stop defaulting `statsEventId` to `0`; use Brightcove id as fallback (PYG-008).
- Timeouts + skip bad JSON instead of killing the Timer (PYG-010).
- Guard empty `sources`; pick MP4 by container (PYG-007).
- SIGINT + real `graceful_quit`: cancel timers, stop browser, `quit_app` (PYG-004/012).
- `requirements.txt` + this README; `.gitignore` for `.env`.
- Delete unused `svglib` / `reportlab` / duplicate imports (PYG-022).

**Suggestion:** Stay in one file for this phase. A split now just moves the
bugs.

---

## Phase 1 — Playback loop that is a loop

**Goal:** One clip after another without idle-PNG spam or races.

- `GoalClip` dataclass; drain `queuedVideos` after resolve (PYG-021/011).
- `threading.Lock` or `queue.Queue` (PYG-006).
- `MediaStatusListener`; advance on `FINISHED` of the MP4 (PYG-009).
- In-flight flag so card `sleep` cannot nest `play_next`.
- `--device` / `--list-devices` / validated picker (PYG-017/023).
- One Zeroconf owned by the player (PYG-012).
- Filter compilations out of the live queue (PYG-013).
- Mark seen after successful start, not at fetch (PYG-014).

**Suggestion:** Log skip reasons (`compilation`, `no_player`, `no_mp4`) —
you will need them the first night the CMS page is all recaps.

---

## Phase 2 — Cards without Imgur

**Goal:** Chromecast shows the card; the internet does not.

- Threaded HTTP server on LAN IP (not 127.0.0.1) (PYG-016).
- Unique temp PNG per event; delete after video starts.
- Bundled font; RGBA convert; default team theme (PYG-015/024).
- `teams.json` for colors, ESPN slugs, aliases (NJD→nj, LAK→LA, UTA).
- Idle/boot PNGs from the repo, not someone else’s Imgur ids.
- `--no-overlay` for video-only.

**Why this refactor:** Public uploads leak player+title, hit rate limits, and
need leaked credentials. LAN HTTP is less code than a robust Imgur client.

---

## Phase 3 — Product CLI and config

**Goal:** Scriptable, no banner-and-`input()` required.

- Flags: `--dry-run`, `--once`, `--poll-seconds`, `--overlay-path`, `--quiet`,
  `--log-level` (see `openspec/specs/cli-and-lifecycle`).
- Env + optional `pygoals.toml`; CLI wins.
- `logging` instead of `print`; never log PK or public card URLs.
- Bind or delete `reset()` (PYG-020).

**Suggestion:** `--dry-run` is the test you can run on a laptop with no TV.

---

## Phase 4 — Ingest that matches “live goals”

**Goal:** Tonight’s goals, not a CMS mixtape.

Forge `tags.slug=goal` is a taxonomy, not a live queue (compilations first,
`statsEventId` reused across games, pagination 25/100).

Suggested hybrid:

1. **Events** from NHL `api-web` (score / PBP `eventId`).
2. **Clip attach** from Forge/WSC by `(gameId, statsEventId)`.
3. **Media** from Brightcove with cached MP4 URLs.

Follow `nextUrl` only for backfill. Cache Brightcove sources with a TTL so
the 60s poll is cheap.

**Suggestion:** If api-web matching is too much, a tighter Forge filter
(`real-time-highlight` + duration cap) is an 80% fix.

---

## Phase 5 — Package split and tests

**Goal:** Seams for pytest.

```
src/pygoals/
  config.py
  nhl_api.py
  brightcove.py
  cards.py
  chromecast.py
  main.py
```

Tests with committed JSON fixtures: listing parse, MP4 pick, team aliases,
empty sources, skip reasons. No live Imgur. Optional live discovery behind
an explicit marker.

LICENSE + `pyproject.toml` console script `pygoals`.

---

## Later

- Team/player filters (`--team TOR`)
- Multi-room (only after single-device shutdown is boring)
- systemd / Windows service (`--device` required)
- Contrast-aware title color
- NHL logo CDN if you have a right to those assets
- Drop `pynput` if SIGINT + `--once` is enough

---

## Explicitly not on the roadmap

- Committing new secrets “just for now”
- Imgur delete-after-play as the long-term card design
- Re-introducing SVG/reportlab without a test
- Redistributing NHL media
- Merging this app into yekcohno (keep them siblings)
