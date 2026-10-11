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
| `--port N` | Card server port (default 8765; 0 = any free port) |
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

## Video quality and the receiver

Brightcove offers each goal as a progressive MP4 (usually only 720p) and as an
HLS ladder up to 1080p. pygoals reads the HLS master playlist and casts the
tallest **H.264** rendition no taller than `[playback] max_height` (default
`1080`, also in Settings as "Max video height"); HEVC/AV1/VP9 rungs are
skipped. If the HLS ladder is unavailable it falls back to the best MP4. The
chosen rendition is logged (`rendition for ...: HLS 1920x1080 4.1 Mbps ...`).

To force a specific rendition, open Settings > **Video quality**. The dropdown
lists what Brightcove actually offers for a recent goal (fetched when the
dialog opens, cached for a few hours; a typical NHL list is shown when
offline), e.g. `HLS 1080p - 1920x1080 - H.264 High - 4.1 Mbps`,
`MP4 720p`, `HLS 540p`, ..., `HLS adaptive (receiver chooses)`, plus
`Auto (best compatible)`. It is saved as `[playback] quality` (`auto`,
`hls:1080`, `mp4:720`, `hls:adaptive`, ...); if a clip lacks that rung the next
lower one is used. Changes apply to the next clip, including ones already
queued. Settings with a fixed set of values (video quality, auto max height,
log level) are dropdowns.

Player cards come in three styles (`[playback] card_mode`, also in Settings as
"Player card"):

* `video` (default): the card is encoded into a short silent 1080p H.264 clip
  (about 1 s of ffmpeg, done in the background while the previous goal plays)
  and sent to the TV together with the goal as a two-item cast queue, so the TV
  goes card -> goal with about a second of buffering and no backdrop. Needs
  ffmpeg: `imageio-ffmpeg` (a dependency, bundles a binary) or `ffmpeg` on
  PATH; without it pygoals falls back to `image`.
* `image`: the card is shown as a still PNG. Some Google TV devices (seen on
  an onn 4K Pro) play only the audio of a video loaded after an image in the
  same receiver session, with the clock frozen a few seconds in, so pygoals
  restarts the receiver between card and goal. That leaves several seconds of
  cast backdrop in between.
* `off`: no card.

`card_seconds` ("Card duration") sets how long the card shows (video cards are
at least 1 s). A watchdog polls the receiver every few seconds and skips a clip
whose position stops advancing for 25 s or that runs well past its length.

## pygoals Cast receiver (optional)

`receiver/` holds a Google Cast Web Receiver (CAF v3, static HTML/CSS/JS) that
plays the goal and draws the player card as an HTML overlay: headshot, team
logo and colours, scorer and title. The card appears the instant a goal is
loaded (it covers buffering), stays for the card duration, then shrinks to a
lower third, so there is no gap and no PNG/MP4 card is generated. When nothing
is queued it shows a pygoals idle screen. It is published at
https://gratefulnuckle.github.io/pygoals-receiver/ (mirror repo
`gratefulnuckle/pygoals-receiver`, GitHub Pages) and registered as Cast app
`A7C76189`.

The app is unpublished, so it only launches on devices registered as test
devices in the [Cast SDK Developer Console](https://cast.google.com/publish/)
(add the device serial number, then allow ~15 minutes and reboot the device).
Others can register their own receiver URL and put that app ID in settings.

```ini
[cast]
receiver_mode = auto        ; auto | custom | default
receiver_app_id = A7C76189  ; blank = always the Default Media Receiver
```

* `auto`: launch the pygoals receiver when an app ID is set; if it can't launch
  (device not registered, timeout) show one notification and keep using the
  Default Media Receiver with video cards until settings change or another TV
  is picked.
* `custom`: always try the pygoals receiver (retried for each goal; falls back
  to the default receiver for that goal).
* `default`: never use it.

Both are in Settings ("Cast receiver", "Receiver app ID"). Loads carry
`media.customData.pygoals` (see `receiver/README.md`).

## Troubleshooting: the TV shows a blank receiver / no player cards

Player cards are PNGs that the Chromecast downloads from a small web server
inside pygoals on this PC (`http://<this PC>:8765/card-....png`). If the PC
blocks inbound connections, the TV can't fetch them. pygoals waits a few
seconds for the TV to fetch each card; if it never does, it shows a
"TV can't reach this PC" notification once and plays the clips without cards.
The highlight videos themselves stream from the NHL CDN and are not affected.

`logs/pygoals.log` shows every request the TV makes
(`card server: 192.168.x.y GET card-....png -> 200`), every `LOAD` sent to the
Chromecast and every media status change (`Chromecast media: PLAYING ...`).
No `card server:` lines after a `LOAD image/png` means the request was blocked.

To allow it, keep the fixed port (`[server] port = 8765` in `settings.ini`) and
allow inbound TCP on that port for private networks in whichever firewall is
active on the PC:

* **Windows Defender Firewall** - in an *administrator* PowerShell:

  ```powershell
  New-NetFirewallRule -DisplayName "pygoals cards (TCP 8765)" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private
  ```

  (Remove it later with `Remove-NetFirewallRule -DisplayName "pygoals cards (TCP 8765)"`.)
* **Norton or another security suite** (which replaces the Windows firewall) -
  add a traffic rule allowing inbound TCP 8765 from the local network, or allow
  the Python interpreter that runs pygoals (the path to `pythonw.exe` is shown in
  the notification and log, e.g.
  `%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe`). Allowing the
  project folder is not enough: the program listening is the interpreter.

The PC's network should be marked *Private*. Alternatively turn cards off in
Settings.

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
