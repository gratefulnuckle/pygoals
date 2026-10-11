# pygoals receiver

Google Cast Web Receiver (CAF v3) for [pygoals](https://github.com/gratefulnuckle/pygoals):
plays NHL goal videos and draws the player card as an HTML overlay, so there is no
gap between card and goal.

Live at https://gratefulnuckle.github.io/pygoals-receiver/ (GitHub Pages, `main` / root).
Static files only: `index.html`, `receiver.css`, `receiver.js`.

The source of truth is `receiver/` in the pygoals repo; this repo is a published mirror.

## Media item contract

Senders LOAD a goal with `media.customData.pygoals`:

| key | meaning |
| --- | --- |
| `title` | clip title |
| `player`, `number`, `position` | scorer name, sweater number, position |
| `team`, `teamName` | team abbreviation and display name |
| `primary`, `secondary`, `text`, `accent` | team colours (CSS colours) |
| `headshot`, `logo` | image URLs |
| `cardSeconds` | seconds of playback the full card stays up (default 3) |
| `lowerSeconds` | seconds the lower third stays after that (default 8; 0 = none) |

The full card appears as soon as the LOAD/QUEUE_LOAD arrives (it covers buffering),
stays for `cardSeconds` of playback, then collapses to a lower third. Without
`customData` the receiver falls back to `metadata.title` / `subtitle` / `images`.
Nothing queued for a few seconds brings back the idle screen. No custom namespace.

## Registering

The Cast app (ID `A7C76189`) is unpublished, so it only runs on devices registered
as test devices in the Google Cast SDK Developer Console (serial number, then
about 15 minutes and a device reboot).
