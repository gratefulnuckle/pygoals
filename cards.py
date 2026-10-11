"""Player cards (1280x720 PNG): team colors, headshot, wrapped title, logo.

Each card gets a unique file name so the Chromecast never shows a cached card
for a different goal; ``cleanup_cards`` removes old ones.
"""

import io
import os
import shutil
import subprocess
import sys
import threading
import logging
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from http_util import get_bytes, get_json
from team_theme import accent_on_dark, canonical_team, espn_slug, lookup_theme, text_color_for

log = logging.getLogger(__name__)

PLAYER_URL = "https://api-web.nhle.com/v1/player/{}/landing"
LOGO_URL = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nhl/500/{}.png"
WIDTH, HEIGHT = 1280, 720
SPLIT = int(HEIGHT * 0.6)
TITLE_MAX_LINES = 3
TITLE_MARGIN = 60


def _font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
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


def _text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(draw, text, font, max_width, max_lines=TITLE_MAX_LINES):
    """Greedy word wrap; the last line is ellipsized if the text overflows."""
    words = (text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        # A single word wider than the line: hard-cut it.
        while _text_width(draw, current, font) > max_width and len(current) > 1:
            cut = len(current) - 1
            while cut > 1 and _text_width(draw, current[:cut], font) > max_width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        last = kept[-1]
        while last and _text_width(draw, last + "\u2026", font) > max_width:
            last = last[:-1].rstrip()
        kept[-1] = last + "\u2026"
        lines = kept
    return lines


_info_cache = {}
_info_lock = threading.Lock()


def _localized(value):
    if isinstance(value, dict):
        return str(value.get("default") or next(iter(value.values()), "") or "")
    return str(value or "")


def player_info(player_id, http_get_json=None):
    """Name, number, position and headshot URL from the NHL landing API (cached)."""
    if not player_id:
        return {}
    key = str(player_id)
    with _info_lock:
        if key in _info_cache:
            return dict(_info_cache[key])
    info = {}
    try:
        landing = (http_get_json or get_json)(PLAYER_URL.format(key))
        name = " ".join(p for p in (_localized(landing.get("firstName")), _localized(landing.get("lastName"))) if p)
        info = {
            "player": name,
            "number": str(landing.get("sweaterNumber") or ""),
            "position": str(landing.get("position") or ""),
            "headshot": str(landing.get("headshot") or ""),
        }
    except Exception:  # noqa: BLE001 - the receiver falls back to the title
        log.debug("player info for %s unavailable", key, exc_info=True)
        return {}
    with _info_lock:
        _info_cache[key] = info
    return dict(info)


def receiver_card(clip, card_seconds=3.0, http_get_json=None, lower_seconds=0):
    """``customData.pygoals`` for the pygoals Cast receiver (HTML card overlay)."""
    team = getattr(clip, "team", None)
    theme = lookup_theme(team)
    primary, secondary = theme["primary"], theme["secondary"]
    payload = {
        "v": 1,
        "title": getattr(clip, "title", "") or "",
        "team": canonical_team(team) or "",
        "teamName": canonical_team(team) or "",
        "primary": primary,
        "secondary": secondary,
        "text": text_color_for(primary),
        "accent": accent_on_dark(team),
        "logo": LOGO_URL.format(espn_slug(team)) if team else "",
        "cardSeconds": round(max(0.0, float(card_seconds or 0)), 1),
        "lowerSeconds": round(max(0.0, float(lower_seconds or 0)), 1),
    }
    payload.update(player_info(getattr(clip, "player_id", None), http_get_json=http_get_json))
    return payload


def fetch_player_art(player_id, team, http_get_json=None, http_get_bytes=None):
    """(headshot RGBA or None, logo RGBA or None) for cards and the media bar."""
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
    logo = _fetch_image(LOGO_URL.format(espn_slug(team)), getter_bytes) if team else None
    return headshot, logo


def render_card(player_id, team, title, out_dir=None, http_get_json=None, http_get_bytes=None):
    theme = lookup_theme(team)
    background = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(background)
    draw.rectangle([0, 0, WIDTH, SPLIT], fill=theme["primary"])
    draw.rectangle([0, SPLIT, WIDTH, HEIGHT], fill=theme["secondary"])

    headshot, logo = fetch_player_art(player_id, team, http_get_json, http_get_bytes)

    if headshot is not None:
        headshot = headshot.resize((300, 300))
        mask = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 300, 300), fill=255)
        headshot.putalpha(mask)
        ring = Image.new("RGBA", (312, 312), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, 311, 311), fill=theme["secondary"])
        ring.paste(headshot, (6, 6), headshot)
        pos = ((WIDTH - 312) // 2, (HEIGHT // 3) - 156)
        background.paste(ring, pos, ring)

    font = _font(32)
    draw = ImageDraw.Draw(background)
    lines = wrap_text(draw, title or "", font, WIDTH - 2 * TITLE_MARGIN)
    fill = text_color_for(theme["secondary"])
    y = SPLIT + 18
    line_height = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_height = max(line_height, bbox[3] - bbox[1])
        draw.text(((WIDTH - line_w) // 2, y), line, font=font, fill=fill)
        y += (bbox[3] - bbox[1]) + 10

    if logo is not None:
        top = y + 8
        size = min(200, HEIGHT - 16 - top)
        if size >= 60:
            logo = logo.resize((size, size))
            background.paste(logo, ((WIDTH - size) // 2, top), logo)

    folder = Path(out_dir or tempfile.mkdtemp(prefix="pygoals-"))
    folder.mkdir(parents=True, exist_ok=True)
    safe_player = "".join(ch for ch in str(player_id or "unknown") if ch.isalnum()) or "unknown"
    path = folder / "card-{}-{}.png".format(safe_player, uuid.uuid4().hex[:10])
    background.save(path)
    return path


class CardVideoUnavailable(RuntimeError):
    """No ffmpeg to turn a card into a video."""


def ffmpeg_exe():
    """ffmpeg from imageio-ffmpeg (bundled binary) or PATH; None if neither."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:  # noqa: BLE001 - not installed / no binary for this platform
        pass
    return shutil.which("ffmpeg")


def card_video(png_path, seconds=4.0, out_path=None, exe=None, run=None):
    """Encode a card PNG into a short silent 1080p H.264/AAC MP4.

    The Chromecast plays card video -> goal video back to back in one receiver
    session; image -> video freezes some Google TV devices.
    """
    exe = exe or ffmpeg_exe()
    if not exe:
        raise CardVideoUnavailable("ffmpeg not found (pip install imageio-ffmpeg)")
    png_path = Path(png_path)
    out_path = Path(out_path) if out_path else png_path.with_suffix(".mp4")
    seconds = "{:.2f}".format(max(1.0, float(seconds)))
    tmp = out_path.with_name(out_path.stem + ".part.mp4")
    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", seconds, "-i", str(png_path),
        "-f", "lavfi", "-t", seconds, "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "veryfast",
        "-tune", "stillimage", "-crf", "20", "-g", "30",
        "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", str(tmp),
    ]
    runner = run or subprocess.run
    kwargs = {"check": True, "capture_output": True, "timeout": 60}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW (pythonw)
    try:
        runner(cmd, **kwargs)
        os.replace(tmp, out_path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError("ffmpeg failed: {}".format(detail)) from None
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return out_path


def cleanup_cards(out_dir, keep=()):
    """Delete card-*.png/.mp4 in ``out_dir`` except the names in ``keep``."""
    keep_names = {Path(k).name for k in keep if k}
    removed = 0
    paths = list(Path(out_dir).glob("card-*.png")) + list(Path(out_dir).glob("card-*.mp4"))
    for path in paths:
        if path.name in keep_names:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            log.debug("could not delete %s", path, exc_info=True)
    return removed


def idle_card(out_dir=None):
    folder = Path(out_dir or tempfile.mkdtemp(prefix="pygoals-"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "idle.png"
    img = Image.new("RGB", (WIDTH, HEIGHT), "#041E42")
    draw = ImageDraw.Draw(img)
    font = _font(40)
    text = "pygoals \u2014 waiting for goals"
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 340), text, font=font, fill="white")
    img.save(path)
    return path
