# pygoals

```
██████╗ ██╗   ██╗ ██████╗  ██████╗  █████╗ ██╗     ███████╗
██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔═══██╗██╔══██╗██║     ██╔════╝
██████╔╝ ╚████╔╝ ██║  ███╗██║   ██║███████║██║     ███████╗
```

Cast NHL **goal highlight** clips to a Chromecast on your LAN. Before each
clip the TV can show a generated player card (headshot, team colors, title)
served from this PC — not Imgur.

**Unofficial.** Not affiliated with the NHL or Brightcove. Personal LAN use
only. Endpoints and player keys rotate.

| Docs | |
|------|--|
| Product spec | [`openspec/`](openspec/) |
| Work tracker | [`ISSUES.md`](ISSUES.md) |
| Plan | [`ROADMAP.md`](ROADMAP.md) |

---

## Setup

```text
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set BRIGHTCOVE_PK=your-player-policy-key
python pygoals.py --device "Living Room"
```

Copy `.env.example` and set `BRIGHTCOVE_PK`. Never commit the key.

### Useful flags

| Flag | Meaning |
|------|---------|
| `--dry-run` | List clips; no Cast, no PK required |
| `--list-devices` | Print Chromecasts and exit |
| `--device NAME` | Skip the numbered picker |
| `--known-host IP` | Repeatable |
| `--no-overlay` | Video only |
| `--once` | Play the current queue then quit |
| `--quiet` | No ASCII banner |
| Ctrl+C | Graceful shutdown |

Exit `2` if `BRIGHTCOVE_PK` is missing (except `--dry-run` / `--list-devices`).

---

## Layout

| Path | Role |
|------|------|
| `pygoals.py` | CLI, queue, Cast session |
| `nhl_ingest.py` | Forge listing → `GoalClip` |
| `brightcove.py` | MP4 source pick + Playback API |
| `cards.py` | 1280×720 card |
| `media_server.py` | LAN HTTP for cards |
| `team_theme.py` | Colors and ESPN slugs |
| `tests/` | Fixtures, no live Imgur |

---

## License

MIT. See [LICENSE](LICENSE).
