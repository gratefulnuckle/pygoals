# cli-and-lifecycle

## Purpose

Runnable CLI, config precedence, and process lifecycle that a second person
can operate.

## Requirements

### Requirement: Documented install

The repo SHALL have README, pinned dependencies (`requirements.txt` or
`pyproject.toml`), `.gitignore` (venv, `__pycache__`, `.env`, overlay PNGs),
and a license. Unused imports (`svglib`, `reportlab`, duplicate `requests`)
SHALL be removed unless a tested SVG path exists.

#### Scenario: New machine

- GIVEN Python 3.10+ and a venv
- WHEN the user follows README
- THEN deps install
- AND `python pygoals.py --help` (or `python -m pygoals --help`) prints flags

### Requirement: CLI flags

Non-interactive use SHALL be possible.

| Flag | Behavior |
|------|----------|
| `--known-host` | Repeatable IP (already exists) |
| `--device` | Friendly-name substring; skip stdin |
| `--list-devices` | Discover, print, exit 0 |
| `--poll-seconds` | Fetch interval (default 60) |
| `--overlay-path` | Card output dir/file |
| `--no-overlay` | Video only |
| `--dry-run` | Fetch/resolve, print clip ids, no cast |
| `--log-level` | DEBUG..ERROR |
| `--quiet` | No ASCII banner |
| `--once` | Play current queue, then graceful quit |
| `--version` | Package/version string |

Exit codes: `0` clean, `1` no videos/devices, `2` config/auth, `130` SIGINT.

#### Scenario: Dry run

- GIVEN `--dry-run --quiet`
- WHEN the process starts
- THEN clips are listed
- AND no Cast session starts
- AND no image host upload occurs

### Requirement: Config precedence

CLI > env > optional config file > defaults.

Env names: `PYGOALS_KNOWN_HOSTS`, `PYGOALS_DEVICE`, `PYGOALS_OVERLAY_PATH`,
`BRIGHTCOVE_PK`, `IMGUR_CLIENT_ID`, `IMGUR_CLIENT_SECRET` (only if opt-in),
`PYGOALS_LOG_LEVEL`.

#### Scenario: Env PK, CLI device

- GIVEN `BRIGHTCOVE_PK` in the environment and `--device Kitchen`
- WHEN the app starts
- THEN Playback API uses the env key
- AND Kitchen is selected even if a config file names another device

### Requirement: Logging

Stdlib `logging`. No credentials or policy keys in log lines. Overlay URLs
at INFO SHALL be LAN paths or omitted. ASCII banner MAY show on a TTY
unless `--quiet`.

### Requirement: Named clip model

Clips SHALL be a named structure (`GoalClip` / dataclass), not parallel
dicts plus 6-tuples. `queuedVideos` SHALL be drained after resolve. Played
collections SHALL be sets (or bounded).

#### Scenario: Unpack for play

- GIVEN a resolved clip
- WHEN play starts
- THEN title on the card is the highlight title, not Brightcove long description
  unless that field is explicitly chosen
- AND duration is milliseconds until formatted for display

### Requirement: Package layout (target)

A later refactor MAY split:

```
src/pygoals/
  __main__.py
  config.py
  nhl_api.py
  brightcove.py
  cards.py
  chromecast.py
  main.py
```

The first milestones MAY stay in one file if secrets, quit, and ingest
guards land. Split when tests need seams.
