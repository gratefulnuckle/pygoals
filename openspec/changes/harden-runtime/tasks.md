# Tasks: harden-runtime

## 1. Secrets and paths

- [x] 1.1 Read `BRIGHTCOVE_PK` from env; fail with exit 2 if missing
- [x] 1.2 Imgur path removed (LAN HTTP cards)
- [x] 1.3 Card output via tempfile / `--overlay-path`
- [x] 1.4 Add `.gitignore` for `.env` and overlay PNGs
- [x] 1.5 Add `requirements.txt` (requests, pychromecast, zeroconf, Pillow)

## 2. Ingest guards

- [x] 2.1 Initialize `player_id` / `team` to `None` per item; skip if missing
- [x] 2.2 Stop using `statsEventId` default `0`; fall back to Brightcove id
- [x] 2.3 `timeout=` on every `requests.get`; catch and log, keep the loop alive
- [x] 2.4 If `sources` is empty, skip; prefer `container`/`src` ending `.mp4`

## 3. Shutdown

- [x] 3.1 Keep the Zeroconf/browser used for discovery on `self`; close those
- [x] 3.2 `signal.signal` SIGINT/SIGTERM → shutdown, `quit_app`, stop discovery
- [x] 3.3 Event loop instead of unreachable `while True` + non-daemon Timers
- [x] 3.4 pynput removed; SIGINT is enough

## 4. Verify

- [x] 4.1 `python pygoals.py --help`
- [x] 4.2 Missing `BRIGHTCOVE_PK` exits 2
- [x] 4.3 Fixture compilation does not raise UnboundLocalError
