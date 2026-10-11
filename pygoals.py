"""NHL goal highlights on a Chromecast. Secrets from the environment only."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from collections import deque

import requests

from brightcove import policy_key, resolve_clip
from cards import idle_card, render_card
from http_util import get_json
from media_server import CardServer
from nhl_ingest import GoalClip, clips_from_listing

log = logging.getLogger("pygoals")

VIDEO_URL = "https://forge-dapi.d3.nhle.com/v2/content/en-US/videos?tags.slug=goal"
BANNER = r"""
██████╗ ██╗   ██╗ ██████╗  ██████╗  █████╗ ██╗     ███████╗
██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔═══██╗██╔══██╗██║     ██╔════╝
██████╔╝ ╚████╔╝ ██║  ███╗██║   ██║███████║██║     ███████╗
version 1.1 — unofficial. Set BRIGHTCOVE_PK. LAN Chromecast only.
"""


def build_parser():
    parser = argparse.ArgumentParser(description="Cast NHL goal highlights on your LAN.")
    parser.add_argument("--known-host", action="append", help="Chromecast IP, repeatable")
    parser.add_argument("--device", default=os.environ.get("PYGOALS_DEVICE"), help="Friendly name substring")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=60)
    parser.add_argument("--overlay-path", default=None)
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("PYGOALS_LOG_LEVEL", "INFO"))
    parser.add_argument("--version", action="store_true")
    return parser


class AdvanceListener:
    """pychromecast MediaStatusListener: advance only after a clip FINISHED."""

    def __init__(self, player):
        self.player = player

    def new_media_status(self, status):
        state = getattr(status, "player_state", None)
        reason = str(getattr(status, "idle_reason", "") or "")
        if state == "IDLE" and reason == "FINISHED" and self.player.expect_advance:
            self.player.expect_advance = False
            threading.Thread(target=self.player.play_next, daemon=True).start()

    def load_media_failed(self, *args):
        log.warning("load_media_failed %s", args)
        self.player.expect_advance = False
        threading.Thread(target=self.player.play_next, daemon=True).start()


class NHLVideoPlayer:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.pending = deque()
        self.seen_media = set()
        self.queued_ids = set()
        self.cast = None
        self.browser = None
        self.zeroconf = None
        self.stop = threading.Event()
        self.expect_advance = False
        self.overlay_dir = args.overlay_path or tempfile.mkdtemp(prefix="pygoals-")
        self.server = None
        self.poll_thread = None

    def poll_listing(self):
        payload = get_json(VIDEO_URL)
        clips, skips = clips_from_listing(payload)
        for skip in skips:
            log.info("skip %s (%s)", skip.get("title"), skip.get("reason"))
        pk = policy_key()
        new_clips = []
        for clip in clips:
            if clip.brightcove_id in self.seen_media or clip.brightcove_id in self.queued_ids:
                continue
            if pk and not self.args.dry_run:
                try:
                    resolve_clip(clip)
                except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
                    log.warning("resolve failed %s: %s", clip.brightcove_id, exc)
                    continue
                if not clip.playback_url:
                    log.info("skip %s (no_mp4)", clip.title)
                    continue
            new_clips.append(clip)
        with self.lock:
            for clip in new_clips:
                self.pending.append(clip)
                self.queued_ids.add(clip.brightcove_id)
        return new_clips

    def choose_device(self, casts):
        if not casts:
            log.error("No Chromecasts found.")
            return None
        if self.args.device:
            needle = self.args.device.lower()
            for cast in casts:
                if needle in (cast.name or "").lower():
                    return cast
            log.error("No device matching %s", self.args.device)
            return None
        for index, cast in enumerate(casts, start=1):
            print('[{}] "{}"'.format(index, cast.name))
        raw = input("Select a Chromecast [1-{}]: ".format(len(casts))).strip()
        try:
            choice = int(raw) - 1
        except ValueError:
            log.error("Not a number")
            return None
        if choice < 0 or choice >= len(casts):
            log.error("Index out of range")
            return None
        return casts[choice]

    def start_cast(self):
        import pychromecast
        from zeroconf import Zeroconf

        self.zeroconf = Zeroconf()
        chromecasts, self.browser = pychromecast.get_chromecasts(
            known_hosts=self.args.known_host, zeroconf_instance=self.zeroconf
        )
        if self.args.list_devices:
            for cast in chromecasts:
                print(cast.name)
            return False
        self.cast = self.choose_device(chromecasts)
        if self.cast is None:
            return False
        self.cast.wait()
        try:
            from pychromecast.controllers.media import MediaStatusListener

            class _Listener(AdvanceListener, MediaStatusListener):
                pass

            self.cast.media_controller.register_status_listener(_Listener(self))
        except Exception:
            log.debug("status listener not registered", exc_info=True)
            try:
                self.cast.media_controller.register_status_listener(AdvanceListener(self))
            except Exception:
                log.debug("duck-typed listener failed", exc_info=True)
        if not self.args.no_overlay:
            self.server = CardServer(self.overlay_dir).start()
            idle = idle_card(self.overlay_dir)
            self._play_media(self.server.url_for(idle), "image/png")
        return True

    def _play_media(self, url, mime):
        mc = self.cast.media_controller
        mc.play_media(url, mime)
        mc.block_until_active()

    def play_next(self):
        with self.lock:
            if not self.pending:
                clip = None
            else:
                clip = self.pending.popleft()
        if clip is None:
            log.info("Queue empty")
            return
        self.expect_advance = False
        if not self.args.no_overlay and self.server and clip.player_id:
            try:
                path = render_card(clip.player_id, clip.team, clip.title, out_dir=self.overlay_dir)
                self._play_media(self.server.url_for(path), "image/png")
                time.sleep(4)
            except Exception:
                log.exception("card failed; playing video")
        if not clip.playback_url:
            log.info("No playback URL for %s", clip.title)
            return
        self._play_media(clip.playback_url, clip.mime or "video/mp4")
        with self.lock:
            self.seen_media.add(clip.brightcove_id)
        self.expect_advance = True
        remaining = len(self.pending)
        log.info("Now playing %s (%s left)", clip.title, remaining)

    def poll_loop(self):
        while not self.stop.wait(self.args.poll_seconds):
            try:
                self.poll_listing()
            except Exception:
                log.exception("poll failed")

    def shutdown(self, *_args):
        log.info("Shutting down")
        self.stop.set()
        if self.cast:
            try:
                self.cast.quit_app()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.stop_discovery()
            except Exception:
                pass
        if self.zeroconf:
            try:
                self.zeroconf.close()
            except Exception:
                pass
        if self.server:
            self.server.stop()

    def reset_queue(self):
        with self.lock:
            self.pending.clear()
            self.queued_ids.clear()
            self.seen_media.clear()
        self.poll_listing()


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    if args.version:
        print("pygoals 1.1")
        return 0
    if not args.quiet and not args.dry_run:
        print(BANNER)
    if not args.dry_run and not args.list_devices and not policy_key():
        log.error("Set BRIGHTCOVE_PK in the environment (see .env.example).")
        return 2
    player = NHLVideoPlayer(args)
    try:
        clips = player.poll_listing()
    except requests.RequestException as exc:
        log.error("Could not list videos: %s", exc)
        return 1
    if args.dry_run:
        for clip in clips:
            print("{} [{}] {}".format(clip.brightcove_id, clip.team, clip.title))
        return 0
    if not player.start_cast():
        player.shutdown()
        return 1 if not args.list_devices else 0
    if not player.pending and not args.once:
        log.warning("No playable clips yet; waiting for poll")
    else:
        player.play_next()
    signal.signal(signal.SIGINT, player.shutdown)
    try:
        signal.signal(signal.SIGTERM, player.shutdown)
    except (AttributeError, ValueError):
        pass
    if args.once:
        player.stop.wait(timeout=90)
        player.shutdown()
        return 0
    player.poll_thread = threading.Thread(target=player.poll_loop, daemon=True)
    player.poll_thread.start()
    while not player.stop.is_set():
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
