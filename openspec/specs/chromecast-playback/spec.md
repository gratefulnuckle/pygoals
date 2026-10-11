# chromecast-playback

## Purpose

Select a Cast device, play card then clip, advance on finished media, and
shut down without leaking discovery or the receiver app.

## Requirements

### Requirement: Device selection

The app SHALL discover devices via pychromecast/zeroconf, honoring
`--known-host`. The user SHALL select by `--device` name substring or a
validated index. `int(input)` without range checks is non-compliant.
`--list-devices` SHALL print and exit 0.

#### Scenario: Named device

- GIVEN `--device "Living Room"`
- WHEN discovery returns matching casts
- THEN that device is used
- AND stdin is not required

#### Scenario: Bad index

- GIVEN interactive picker and the user types `n`
- WHEN selection is parsed
- THEN the app re-prompts or exits 2
- AND it does not raise `ValueError` uncaught

### Requirement: Single discovery owner

The player SHALL own one Zeroconf instance and the discovery browser.
Shutdown SHALL call `stop_discovery()` and `zeroconf.close()` on **that**
instance.

#### Scenario: Quit

- GIVEN discovery is running
- WHEN graceful shutdown runs
- THEN the browser is stopped
- AND the Zeroconf used for `get_chromecasts` is closed
- AND a second unused Zeroconf is not what gets closed

### Requirement: Card then video, no overlap

The app SHALL wait until the Cast is ready, show the player card, then play
the MP4. Two `play_next` invocations MUST NOT overlap. Blind `sleep(5)` MAY
not be the only gate; prefer media status PLAYING on the card or a
single-shot timer started after PLAYING.

#### Scenario: Next clip while card is up

- GIVEN a card is showing
- WHEN idle flaps
- THEN the next MP4 is not started until the current item is finished or failed
- AND an in-flight flag/lock is held

### Requirement: Advance on FINISHED

Next item SHALL be driven by `MediaStatusListener` (or equivalent events).
Advance SHALL require `idle_reason == "FINISHED"` (or documented equivalent)
for the **mp4**, not the card and not the idle PNG. Polling
`player_state == 'IDLE'` every second is non-compliant.

#### Scenario: Empty queue

- GIVEN no clips left
- WHEN the receiver is idle after the idle slate
- THEN the idle image is not re-cast every second
- AND the app waits for the next ingest poll

#### Scenario: Load error

- GIVEN the MP4 fails to load
- WHEN status becomes IDLE with an error/cancel reason
- THEN the app logs failure and MAY skip
- AND it does not treat it identically to a clean finish without logging

### Requirement: Thread-safe queue

Pending clips SHALL live in a queue or a list plus lock. Fetch and play
MUST NOT append/pop the same unlocked list.

#### Scenario: Poll during play

- GIVEN the 60s fetch resolves a new MP4
- WHEN `play_next` pops the current head
- THEN no skip/duplicate/exception from concurrent mutation

### Requirement: Graceful shutdown

Ctrl+C and a documented quit chord SHALL cancel timers, `quit_app` /
disconnect the Cast, and stop discovery. `sys.exit` from a pynput callback
is not sufficient. After the listener stops, the process SHALL exit — no
`while True: sleep(1)` with non-daemon timers.

#### Scenario: SIGINT

- GIVEN clips are playing
- WHEN the user presses Ctrl+C in the terminal
- THEN timers are cancelled
- AND the receiver app quits
- AND the process exits with 130 or 0
- AND the user does not have to kill python in Task Manager

### Requirement: Reset is explicit

A playlist reset SHALL be a bound control (CLI or key) or SHALL be deleted.
If present, it MUST take the same lock as play/fetch and MUST NOT stack a
second `play_next` on the idle path.

#### Scenario: Reset during play

- GIVEN a clip is playing
- WHEN reset runs
- THEN queues are cleared
- AND one (not two) subsequent play starts after re-resolve
