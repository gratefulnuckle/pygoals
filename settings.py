"""settings.ini: load, validate, save (configparser), with defaults.

Precedence (highest first): CLI flags > environment / .env > settings.ini >
built-in defaults. Only the Brightcove key and a few PYGOALS_* variables are
read from the environment; see ``ENV_OVERRIDES``.
"""

from __future__ import annotations

import configparser
import io
import logging
import math
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from config import atomic_write_text, settings_path

log = logging.getLogger(__name__)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MIN_POLL_SECONDS = 5.0
MIN_HEIGHT = 240
MAX_HEIGHT = 2160
MAX_POLL_SECONDS = 3600.0


@dataclass
class Settings:
    # [brightcove]
    policy_key: str = ""
    # [device]
    device_name: str = ""
    device_uuid: str = ""
    device_host: str = ""
    known_hosts: list = field(default_factory=list)
    # [playback]
    poll_seconds: float = 60.0
    card_seconds: float = 4.0
    max_height: int = 1080
    quality: str = "auto"
    card_mode: str = "video"
    remember_seen: bool = True
    # [cast]
    receiver_mode: str = "auto"
    receiver_app_id: str = ""
    # [server]
    port: int = 8765
    # [ui]
    snap_to_tray: bool = True
    bar_x: int | None = None
    bar_y: int | None = None
    show_bar_on_start: bool = True
    # [notifications]
    notify_goals: bool = True
    notify_errors: bool = True
    toast_seconds: float = 6.0
    # [logging]
    log_level: str = "INFO"
    log_to_file: bool = True

    @property
    def bar_position(self):
        if self.bar_x is None or self.bar_y is None:
            return None
        return (self.bar_x, self.bar_y)

    @property
    def show_cards(self):
        return self.card_mode != "off"

    def copy(self, **changes):
        return replace(self, known_hosts=list(self.known_hosts), **changes)


# (section, option, attribute, kind)
SCHEMA = (
    ("brightcove", "policy_key", "policy_key", "str"),
    ("device", "name", "device_name", "str"),
    ("device", "uuid", "device_uuid", "str"),
    ("device", "host", "device_host", "str"),
    ("device", "known_hosts", "known_hosts", "hosts"),
    ("playback", "poll_seconds", "poll_seconds", "poll"),
    ("playback", "card_seconds", "card_seconds", "card"),
    ("playback", "quality", "quality", "quality"),
    ("playback", "max_height", "max_height", "height"),
    ("playback", "card_mode", "card_mode", "cardmode"),
    ("playback", "remember_seen", "remember_seen", "bool"),
    ("cast", "receiver_mode", "receiver_mode", "recvmode"),
    ("cast", "receiver_app_id", "receiver_app_id", "appid"),
    ("server", "port", "port", "port"),
    ("ui", "snap_to_tray", "snap_to_tray", "bool"),
    ("ui", "bar_x", "bar_x", "optint"),
    ("ui", "bar_y", "bar_y", "optint"),
    ("ui", "show_bar_on_start", "show_bar_on_start", "bool"),
    ("notifications", "goals", "notify_goals", "bool"),
    ("notifications", "errors", "notify_errors", "bool"),
    ("notifications", "toast_seconds", "toast_seconds", "toast"),
    ("logging", "level", "log_level", "level"),
    ("logging", "to_file", "log_to_file", "bool"),
)

COMMENTS = {
    "brightcove": "Brightcove player policy key. BRIGHTCOVE_PK in the environment or .env overrides this.",
    "device": "Active Chromecast. Set from the Devices page; uuid is matched first, then name, then host.",
    "playback": "poll_seconds: 5-3600. card_mode: video (card plays as a short clip right before the goal, seamless), image (still card; the receiver restarts before the goal) or off. card_seconds: 0-30 (video cards last at least 1 s). quality: auto, hls:<height>, mp4:<height> or hls:adaptive (pick it in Settings). max_height: cap for auto, 240-2160.",
    "cast": ("Which Cast receiver plays the goals. receiver_mode: auto (pygoals receiver if receiver_app_id is set "
             "and it launches, else the default receiver), custom (always the pygoals receiver) or default. "
             "receiver_app_id: 8-character Cast app ID, e.g. A7C76189 (unpublished apps only run on registered test devices)."),
    "server": "LAN port the TV fetches player cards from. Keep it fixed (default 8765) so one firewall rule covers it; 0 = random port each run.",
    "ui": "Media bar position. snap_to_tray = true ignores bar_x/bar_y and anchors above the tray icon.",
    "notifications": "Dark toast notifications above the tray. toast_seconds: 2-60.",
    "logging": "level: DEBUG, INFO, WARNING or ERROR. Logs go to ./logs/pygoals.log.",
}

ENV_OVERRIDES = {
    "BRIGHTCOVE_PK": "policy_key",
    "PYGOALS_DEVICE": "device_name",
    "PYGOALS_KNOWN_HOSTS": "known_hosts",
    "PYGOALS_POLL_SECONDS": "poll_seconds",
    "PYGOALS_PORT": "port",
    "PYGOALS_MAX_HEIGHT": "max_height",
    "PYGOALS_QUALITY": "quality",
    "PYGOALS_RECEIVER_MODE": "receiver_mode",
    "PYGOALS_RECEIVER_APP_ID": "receiver_app_id",
    "PYGOALS_LOG_LEVEL": "log_level",
}

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,252})$|^[0-9A-Fa-f:]+$")
_QUALITY_RE = re.compile(r"^(auto|hls:adaptive|(hls|mp4):[0-9]{3,4})$")
CARD_MODES = ("video", "image", "off")
RECEIVER_MODES = ("auto", "custom", "default")
_APP_ID_RE = re.compile(r"^[0-9A-Z]{8}$")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class SettingsError(ValueError):
    def __init__(self, errors):
        self.errors = dict(errors)
        super().__init__("; ".join("{}: {}".format(k, v) for k, v in self.errors.items()))


def _convert(kind, raw):
    """Convert a raw string to the typed value or raise ValueError(message)."""
    text = "" if raw is None else str(raw).strip()
    if kind == "str":
        return text
    if kind in ("list", "hosts"):
        items = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
        if kind == "hosts":
            bad = [item for item in items if not _HOST_RE.match(item)]
            if bad:
                raise ValueError("not an IP or host name: " + ", ".join(bad))
        return items
    if kind == "bool":
        lowered = text.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError("expected true/false")
    if kind == "optint":
        if text == "":
            return None
        try:
            return int(float(text))
        except ValueError:
            raise ValueError("expected a whole number or blank") from None
    if kind == "port":
        try:
            value = int(text or "0")
        except ValueError:
            raise ValueError("expected a whole number 0-65535") from None
        if not 0 <= value <= 65535:
            raise ValueError("must be 0-65535")
        return value
    if kind == "recvmode":
        value = (text or "auto").lower()
        if value not in RECEIVER_MODES:
            raise ValueError("must be one of " + ", ".join(RECEIVER_MODES))
        return value
    if kind == "appid":
        value = text.upper()
        if value and not _APP_ID_RE.match(value):
            raise ValueError("expected an 8-character Cast app ID (letters/digits) or blank")
        return value
    if kind == "cardmode":
        value = (text or "video").lower()
        if value not in CARD_MODES:
            raise ValueError("must be one of " + ", ".join(CARD_MODES))
        return value
    if kind == "quality":
        value = (text or "auto").lower()
        if not _QUALITY_RE.match(value):
            raise ValueError("expected auto, hls:<height>, mp4:<height> or hls:adaptive")
        return value
    if kind == "height":
        try:
            value = int(float(text or "1080"))
        except ValueError:
            raise ValueError("expected a whole number 240-2160") from None
        if not MIN_HEIGHT <= value <= MAX_HEIGHT:
            raise ValueError("must be {}-{}".format(MIN_HEIGHT, MAX_HEIGHT))
        return value
    if kind == "level":
        upper = (text or "INFO").upper()
        if upper not in LOG_LEVELS:
            raise ValueError("must be one of " + ", ".join(LOG_LEVELS))
        return upper
    bounds = {
        "poll": (MIN_POLL_SECONDS, MAX_POLL_SECONDS),
        "card": (0.0, 30.0),
        "toast": (2.0, 60.0),
    }
    if kind in bounds:
        low, high = bounds[kind]
        try:
            value = float(text)
        except ValueError:
            raise ValueError("expected a number") from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError("must be between {:g} and {:g}".format(low, high))
        return value
    raise ValueError("unknown kind " + kind)


def _format(kind, value):
    if kind in ("list", "hosts"):
        return ", ".join(value or [])
    if kind == "bool":
        return "true" if value else "false"
    if kind == "optint":
        return "" if value is None else str(int(value))
    if kind in ("poll", "card", "toast"):
        return "{:g}".format(float(value))
    return "" if value is None else str(value)


def _kind_of(attr):
    for _section, _option, name, kind in SCHEMA:
        if name == attr:
            return kind
    raise KeyError(attr)


def validate_values(values, base=None):
    """Validate ``{attribute: raw string}`` and return a new Settings.

    Raises SettingsError with every bad field. Unknown keys are rejected.
    """
    result = (base or Settings()).copy()
    errors = {}
    known = {name for *_rest, name, _kind in SCHEMA}
    for attr, raw in values.items():
        if attr not in known:
            errors[attr] = "unknown setting"
            continue
        try:
            setattr(result, attr, _convert(_kind_of(attr), raw))
        except ValueError as exc:
            errors[attr] = str(exc)
    if errors:
        raise SettingsError(errors)
    return result


def as_strings(settings):
    """``{attribute: string}`` view, the inverse of ``validate_values``."""
    return {name: _format(kind, getattr(settings, name)) for _s, _o, name, kind in SCHEMA}


def from_parser(parser):
    """Read a ConfigParser leniently: bad values are logged and defaulted."""
    result = Settings()
    problems = {}
    for section, option, attr, kind in SCHEMA:
        if not parser.has_option(section, option):
            continue
        try:
            setattr(result, attr, _convert(kind, parser.get(section, option, raw=True)))
        except ValueError as exc:
            problems["{}.{}".format(section, option)] = str(exc)
    # Older files: [playback] show_cards = false meant no cards.
    if not parser.has_option("playback", "card_mode") and parser.has_option("playback", "show_cards"):
        try:
            if not _convert("bool", parser.get("playback", "show_cards", raw=True)):
                result.card_mode = "off"
        except ValueError:
            pass
    for key, message in problems.items():
        log.warning("settings.ini %s ignored: %s", key, message)
    return result, problems


def to_text(settings):
    parser = configparser.ConfigParser(interpolation=None)
    sections = []
    for section, option, attr, kind in SCHEMA:
        if section not in sections:
            sections.append(section)
            parser.add_section(section)
        parser.set(section, option, _format(kind, getattr(settings, attr)))
    buffer = io.StringIO()
    buffer.write("# pygoals settings. Edit here or from the tray: Settings.\n")
    buffer.write("# Precedence: command-line flags > environment/.env > this file > defaults.\n\n")
    for section in sections:
        if section in COMMENTS:
            buffer.write("# {}\n".format(COMMENTS[section]))
        single = configparser.ConfigParser(interpolation=None)
        single.add_section(section)
        for option, value in parser.items(section, raw=True):
            single.set(section, option, value)
        single.write(buffer)
    return buffer.getvalue()


def load(path=None, create=True):
    """Load settings.ini (creating it with defaults if missing)."""
    path = Path(path) if path else settings_path()
    parser = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        try:
            parser.read(path, encoding="utf-8-sig")
        except (configparser.Error, OSError) as exc:
            log.error("could not parse %s (%s); using defaults", path, exc)
            return Settings()
        settings, _problems = from_parser(parser)
        return settings
    settings = Settings()
    if create:
        try:
            save(settings, path)
            log.info("created %s with defaults", path)
        except OSError as exc:
            log.warning("could not create %s: %s", path, exc)
    return settings


def save(settings, path=None):
    path = Path(path) if path else settings_path()
    atomic_write_text(path, to_text(settings))
    return path


def env_overrides(environ=None):
    """Typed values from the environment that override settings.ini."""
    environ = os.environ if environ is None else environ
    out = {}
    for var, attr in ENV_OVERRIDES.items():
        raw = environ.get(var, "")
        if not str(raw).strip():
            continue
        try:
            out[attr] = _convert(_kind_of(attr), raw)
        except ValueError as exc:
            log.warning("%s ignored: %s", var, exc)
    return out


def effective(settings, environ=None):
    """settings.ini values with environment overrides applied."""
    result = settings.copy()
    overrides = env_overrides(environ)
    if "device_name" in overrides:
        # A device named in the environment replaces the saved one entirely.
        result.device_uuid = ""
        result.device_host = ""
    for attr, value in overrides.items():
        setattr(result, attr, value)
    return result


def key_from_environment(environ=None):
    environ = os.environ if environ is None else environ
    return bool(str(environ.get("BRIGHTCOVE_PK", "")).strip())


__all__ = [
    "Settings", "SettingsError", "load", "save", "validate_values", "as_strings",
    "effective", "env_overrides", "to_text", "from_parser", "key_from_environment",
    "LOG_LEVELS", "SCHEMA",
]
