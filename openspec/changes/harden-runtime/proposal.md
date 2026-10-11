# Proposal: Secrets, crash guards, and shutdown

## Why

The script cannot be given to another machine: credentials and a personal
path are in source, ingest crashes on compilation CMS items, and Ctrl+Q
never calls `graceful_quit`.

Closes: PYG-001, PYG-002, PYG-003, PYG-004, PYG-005, PYG-007 (guard),
PYG-008, PYG-010, PYG-012 (own the Zeroconf used for discovery), PYG-018
(deps file — README already added).

## What Changes

- Load Brightcove PK (and Imgur if still used) from environment.
- Write cards to a temp path.
- Skip items missing player/team; unique ids; HTTP timeouts; MP4 source guard.
- SIGINT + working quit: cancel timers, stop discovery, `quit_app`.
- `requirements.txt` and `.gitignore` (`.env`).

## Out of scope

- LAN HTTP replacing Imgur (phase 2)
- `MediaStatusListener` / queue lock (phase 1)
- Package split (phase 5)
- Filtering compilations beyond “skip if no player/team”

## Approach

Stay in `pygoals.py`. Add a tiny `os.environ` config at the top. Do not
paste rotated secrets into the repo.
