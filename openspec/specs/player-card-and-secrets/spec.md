# player-card-and-secrets

## Purpose

Build a 1280×720 goal card and get it onto Chromecast without public uploads
or committed credentials.

## Requirements

### Requirement: No secrets in source

Brightcove policy key and any Imgur credentials SHALL come from environment
or a gitignored file. Missing Imgur credentials MUST NOT be required if
local media serving is used. `.env.example` SHALL contain empty placeholders
only.

#### Scenario: Fresh clone

- GIVEN a git checkout with no `.env`
- WHEN someone greps the repo for client secrets
- THEN no live Imgur secret or Brightcove PK is in tracked files
- AND README names the env vars, not the values

### Requirement: Cards are not public by default

Player cards and idle/boot art MUST NOT be uploaded to a public host by
default. Chromecast SHALL GET `http://<lan-ip>:<port>/...`. `file://` and
`http://127.0.0.1` are non-compliant for Cast.

#### Scenario: Goal card on TV

- GIVEN a resolved clip
- WHEN the card is shown
- THEN the Cast device HTTP-GETs a LAN URL
- AND no anonymous Imgur upload occurs
- AND INFO logs do not print a public CDN URL of the player

### Requirement: Portable output

Card bytes SHALL be a unique temp path or in-memory buffer served by the
HTTP handler. A hardcoded user home path is non-compliant.

#### Scenario: Another Windows user

- GIVEN the app runs as a different user
- WHEN a card is generated
- THEN it writes under temp or a configured overlay dir
- AND `C:/Users/jonat/image.png` is not referenced

### Requirement: Card composition

The card SHALL use team primary (~top 60%) and secondary (~bottom 40%), a
circular NHL headshot with a ring, wrapped contrast-safe title, and a team
logo. Team identity SHALL load from config (colors, ESPN slug, NHL abbrev),
not only inline conditionals. Unknown team → default theme.

#### Scenario: RGB ESPN logo

- GIVEN a logo without alpha
- WHEN compositing
- THEN the image is converted to RGBA
- AND paste does not raise `ValueError: bad transparency mask`

#### Scenario: Missing arial.ttf

- GIVEN a non-Windows host or missing Arial
- WHEN drawing the title
- THEN a bundled TTF or PIL default is used
- AND the card is still produced

### Requirement: Recoverable asset fetch

Headshot, logo, and player-landing HTTP SHALL use timeouts. Non-image /
non-200 SHALL skip that layer and still produce a card.

#### Scenario: Headshot 404

- GIVEN player landing has no headshot
- WHEN `create_image` runs
- THEN the card still has colors, title, and (if possible) logo
- AND play continues

### Requirement: Optional public host

If a third-party image host remains, it SHALL be opt-in, credentials env-only,
and uploads explicit. The default path SHALL be local serve.

#### Scenario: `--no-overlay`

- GIVEN overlay is disabled
- WHEN a clip plays
- THEN Cast loads the MP4 only
- AND no card HTTP or Imgur call is made
