# pygoals

## Purpose

pygoals watches NHL goal-highlight video listings, resolves a Chromecast-playable
MP4, shows a generated player card on the TV, then plays the clip. It is a
personal LAN companion for game night, not a redistribution service.

**Unofficial.** Not affiliated with the NHL or Brightcove. Clip URLs and the
Brightcove player policy key are third-party; they can rotate. Do not
redistribute media.

## Tech stack

- Python 3.10+
- `requests` — NHL Forge DAPI, Brightcove Playback, player landing, logos
- `pychromecast` + `zeroconf` — discovery and media
- `Pillow` — 1280×720 player cards
- `pynput` — intended global hotkey (currently broken)
- Optional: local `http.server` for cards (preferred over Imgur)

## Current tree (as of 2026-08-20)

| Path | Role |
|------|------|
| `pygoals.py` | Entire app (~367 lines), class `NHLVideoPlayer` |
| No README (this repo now has one), no deps file, no tests, no license | |

Secrets are environment-only. Cards are LAN HTTP. SIGINT shuts down.
Ingest skips compilations. See ISSUES.md (all closed).

## Constraints

- LAN Chromecast only; cards MUST be reachable from the Cast device
  (`http://<lan-ip>:<port>/...`, never `localhost` or `file://`).
- No secrets in git. `.env` / `secrets.json` gitignored.
- Windows is the original host; font and paths MUST NOT assume one user.
- MIT-or-choose a license when you add LICENSE; until then treat as personal.
- Do not log policy keys, Imgur secrets, or public card URLs at INFO.

## Non-goals

- Re-hosting or selling NHL clips
- Multi-room product before single-device shutdown works
- Keeping Imgur as the default card transport
- `svglib` / `reportlab` unless SVG logos are an explicit, tested path
