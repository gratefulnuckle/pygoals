"""Player cards. No Imgur, no hardcoded user path, RGBA-safe paste."""

import io
import logging
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from http_util import get_bytes, get_json
from team_theme import espn_slug, lookup_theme

log = logging.getLogger(__name__)

PLAYER_URL = "https://api-web.nhle.com/v1/player/{}/landing"
LOGO_URL = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nhl/500/{}.png"


def _font(size):
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _to_rgba(image):
    if image.mode != "RGBA":
        return image.convert("RGBA")
    return image


def _fetch_image(url, http_get_bytes):
    try:
        raw = http_get_bytes(url)
        return _to_rgba(Image.open(io.BytesIO(raw)))
    except Exception:
        log.debug("image fetch failed %s", url, exc_info=True)
        return None


def render_card(player_id, team, title, out_dir=None, http_get_json=None, http_get_bytes=None):
    theme = lookup_theme(team)
    width, height = 1280, 720
    background = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(background)
    draw.rectangle([0, 0, width, int(height * 0.6)], fill=theme["primary"])
    draw.rectangle([0, int(height * 0.6), width, height], fill=theme["secondary"])

    getter_json = http_get_json or get_json
    getter_bytes = http_get_bytes or get_bytes

    headshot = None
    if player_id:
        try:
            landing = getter_json(PLAYER_URL.format(player_id))
            if landing.get("headshot"):
                headshot = _fetch_image(landing["headshot"], getter_bytes)
        except Exception:
            log.debug("headshot skipped", exc_info=True)

    if headshot is not None:
        headshot = headshot.resize((300, 300))
        mask = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 300, 300), fill=255)
        headshot.putalpha(mask)
        bordered = Image.new("RGBA", (304, 304), (0, 0, 0, 0))
        bordered.paste(headshot, (2, 2), mask)
        pos = ((width - 304) // 2, (height // 3) - 152)
        background.paste(bordered, pos, bordered)

    title = title or ""
    font = _font(25)
    draw = ImageDraw.Draw(background)
    bbox = draw.textbbox((0, 0), title, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    title_pos = ((width - text_w) // 2, int(height * 0.6) + 20)
    draw.text(title_pos, title, font=font, fill=(255, 255, 255))

    logo = _fetch_image(LOGO_URL.format(espn_slug(team)), getter_bytes)
    if logo is not None:
        logo = logo.resize((200, 200))
        logo_pos = ((width - 200) // 2, title_pos[1] + text_h + 20)
        background.paste(logo, logo_pos, logo)

    folder = Path(out_dir or tempfile.mkdtemp(prefix="pygoals-"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "card-{}.png".format(player_id or "unknown")
    background.save(path)
    return path


def idle_card(out_dir=None):
    folder = Path(out_dir or tempfile.mkdtemp(prefix="pygoals-"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "idle.png"
    img = Image.new("RGB", (1280, 720), "#041E42")
    draw = ImageDraw.Draw(img)
    font = _font(40)
    text = "pygoals — waiting for goals"
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((1280 - (bbox[2] - bbox[0])) // 2, 340), text, font=font, fill="white")
    img.save(path)
    return path
