# Delta for chromecast-playback

## ADDED Requirements

### Requirement: SIGINT stops the player

SIGINT MUST cancel periodic timers, stop Chromecast discovery, and quit the
receiver app.

#### Scenario: Ctrl+C during idle poll

- GIVEN timers are running
- WHEN the user sends SIGINT
- THEN the process exits
- AND non-daemon timers do not keep Python alive
