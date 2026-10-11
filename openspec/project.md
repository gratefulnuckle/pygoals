# pygoals

## Purpose

pygoals watches NHL goal-highlight video listings, resolves a Chromecast-playable
MP4, shows a generated player card on the TV, then plays the clip. It is a
personal LAN companion for game night, not a redistribution service. The default
UI is a Windows system-tray app with a dark media bar; a console mode remains.

**Unofficial.** Not affiliated with the NHL or Brightcove. Clip URLs and the
Brightcove player policy key are third-party; they can rotate. Do not
redistribute media.

## Tech stack

- Python 3.10+ (developed on 3.14)
- `requests` (shared Session with retries) for NHL Forge DAPI, Brightcove Playback, player landing, logos
- `pychromecast` + `zeroconf` for discovery and media
- `Pillow` for 1280x720 player cards
- `PyQt6` for the tray icon, media bar, toasts, Settings and Devices pages
- stdlib `http.server` for LAN card serving, `configparser` for `settings.ini`
- `pytest` (fixtures, fake Chromecast, offscreen Qt)

## Current tree (as of 2026-10-11, v1.2.0)

| Path | Role |
|------|------|
| `pygoals.py` | Entry point; tray by default, `--cli`/headless flags for console |
| `tray.py`, `tray_widgets.py`, `tray_style.py`, `tray_geometry.py` | Qt UI |
| `player.py` | `NHLVideoPlayer` engine + events (UI-agnostic) |
| `clip_queue.py` | `ClipQueue` (pending/current/seen/failed), `SeenStore` |
| `settings.py`, `config.py` | settings.ini schema/validation; portable paths, `.env`, logging |
| `nhl_ingest.py`, `brightcove.py`, `cards.py`, `media_server.py`, `team_theme.py`, `http_util.py` | Ingest, playback API, cards, LAN HTTP, theme, HTTP |
| `pyproject.toml`, `requirements*.txt`, `tests/`, `LICENSE` | Packaging and tests |

Secrets come from `settings.ini` (gitignored) or the environment/`.env`.
Cards are LAN HTTP. Advance happens on media FINISHED for the current clip
only. Ctrl+C / Quit shut down cleanly.

## Constraints

- LAN Chromecast only; cards MUST be reachable from the Cast device
  (`http://<lan-ip>:<port>/...`, never `localhost` or `file://`). The LAN IP is
  chosen by routing toward the Chromecast; a loopback fallback is reported.
- Portable: `settings.ini`, `state.json`, `logs/` live next to the app; nothing
  in AppData. No secrets in git.
- Windows is the primary host; font and paths MUST NOT assume one user.
- Do not log policy keys at any level.

## Non-goals

- Re-hosting or selling NHL clips
- Multi-room playback
- Third-party image hosts for cards
- `svglib` / `reportlab` unless SVG logos are an explicit, tested path
