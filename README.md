# pygoals

Cast NHL **goal highlight** clips to a Chromecast on your LAN, from a small
dark media bar in the Windows system tray. Before each clip the TV can show a
generated player card (headshot, team colors, title) served from this PC.

**Unofficial.** Not affiliated with the NHL or Brightcove. Personal LAN use
only. Endpoints and player keys rotate.

| Docs | |
|------|--|
| Product spec | [`openspec/`](openspec/) |
| Work tracker | [`ISSUES.md`](ISSUES.md) |
| Plan | [`ROADMAP.md`](ROADMAP.md) |

---

## Setup

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt        # or: pip install -e .   (adds the pygoals command)
python pygoals.py                      # no arguments needed
```

On first run pygoals creates `settings.ini` next to `pygoals.py`, opens
**Settings** so you can paste your Brightcove policy key, then opens
**Devices** so you can pick a Chromecast. After that, running `pygoals` with no
arguments just works.

The key can also come from the environment, which overrides `settings.ini`:

```powershell
$env:BRIGHTCOVE_PK = "your-player-policy-key"   # PowerShell
set BRIGHTCOVE_PK=your-player-policy-key        # cmd.exe
```

or from a `.env` file next to `pygoals.py` (copy `.env.example`). Never commit
the key: `settings.ini`, `.env`, `state.json` and `logs/` are gitignored.

## The tray app (default)

`python pygoals.py` (or `pygoals` / `pythonw pygoals.py`) starts the tray icon,
a goal-light disc whose lamp shows state: grey idle, red playing, blue polling
paused, amber error.

* **Left-click** the icon: the media bar slides up ~10 px above the tray (works
  with the taskbar on any edge and on any monitor). It shows the headshot or
  team logo, the clip title, a team-colour accent, and buttons for Skip,
  Pause/Resume polling, Chromecast picker, Replay all, Settings and Quit.
  Click-drag anywhere on the bar to move it; the position is remembered. Use
  the pin button (or double-click the bar) to snap it back above the tray.
* **Right-click** the icon: dark menu with Now playing, Skip, Pause polling,
  Chromecast submenu, Replay all, Devices, Settings, Open log, Quit.
* **Toasts**: dark notifications stack above the tray for new goals and for
  errors (rejected key, no Chromecast, card server stuck on loopback, network).
  Clicking a key/device error opens the relevant page.
* **Settings** page edits `settings.ini` with validation; most changes apply
  immediately (the card port applies after a restart).
* **Devices** page scans the LAN (Scan button with progress), lists name, model
  and IP, and switches playback to the device you pick (saved to
  `settings.ini`).

If PyQt6 is missing, pygoals logs a warning and falls back to console mode.

## Console mode and flags

Flags are optional, per-run overrides; they are never written to
`settings.ini`.

| Flag | Meaning |
|------|---------|
| `--cli` / `--no-tray` | Console mode instead of the tray |
| `--tray` | Tray mode (the default; accepted for compatibility) |
| `--dry-run` | List clips; no Cast, no key required (console) |
| `--list-devices` | Print Chromecasts (name, model, IP) and exit (console) |
| `--once` | Play the current queue until the last clip finishes, then quit (console) |
| `--device NAME` | Friendly-name substring; skips the picker |
| `--known-host IP` | Repeatable |
| `--poll-seconds N` | 5-3600 |
| `--port N` | Card server port (0 = any free port) |
| `--no-overlay` | Video only, no player cards |
| `--overlay-path DIR` | Where card PNGs are written (default: a temp dir, removed on exit) |
| `--config PATH` | Use another settings.ini |
| `--log-level LEVEL` / `--no-log-file` | Logging |
| `--forget-seen` | Ignore `state.json` this run |
| `--quiet` | No ASCII banner |
| Ctrl+C | Graceful shutdown (exit code 130) |

Exit codes: `0` ok, `1` no videos/devices, `2` missing key or no way to choose a
device, `130` interrupted.

## Configuration and files (portable)

Everything lives next to the app (the folder of `pygoals.py`, or of the `.exe`
if frozen). Nothing is written to AppData.

| File | What |
|------|------|
| `settings.ini` | All settings (created with defaults on first run; see `settings.example.ini`) |
| `.env` | Optional environment overrides (`BRIGHTCOVE_PK`, `PYGOALS_DEVICE`, ...) |
| `state.json` | Recently played clip ids, so restarts don't replay old goals |
| `logs/pygoals.log` | Rotating log (1 MB x 3) |

Precedence: **command-line flags > environment / `.env` > `settings.ini` >
defaults.** Environment variables: `BRIGHTCOVE_PK`, `PYGOALS_DEVICE`,
`PYGOALS_KNOWN_HOSTS`, `PYGOALS_POLL_SECONDS`, `PYGOALS_PORT`,
`PYGOALS_LOG_LEVEL`. `PYGOALS_HOME` moves the whole data folder (used by tests).

## Run at login (Windows)

Either drop a shortcut in the Startup folder (`Win+R`, `shell:startup`) with
target:

```text
"C:\path\to\pygoals\.venv\Scripts\pythonw.exe" "C:\path\to\pygoals\pygoals.py"
```

or create a Task Scheduler task "At log on" running the same command.
`pythonw.exe` has no console window; logs go to `logs\pygoals.log`. If you
installed with `pip install -e .`, the `pygoals` GUI script in
`.venv\Scripts\` works too. Pick the device once in the tray; no flags needed.

## Layout

| Path | Role |
|------|------|
| `pygoals.py` | Entry point, flags, console mode |
| `tray.py` | Tray controller (Qt signals bridge, menus, pages, toasts) |
| `tray_widgets.py` / `tray_style.py` | Media bar, toasts, Settings/Devices pages, dark QSS, drawn icons |
| `tray_geometry.py` | Pure positioning math for the bar and toasts |
| `player.py` | Chromecast engine: discovery, connect, card + clip, polling, events |
| `clip_queue.py` | Thread-safe queue, seen/failed state, `state.json` |
| `settings.py` / `config.py` | settings.ini schema + validation; paths, `.env`, logging |
| `nhl_ingest.py` | Forge listing to `GoalClip` |
| `brightcove.py` | Source pick (HTTPS MP4 > HLS) + Playback API |
| `cards.py` | 1280x720 card, contrast-safe wrapped title |
| `media_server.py` | LAN HTTP that serves only `idle.png` / `card-*.png` |
| `team_theme.py` | Colors, ESPN slugs, contrast helpers |
| `tests/` | pytest, fixtures, fake Chromecast, offscreen Qt smoke tests |

## Development

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests never touch the network or a real Chromecast, and run the Qt UI
offscreen.

## License

MIT. See [LICENSE](LICENSE).
