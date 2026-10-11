"""Portable paths, .env loading, logging setup and small atomic JSON state.

Everything pygoals writes lives next to the app (the script directory, or the
directory of the frozen executable): ``settings.ini``, ``logs/`` and
``state.json``. Nothing is written to AppData. ``PYGOALS_HOME`` overrides the
directory (used by tests).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import tempfile
import time
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(levelname)s %(message)s"


def app_dir() -> Path:
    override = os.environ.get("PYGOALS_HOME")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path() -> Path:
    return app_dir() / "settings.ini"


def state_path() -> Path:
    return app_dir() / "state.json"


def log_dir() -> Path:
    return app_dir() / "logs"


def log_path() -> Path:
    return log_dir() / "pygoals.log"


def parse_dotenv(text):
    """Parse KEY=VALUE lines. Supports comments, ``export``, and quotes."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_dotenv(path=None, override=False):
    """Load ``.env`` (next to the app by default) into ``os.environ``.

    Existing environment variables win unless ``override`` is true. Empty
    values never clobber anything, so the blank ``.env.example`` is harmless.
    """
    path = Path(path) if path else app_dir() / ".env"
    if not path.is_file():
        return {}
    try:
        values = parse_dotenv(path.read_text(encoding="utf-8-sig"))
    except OSError:
        logging.getLogger(__name__).warning("could not read %s", path)
        return {}
    applied = {}
    for key, value in values.items():
        if value == "":
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value
            applied[key] = value
    return applied


class Utf8RotatingFileHandler(logging.handlers.RotatingFileHandler):
    """UTF-8 log file that starts with a BOM, so Notepad and Windows
    PowerShell 5 (Get-Content) show curly quotes and accents correctly."""

    def __init__(self, filename, **kwargs):
        kwargs["encoding"] = "utf-8"
        super().__init__(filename, **kwargs)
        try:
            if self.stream is not None and self.stream.tell() > 0 and not _has_bom(self.baseFilename):
                self.doRollover()  # older BOM-less log: start a fresh file
        except OSError:
            pass

    def _open(self):
        stream = super()._open()
        try:
            if stream.tell() == 0:
                stream.write("\ufeff")
        except OSError:
            pass
        return stream


def _has_bom(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(3) == b"\xef\xbb\xbf"
    except OSError:
        return False


def setup_logging(level="INFO", to_file=True, path=None):
    """Console logging when a console exists, plus a rotating file in ./logs."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_pygoals", False):  # only replace our own handlers
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(numeric)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        console._pygoals = True
        root.addHandler(console)
    written = None
    if to_file:
        target = Path(path) if path else log_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = Utf8RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3)
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
            handler._pygoals = True
            root.addHandler(handler)
            written = target
        except OSError as exc:
            logging.getLogger(__name__).warning("file logging disabled: %s", exc)
    # pychromecast/zeroconf are chatty at INFO.
    for noisy in ("pychromecast", "zeroconf", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.WARNING))
    return written


def set_log_level(level):
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logging.getLogger().setLevel(numeric)


def atomic_write_text(path, text):
    """Write via a temp file in the same directory, then ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace_with_retry(src, dst, attempts=20, delay=0.05):
    """``os.replace`` that tolerates Windows sharing violations.

    Antivirus/indexers briefly open freshly written files, which makes the
    rename fail with PermissionError (WinError 5/32). Retry for ~1 s.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
