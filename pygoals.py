"""pygoals: NHL goal highlights on a Chromecast, from the system tray.

Run with no arguments to start the tray app; everything else comes from
``settings.ini`` next to the app. Flags are optional overrides. ``--cli``,
``--dry-run``, ``--list-devices`` and ``--once`` run in the console.
"""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import threading

import requests

import settings as settings_mod
from _version import __version__
from brightcove import policy_key, set_policy_key
from clip_queue import SeenStore
from config import load_dotenv, settings_path, setup_logging, state_path
from player import (  # noqa: F401  (re-exported for callers/tests)
    VIDEO_URL, NHLVideoPlayer, PlayerOptions, match_device,
)

log = logging.getLogger("pygoals")

BANNER = r"""
 ____  _   _  ____  ___    _    _     ____
|  _ \| | | |/ ___|/ _ \  / \  | |   / ___|
| |_) | |_| | |  _| | | |/ _ \ | |   \___ \
|  __/ \__, | |_| | |_| / ___ \| |___ ___) |
|_|    |___/ \____|\___/_/   \_\_____|____/
version {} - unofficial. LAN Chromecast only.
""".format(__version__)


def _poll_seconds(raw):
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number") from None
    if not math.isfinite(value) or not settings_mod.MIN_POLL_SECONDS <= value <= settings_mod.MAX_POLL_SECONDS:
        raise argparse.ArgumentTypeError("must be between {:g} and {:g} seconds".format(
            settings_mod.MIN_POLL_SECONDS, settings_mod.MAX_POLL_SECONDS))
    return value


def _port(raw):
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("must be 0-65535")
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pygoals",
        description="Cast NHL goal highlights on your LAN. No arguments: start the tray app "
                    "using settings.ini. Flags override settings for this run only.",
    )
    mode = parser.add_argument_group("mode")
    mode.add_argument("--cli", "--no-tray", dest="cli", action="store_true",
                      help="console mode instead of the tray")
    mode.add_argument("--tray", action="store_true", help="tray mode (the default; accepted for compatibility)")
    mode.add_argument("--dry-run", action="store_true", help="list clips; no Cast, no key required")
    mode.add_argument("--list-devices", action="store_true", help="print Chromecasts and exit")
    mode.add_argument("--once", action="store_true", help="play the current queue, then quit")
    parser.add_argument("--device", default=None, help="Chromecast friendly-name substring")
    parser.add_argument("--known-host", action="append", default=None, help="Chromecast IP, repeatable")
    parser.add_argument("--poll-seconds", type=_poll_seconds, default=None)
    parser.add_argument("--port", type=_port, default=None, help="card server port (0 = any)")
    parser.add_argument("--overlay-path", default=None, help="directory for card PNGs")
    parser.add_argument("--no-overlay", action="store_true", help="video only, no player cards")
    parser.add_argument("--config", default=None, help="settings.ini path (default: next to the app)")
    parser.add_argument("--log-level", default=None, type=str.upper, choices=settings_mod.LOG_LEVELS)
    parser.add_argument("--no-log-file", action="store_true", help="do not write logs/pygoals.log")
    parser.add_argument("--forget-seen", action="store_true", help="ignore and do not write state.json")
    parser.add_argument("--quiet", action="store_true", help="no ASCII banner")
    parser.add_argument("--version", action="store_true")
    return parser


class Runtime:
    """Stored settings + environment + CLI overrides, and the player factory."""

    def __init__(self, args, stored, path, log_file=None):
        self.args = args
        self.stored = stored
        self.settings_path = path
        self.log_file = log_file
        self.cli_overrides = self._cli_overrides(args)

    @staticmethod
    def _cli_overrides(args):
        out = {}
        if args.device:
            out.update(device_name=args.device, device_uuid="", device_host="")
        if args.known_host:
            out["known_hosts"] = list(args.known_host)
        if args.poll_seconds is not None:
            out["poll_seconds"] = args.poll_seconds
        if args.port is not None:
            out["port"] = args.port
        if args.no_overlay:
            out["card_mode"] = "off"
        if args.log_level:
            out["log_level"] = args.log_level
        if args.no_log_file:
            out["log_to_file"] = False
        if args.forget_seen or args.dry_run:
            out["remember_seen"] = False
        return out

    def effective(self):
        eff = settings_mod.effective(self.stored)
        for attr, value in self.cli_overrides.items():
            setattr(eff, attr, value)
        return eff

    def options(self):
        eff = self.effective()
        return PlayerOptions(
            poll_seconds=eff.poll_seconds,
            card_seconds=eff.card_seconds,
            max_height=eff.max_height,
            quality=eff.quality,
            show_cards=eff.show_cards,
            card_mode=eff.card_mode,
            receiver_mode=eff.receiver_mode,
            receiver_app_id=eff.receiver_app_id,
            video_overlay=eff.video_overlay,
            port=eff.port,
            known_hosts=list(eff.known_hosts),
            overlay_path=self.args.overlay_path,
            dry_run=self.args.dry_run,
        )

    def make_player(self, **kwargs):
        eff = self.effective()
        set_policy_key(eff.policy_key)
        store = SeenStore(state_path()) if eff.remember_seen else None
        return NHLVideoPlayer(self.options(), seen_store=store, **kwargs)

    def apply_to_player(self, player):
        eff = self.effective()
        set_policy_key(eff.policy_key)
        options = player.options
        options.poll_seconds = eff.poll_seconds
        options.card_seconds = eff.card_seconds
        options.max_height = eff.max_height
        options.quality = eff.quality
        options.show_cards = eff.show_cards
        options.card_mode = eff.card_mode
        options.video_overlay = eff.video_overlay
        if (options.receiver_mode, options.receiver_app_id) != (eff.receiver_mode, eff.receiver_app_id):
            options.receiver_mode = eff.receiver_mode
            options.receiver_app_id = eff.receiver_app_id
            player.reset_receiver_choice()
        options.known_hosts = list(eff.known_hosts)
        if eff.remember_seen and player.seen_store is None:
            player.seen_store = SeenStore(state_path())
        elif not eff.remember_seen:
            player.seen_store = None


def choose_device(devices, eff, input_fn=input, out=print, attempts=3):
    """Return (device, exit_code). exit_code is None on success."""
    if not devices:
        log.error("No Chromecasts found.")
        return None, 1
    configured = eff.device_uuid or eff.device_name or eff.device_host
    if configured:
        device = match_device(devices, eff.device_uuid, eff.device_name, eff.device_host)
        if device is None:
            log.error("No device matching %s", eff.device_name or eff.device_uuid or eff.device_host)
            return None, 1
        return device, None
    if len(devices) == 1:
        return devices[0], None
    for index, device in enumerate(devices, start=1):
        out('[{}] "{}" {} {}'.format(index, device.name, device.model, device.host))
    for _ in range(attempts):
        try:
            raw = input_fn("Select a Chromecast [1-{}]: ".format(len(devices))).strip()
        except (EOFError, OSError):
            log.error("No console to choose a device. Pick one in the tray (Devices) "
                      "or set [device] name in settings.ini, or pass --device.")
            return None, 2
        try:
            choice = int(raw)
        except ValueError:
            out("Please type a number.")
            continue
        if 1 <= choice <= len(devices):
            return devices[choice - 1], None
        out("Out of range.")
    log.error("No valid device selected.")
    return None, 2


def _once_timeout(clips):
    total = sum(max(0, c.duration_ms or 0) for c in clips) / 1000.0
    return max(120.0, total * 1.5 + 30.0 * len(clips))


def run_console(runtime):
    args = runtime.args
    eff = runtime.effective()
    if not args.dry_run and not args.list_devices and not policy_key():
        log.error("No Brightcove policy key. Set policy_key in %s or BRIGHTCOVE_PK in the "
                  "environment/.env.", runtime.settings_path)
        return 2
    if not args.quiet and not args.dry_run and sys.stdout is not None and sys.stdout.isatty():
        print(BANNER)
    player = runtime.make_player()
    interrupted = threading.Event()

    def on_signal(_signum, _frame):
        interrupted.set()
        player.stop.set()

    previous = {}
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass
    try:
        if args.list_devices:
            for device in player.discover():
                print("{}\t{}\t{}".format(device.name, device.model, device.host))
            return 130 if interrupted.is_set() else 0
        try:
            clips = player.poll_listing()
        except requests.RequestException as exc:
            log.error("Could not list videos: %s", exc)
            return 1
        if args.dry_run:
            for clip in clips:
                print("{} [{}] {}".format(clip.brightcove_id, clip.team, clip.title))
            return 0
        if interrupted.is_set():
            return 130
        devices = player.discover()
        if interrupted.is_set():
            return 130
        device, code = choose_device(devices, eff)
        if device is None:
            return code
        if not (eff.device_uuid or eff.device_name or eff.device_host):
            stored = runtime.stored.copy(device_name=device.name, device_uuid=device.uuid,
                                         device_host=device.host)
            try:
                settings_mod.save(stored, runtime.settings_path)
                log.info("Saved %s as the default device in %s", device.name, runtime.settings_path)
            except OSError:
                pass
        if not player.connect(device):
            return 1
        if args.once:
            timeout = _once_timeout(player.queue.pending())
            player.advance()
            player.wait_until_drained(timeout)
            return 130 if interrupted.is_set() else 0
        if not player.queue.pending_count():
            log.info("No playable clips yet; waiting for the next poll")
        player.start_polling()
        player.kick()
        while not player.stop.wait(0.5):
            pass
        return 130 if interrupted.is_set() else 0
    except KeyboardInterrupt:
        return 130
    finally:
        player.shutdown()
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.version:
        print("pygoals " + __version__)
        return 0
    load_dotenv()
    path = args.config or settings_path()
    stored = settings_mod.load(path)
    runtime = Runtime(args, stored, path)
    eff = runtime.effective()
    runtime.log_file = setup_logging(eff.log_level, to_file=eff.log_to_file)
    set_policy_key(eff.policy_key)
    headless = args.cli or args.dry_run or args.list_devices or args.once
    if not headless:
        try:
            import tray
        except ImportError as exc:
            log.warning("PyQt6 is not available (%s); falling back to console mode. "
                        "Install it with: pip install PyQt6", exc)
            headless = True
    if headless:
        return run_console(runtime)
    return tray.run_tray(runtime)


def console_entry():
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
