# Design: harden-runtime

## Technical approach

Keep `NHLVideoPlayer` in one file.

- `HEADERS['accept']` built from `os.environ["BRIGHTCOVE_PK"]` at init.
- Overlay: `Path(os.environ.get("PYGOALS_OVERLAY_PATH", tempfile.gettempdir())) / "pygoals-card.png"`.
- `fetch_videos`: per-item `player_id = team = None`; skip append if either
  missing or if `brightcoveId` missing.
- `resolve_mp4_urls`: wrap HTTP; pick first/highest MP4; continue on failure.
- `main`: store `self.zeroconf` and `self.browser` from `get_chromecasts`;
  `try/finally` around the wait; `signal` handler sets an `Event`.

## Decisions

- **SIGINT over broken pynput** for this change. Global hotkeys can return later.
- **Do not rotate credentials in git.** Operator rotates in the Imgur/Brightcove
  consoles; we only stop committing them.
- **Imgur may still run** if env is set; removing it is phase 2.

## Risks

- Existing users must set `BRIGHTCOVE_PK` once. Document in README.
- Temp PNG still single-name — unique names wait for LAN HTTP (phase 2).
