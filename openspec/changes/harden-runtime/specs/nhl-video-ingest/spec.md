# Delta for nhl-video-ingest

## ADDED Requirements

### Requirement: Skip incomplete CMS items

Items missing Brightcove id, player id, or team abbreviation MUST be skipped
without raising.

#### Scenario: Compilation on page 1

- GIVEN a listing item with no player extraData
- WHEN `fetch_videos` runs
- THEN no `UnboundLocalError`
- AND the scheduler is still armed
