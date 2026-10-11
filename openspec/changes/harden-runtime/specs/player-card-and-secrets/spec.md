# Delta for player-card-and-secrets

## ADDED Requirements

### Requirement: Env-only playback key at runtime

The process MUST read the Brightcove policy key from the environment. It
MUST NOT contain a live policy key in tracked source.

#### Scenario: Missing key

- GIVEN `BRIGHTCOVE_PK` is unset
- WHEN the app starts
- THEN it exits with code 2
- AND the message names the variable, not a fallback hardcoded key
