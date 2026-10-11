"""Chromecast playback engine: discovery, queue, card + clip, polling.

UI-agnostic. The console runner and the tray both drive ``NHLVideoPlayer``
and subscribe to ``player.events``. Callbacks fire on worker threads; the
tray marshals them to the GUI thread with Qt signals.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from brightcove import PolicyKeyError, policy_key, resolve_clip
from cards import CardVideoUnavailable, card_video, cleanup_cards, idle_card, receiver_card, render_card
from clip_queue import ClipQueue
from http_util import get_json
from media_server import CardServer, is_loopback
from nhl_ingest import clips_from_listing

log = logging.getLogger("pygoals.player")

VIDEO_URL = "https://forge-dapi.d3.nhle.com/v2/content/en-US/videos?tags.slug=goal"
CONNECT_TIMEOUT = 15.0
ACTIVE_TIMEOUT = 20.0        # s for the receiver to accept a video LOAD
CARD_FETCH_TIMEOUT = 6.0     # s for the TV to GET the card from our server
STALL_SECONDS = 25.0         # s stuck BUFFERING without progress => skip
OVERRUN_GRACE = 45.0         # s past the clip duration => skip
WATCHDOG_INTERVAL = 2.0
STATUS_REFRESH = 6.0
STREAM_TYPE = "BUFFERED"
RECEIVER_RESTART_PAUSE = 1.5
DEFAULT_RECEIVER_APP_ID = "CC1AD845"     # VOD clips; pychromecast's default (LIVE) stalls some receivers
QUIT_TIMEOUT = 5.0
DISCONNECT_TIMEOUT = 3.0

# Event names
STATUS = "status"            # text
NOW_PLAYING = "now_playing"  # clip (or None when idle)
NEW_CLIPS = "new_clips"      # clips
ERROR = "error"              # kind, message
DEVICES = "devices"          # devices (list[DeviceInfo])
DEVICE = "device"            # device (DeviceInfo or None)
POLLING = "polling"          # enabled
DISCOVERING = "discovering"  # active
STOPPED = "stopped"

# Error kinds
ERR_AUTH = "auth"
ERR_NO_KEY = "no_key"
ERR_NO_DEVICE = "no_device"
ERR_LOOPBACK = "loopback"
ERR_NETWORK = "network"
ERR_PLAYBACK = "playback"
ERR_CARD_UNREACHABLE = "card_unreachable"
ERR_RECEIVER = "receiver"
CUSTOM_LAUNCH_TIMEOUT = 15.0
LOWER_THIRD_SECONDS = 8.0


def describe_url(url):
    """Short, token-free description of a media URL for logs."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(str(url))
    except ValueError:
        return "?"
    name = parts.path.rsplit("/", 1)[-1] or parts.path
    return "{}/…/{}".format(parts.netloc, name) if parts.netloc else name


class Events:
    """Minimal thread-safe pub/sub. Subscriber errors are logged, not raised."""

    def __init__(self):
        self._subs = {}
        self._lock = threading.Lock()

    def subscribe(self, name, callback):
        with self._lock:
            self._subs.setdefault(name, []).append(callback)
        return callback

    def unsubscribe(self, name, callback):
        with self._lock:
            if callback in self._subs.get(name, []):
                self._subs[name].remove(callback)

    def emit(self, name, **payload):
        with self._lock:
            subscribers = list(self._subs.get(name, []))
        for callback in subscribers:
            try:
                callback(**payload)
            except Exception:
                log.exception("event subscriber for %s failed", name)


@dataclass
class PlayerOptions:
    poll_seconds: float = 60.0
    card_seconds: float = 4.0
    max_height: int = 1080
    quality: str = "auto"
    show_cards: bool = True
    card_mode: str = "video"  # video | image (off is show_cards=False)
    receiver_mode: str = "auto"  # auto | custom | default
    receiver_app_id: str = ""
    video_overlay: bool = False  # title text over the video (cast metadata / receiver lower third)
    port: int = 0
    known_hosts: list = field(default_factory=list)
    overlay_path: str | None = None
    dry_run: bool = False


@dataclass
class DeviceInfo:
    name: str
    model: str
    host: str
    uuid: str
    cast: object = None

    @classmethod
    def from_cast(cls, cast):
        info = getattr(cast, "cast_info", None)
        name = getattr(info, "friendly_name", None) or getattr(cast, "name", None) or "?"
        return cls(
            name=str(name),
            model=str(getattr(info, "model_name", "") or ""),
            host=str(getattr(info, "host", "") or ""),
            uuid=str(getattr(info, "uuid", "") or ""),
            cast=cast,
        )


def match_device(devices, uuid="", name="", host=""):
    """uuid, then exact name, then name substring, then host."""
    uuid = (uuid or "").strip().lower()
    name = (name or "").strip().lower()
    host = (host or "").strip()
    if uuid:
        for device in devices:
            if device.uuid.lower() == uuid:
                return device
    if name:
        for device in devices:
            if device.name.lower() == name:
                return device
        for device in devices:
            if name in device.name.lower():
                return device
    if host:
        for device in devices:
            if device.host == host:
                return device
    return None


def default_discover(known_hosts):
    """Blocking discovery (about 5 s). Returns (devices, browser)."""
    import pychromecast

    casts, browser = pychromecast.get_chromecasts(
        known_hosts=list(known_hosts) or None, tries=3, retry_wait=2, timeout=10
    )
    devices = sorted((DeviceInfo.from_cast(c) for c in casts), key=lambda d: d.name.lower())
    return devices, browser


def _status_listener_base():
    try:
        from pychromecast.controllers.media import MediaStatusListener

        return MediaStatusListener
    except Exception:  # pychromecast missing or API moved
        return object


class _AdvanceListenerMixin:
    """Advance only after the current clip FINISHED (or errored) on this cast."""

    def __init__(self, player, cast):
        self.player = player
        self.cast = cast

    def new_media_status(self, status):
        if self.cast is not self.player.cast:
            return
        self.player.on_media_status(status)
        state = getattr(status, "player_state", None)
        reason = str(getattr(status, "idle_reason", "") or "")
        if state == "IDLE" and reason in ("FINISHED", "ERROR"):
            self.player.on_clip_ended(reason, getattr(status, "content_id", None))

    def load_media_failed(self, queue_item_id=None, error_code=None):
        if self.cast is not self.player.cast:
            return
        self.player.on_load_failed(error_code)


def make_listener(player, cast):
    base = _status_listener_base()
    bases = (_AdvanceListenerMixin,) if base is object else (_AdvanceListenerMixin, base)
    cls = type("AdvanceListener", bases, {})
    return cls(player, cast)


class NHLVideoPlayer:
    def __init__(self, options=None, *, queue=None, events=None, seen_store=None,
                 fetch_listing=None, discover=None, resolve=None, card_server_factory=None):
        self.options = options or PlayerOptions()
        self.queue = queue or ClipQueue(seen=seen_store.load() if seen_store else ())
        self.events = events or Events()
        self.seen_store = seen_store
        self._fetch_listing = fetch_listing or (lambda: get_json(VIDEO_URL))
        self._discover = discover or default_discover
        self._resolve = resolve or resolve_clip
        self._server_factory = card_server_factory or CardServer

        self._owns_overlay_dir = not self.options.overlay_path
        self.overlay_dir = Path(self.options.overlay_path or tempfile.mkdtemp(prefix="pygoals-"))

        self.stop = threading.Event()
        self.polling_enabled = threading.Event()
        self.polling_enabled.set()
        self._poll_now = threading.Event()
        self._load_failed = threading.Event()
        self._advance_lock = threading.Lock()
        self._device_lock = threading.RLock()
        self._discover_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shut_down = False
        self._idle_shown = False
        self._logged_skips = set()
        self._auth_reported = False
        self._network_reported = False
        self._last_card = None
        self._status_cond = threading.Condition()
        self._last_status = None
        self._status_key = None
        self._card_warned = False
        self._image_session = False
        self._expect_url = None
        self._clip_playing_seen = False
        self._card_cache = {}
        self._card_lock = threading.Lock()
        self._card_threads = {}
        self._video_cards_ok = True
        self._card_hold = 0.0
        self._custom_failed = False  # auto mode: custom receiver didn't launch on this device
        self._receiver_warned = False
        self._watchdog = None
        self._started_at = 0.0
        self._progress = (None, 0.0)  # (current_time, monotonic when it last changed)

        self.cast = None
        self.device = None
        self.devices = []
        self._cast_browser = None
        self._scan_browser = None
        self._listener = None
        self.server = None
        self.poll_thread = None
        self.status_text = "Starting"

    # -- small helpers ---------------------------------------------------
    def _set_status(self, text):
        self.status_text = text
        self.events.emit(STATUS, text=text)

    def report_error(self, kind, message):
        log.error("%s", message) if kind in (ERR_AUTH, ERR_NO_KEY) else log.warning("%s", message)
        self.events.emit(ERROR, kind=kind, message=message)

    def _save_seen(self):
        if self.seen_store is None:
            return
        try:
            self.seen_store.save(self.queue.seen_ids())
        except OSError:
            log.warning("could not save state", exc_info=True)

    # -- ingest ----------------------------------------------------------
    def poll_listing(self):
        payload = self._fetch_listing()
        clips, skips = clips_from_listing(payload)
        for skip in skips:
            key = (skip.get("id"), skip.get("reason"))
            if key in self._logged_skips:
                log.debug("skip %s (%s)", skip.get("title"), skip.get("reason"))
                continue
            if len(self._logged_skips) > 5000:
                self._logged_skips.clear()
            self._logged_skips.add(key)
            log.info("skip %s (%s)", skip.get("title"), skip.get("reason"))
        key = policy_key()
        resolve = bool(key) and not self.options.dry_run
        if not resolve and not self.options.dry_run:
            # Without a key nothing is playable; don't queue (or burn) clips.
            log.debug("no Brightcove key; %d clip(s) not queued", len(clips))
            return []
        new_clips = []
        for clip in clips:
            if self.stop.is_set():
                break
            if self.queue.is_known(clip.brightcove_id):
                continue
            if resolve:
                try:
                    self._resolve(clip, pk=key, max_height=self.options.max_height,
                                  quality=self.options.quality)
                    clip.resolved_for = self._quality_choice()
                except PolicyKeyError as exc:
                    if not self._auth_reported:
                        self._auth_reported = True
                        self.report_error(ERR_AUTH, "{}. Update the key in Settings.".format(exc))
                    break
                except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
                    log.warning("resolve failed %s: %s", clip.brightcove_id, exc)
                    continue
                self._auth_reported = False
                if not clip.playback_url:
                    log.info("skip %s (no_mp4)", clip.title)
                    self.queue.mark_failed(clip.brightcove_id)
                    continue
            new_clips.append(clip)
        added = self.queue.add(new_clips)
        self._network_reported = False
        if added:
            self.events.emit(NEW_CLIPS, clips=added)
        return added

    # -- devices ---------------------------------------------------------
    def discover(self):
        """Blocking scan. Returns ``list[DeviceInfo]``; emits DEVICES."""
        with self._discover_lock:
            self.events.emit(DISCOVERING, active=True)
            try:
                devices, browser = self._discover(self.options.known_hosts)
            except Exception as exc:
                log.exception("discovery failed")
                self.report_error(ERR_NO_DEVICE, "Chromecast discovery failed: {}".format(exc))
                devices, browser = [], None
            finally:
                self.events.emit(DISCOVERING, active=False)
            with self._device_lock:
                old = self._scan_browser
                self._scan_browser = browser
                if old is not None and old is not self._cast_browser:
                    self._stop_browser(old)
                if self.stop.is_set() and browser is not None:
                    self._stop_browser(browser)
                    self._scan_browser = None
            self.devices = list(devices)
            self.events.emit(DEVICES, devices=list(self.devices))
            if not self.devices:
                self.report_error(ERR_NO_DEVICE, "No Chromecasts found on the network.")
            return list(self.devices)

    @staticmethod
    def _stop_browser(browser):
        try:
            browser.stop_discovery()  # also closes the Zeroconf it created
        except Exception:
            log.debug("stop_discovery failed", exc_info=True)

    def connect(self, device):
        """Connect to ``device`` (DeviceInfo) and make it the active cast."""
        if self.stop.is_set():
            return False
        cast = device.cast
        with self._device_lock:
            if cast is not None and cast is self.cast:
                return True
            self._set_status("Connecting to {}".format(device.name))
            try:
                cast.wait(timeout=CONNECT_TIMEOUT)
            except Exception as exc:
                self.report_error(ERR_NO_DEVICE, "Could not connect to {}: {}".format(device.name, exc))
                try:
                    cast.disconnect(timeout=0)
                except Exception:
                    pass
                return False
            old_cast = self.cast
            if old_cast is not None:
                self.queue.abort_current()
                self._release_cast(old_cast)
            self.cast = cast
            self.device = device
            self._custom_failed = False  # another TV may be a registered test device
            self._receiver_warned = False
            # A receiver left over from an earlier run may be stuck on an image
            # or a frozen video; start the first clip in a fresh one.
            self._image_session = getattr(cast, "app_id", None) == DEFAULT_RECEIVER_APP_ID
            # The scan browser now owns the active cast; retire the old owner.
            if self._scan_browser is not None and self._scan_browser is not self._cast_browser:
                if self._cast_browser is not None:
                    self._stop_browser(self._cast_browser)
                self._cast_browser = self._scan_browser
            self._listener = make_listener(self, cast)
            try:
                cast.media_controller.register_status_listener(self._listener)
            except Exception:
                self._listener = None
                log.warning("media status listener not registered; auto-advance disabled", exc_info=True)
            if self.options.show_cards:
                self._ensure_server()
                ip = self.server.set_client_target(device.host or None)
                if is_loopback(ip):
                    self.report_error(
                        ERR_LOOPBACK,
                        "Card server fell back to {}; the Chromecast cannot reach it. "
                        "Check the network adapter or disable cards.".format(ip),
                    )
            self._idle_shown = False
        log.info("Using Chromecast %s (%s)", device.name, device.host)
        if self.wants_custom_receiver() and not self.options.dry_run:
            # Bring up the pygoals receiver right away so the TV shows its
            # logo idle screen even before the first goal.
            with self._advance_lock:
                if self.cast is cast and self._ensure_custom_receiver():
                    self._idle_shown = True
        self.start_watchdog()
        self.events.emit(DEVICE, device=device)
        self._set_status("Connected to {}".format(device.name))
        return True

    def _release_cast(self, cast):
        try:
            cast.quit_app(timeout=QUIT_TIMEOUT)
        except Exception:
            log.debug("quit_app failed", exc_info=True)
        try:
            cast.disconnect(timeout=DISCONNECT_TIMEOUT)
        except Exception:
            log.debug("disconnect failed", exc_info=True)

    def _ensure_server(self):
        if self.server is None:
            self.server = self._server_factory(self.overlay_dir, port=self.options.port).start()
        return self.server

    # -- playback ----------------------------------------------------------
    def _send_load(self, url, mime, title=None, extra=None):
        cast = self.cast
        if cast is None:
            raise RuntimeError("no Chromecast selected")
        mc = cast.media_controller
        self._load_failed.clear()
        kwargs = {"stream_type": STREAM_TYPE}
        if title:
            kwargs["title"] = title
        if extra:
            kwargs.update(extra)
        log.info("LOAD %s %s on %s", mime, describe_url(url), self.device.name if self.device else "?")
        self._image_session = str(mime).startswith("image/")
        try:
            mc.play_media(url, mime, **kwargs)
        except TypeError:  # very old pychromecast without these keywords
            mc.play_media(url, mime)
        return mc

    def _play_media(self, url, mime, title=None, timeout=ACTIVE_TIMEOUT, extra=None):
        """LOAD and wait until the receiver reports this URL as loaded.

        Success means a media status whose content_id is ``url`` and whose
        state is not IDLE. Raises on LOAD_FAILED, IDLE/ERROR or timeout.
        Falls back to the session-active event when no listener is wired.
        """
        mc = self._send_load(url, mime, title, extra=extra)
        deadline = time.monotonic() + timeout
        with_listener = self._listener is not None
        event = getattr(mc, "session_active_event", None)
        while True:
            if self.stop.is_set():
                raise RuntimeError("stopping")
            if self._load_failed.is_set():
                raise RuntimeError("Chromecast reported LOAD_FAILED")
            status = self._last_status
            if with_listener and status is not None and getattr(status, "content_id", None) == url:
                state = getattr(status, "player_state", None)
                if state and state != "IDLE":
                    log.info("loaded %s: %s", describe_url(url), state)
                    return status
                if state == "IDLE" and getattr(status, "idle_reason", None) == "ERROR":
                    raise RuntimeError("Chromecast reported IDLE/ERROR for the media")
            if not with_listener:
                mc.block_until_active(timeout=0.5)
                if event is None or event.is_set():
                    return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Chromecast did not load {} within {:.0f}s".format(mime, timeout))
            with self._status_cond:
                self._status_cond.wait(min(0.5, remaining))

    def _show_card(self, clip):
        """Show the card; returns quickly if the TV can't fetch it."""
        self._ensure_server()
        card = render_card(clip.player_id, clip.team, clip.title, out_dir=self.overlay_dir)
        url = self.server.url_for(card)
        self._send_load(url, "image/png", self._overlay_title(clip))
        name = Path(card).name
        if not self.server.wait_for_fetch(name, CARD_FETCH_TIMEOUT, stop=self.stop):
            self._card_unreachable()
            return card, False
        log.info("card fetched by the Chromecast")
        if self.options.card_seconds > 0:
            self.stop.wait(self.options.card_seconds)
        return card, True

    def _card_unreachable(self):
        server = self.server
        where = "http://{}:{}".format(server.host_for_clients, server.port) if server else "this PC"
        message = (
            "The TV did not fetch the player card from {} within {:.0f}s, so cards are skipped and "
            "clips play without them. A firewall (Windows Firewall, Norton or another security "
            "suite) is probably blocking inbound TCP port {} for this Python ({}). Allow that "
            "port on private networks, keep a fixed port in Settings, or turn cards off."
        ).format(where, CARD_FETCH_TIMEOUT, server.port if server else "?", sys.executable)
        if not self._card_warned:
            self._card_warned = True
            self.report_error(ERR_CARD_UNREACHABLE, message)
        else:
            log.warning("card not fetched by the Chromecast; skipped")

    def _show_idle(self):
        if self._idle_shown or not self.options.show_cards or self.cast is None:
            return
        if self.custom_receiver_running():
            self._idle_shown = True  # the pygoals receiver shows its own idle screen
            return
        try:
            self._ensure_server()
            path = idle_card(self.overlay_dir)
            self._send_load(self.server.url_for(path), "image/png", "pygoals")
            self._idle_shown = True
        except Exception:
            log.warning("idle card failed", exc_info=True)

    def _overlay_title(self, clip):
        """Title for cast metadata; None keeps receivers from drawing text over the video."""
        return clip.title if self.options.video_overlay else None

    def _quality_choice(self):
        return (self.options.quality, self.options.max_height)

    def _refresh_rendition(self, clip):
        """Re-resolve a queued clip if the quality setting changed since."""
        wanted = self._quality_choice()
        had = getattr(clip, "resolved_for", None)
        if had is None or had == wanted or self.options.dry_run:
            return
        key = policy_key()
        if not key:
            return
        try:
            self._resolve(clip, pk=key, max_height=self.options.max_height, quality=self.options.quality)
            clip.resolved_for = wanted
        except Exception as exc:  # noqa: BLE001 - keep the earlier URL
            log.warning("re-resolve for new quality failed (%s); using the earlier rendition", exc)

    def known_sources(self):
        """Brightcove sources of a clip resolved this session, if any."""
        clips = [self.queue.current] + list(self.queue.pending())
        for clip in clips:
            if clip is not None and getattr(clip, "sources", None):
                return clip.sources
        return None

    def _reset_receiver_after_image(self):
        """Quit the Default Media Receiver if it is showing an image.

        On Google TV devices (onn 4K Pro) a video LOADed into a receiver session
        that last displayed an image plays audio only and its clock freezes a
        few seconds in. A fresh receiver plays the same URL fine, so the session
        is closed and play_media launches a new one.
        """
        cast = self.cast
        if cast is None or not self._image_session:
            return
        log.info("restarting the Default Media Receiver before the video (image session)")
        try:
            cast.quit_app(timeout=10)
        except Exception:
            log.warning("could not quit the receiver app", exc_info=True)
        self._image_session = False
        with self._status_cond:
            self._last_status = None
        self.stop.wait(RECEIVER_RESTART_PAUSE)

    # -- card videos ------------------------------------------------------------
    def _card_seconds(self):
        return max(1.0, float(self.options.card_seconds or 0))

    def _make_card_video(self, clip):
        png = render_card(clip.player_id, clip.team, clip.title, out_dir=self.overlay_dir)
        started = time.monotonic()
        mp4 = card_video(png, self._card_seconds(), out_path=Path(png).with_suffix(".mp4"))
        try:
            Path(png).unlink()
        except OSError:
            pass
        log.debug("card video for %s encoded in %.1fs", clip.title, time.monotonic() - started)
        return mp4

    def _card_video_for(self, clip):
        """Card MP4 for ``clip``: prepared in the background, else made now."""
        key = (clip.brightcove_id, self._card_seconds())
        with self._card_lock:
            thread = self._card_threads.get(key)
        if thread is not None:
            thread.join(30)
        with self._card_lock:
            path = self._card_cache.get(key)
        if path is not None and Path(path).is_file():
            return path
        path = self._make_card_video(clip)
        with self._card_lock:
            self._card_cache[key] = path
        return path

    def _prefetch_next_card(self):
        """Encode the next clip's card while this one plays (about 1 s of ffmpeg)."""
        if not (self.options.show_cards and self.options.card_mode == "video" and self._video_cards_ok):
            return
        if self.wants_custom_receiver() and self.custom_receiver_running():
            return
        pending = self.queue.pending()
        if not pending or not pending[0].player_id:
            return
        clip = pending[0]
        key = (clip.brightcove_id, self._card_seconds())
        with self._card_lock:
            if key in self._card_cache or key in self._card_threads:
                return

            def work():
                try:
                    path = self._make_card_video(clip)
                    with self._card_lock:
                        self._card_cache[key] = path
                except Exception:  # noqa: BLE001 - made again (or skipped) at play time
                    log.debug("card prefetch failed", exc_info=True)
                finally:
                    with self._card_lock:
                        self._card_threads.pop(key, None)

            thread = threading.Thread(target=work, name="card-prefetch", daemon=True)
            self._card_threads[key] = thread
        thread.start()

    def _drop_card_cache(self, keep=()):
        keep_names = {Path(k).name for k in keep if k}
        with self._card_lock:
            for key, path in list(self._card_cache.items()):
                if Path(path).name not in keep_names:
                    self._card_cache.pop(key, None)
            return [p for p in self._card_cache.values()]

    def _play_with_card_video(self, card, clip):
        """QUEUE_LOAD [card video, clip]: the receiver goes card -> goal gaplessly.

        Returns True once the receiver plays either item, False when the TV
        never fetched the card (caller loads the clip directly).
        """
        cast = self.cast
        if cast is None:
            raise RuntimeError("no Chromecast selected")
        self._ensure_server()
        card_url = self.server.url_for(card)
        name = Path(card).name
        mc = cast.media_controller

        def item(url, mime, title, preload):
            metadata = {"metadataType": 0}
            if title:
                metadata["title"] = title
            return {"media": {"contentId": url, "contentType": mime, "streamType": STREAM_TYPE,
                              "metadata": metadata},
                    "autoplay": True, "startTime": 0, "preloadTime": preload}

        message = {
            "type": "QUEUE_LOAD",
            "items": [item(card_url, "video/mp4", self._overlay_title(clip), 0),
                      item(clip.playback_url, clip.mime or "video/mp4", self._overlay_title(clip),
                           min(3, self._card_seconds()))],
            "startIndex": 0,
            "repeatMode": "REPEAT_OFF",
        }
        self._load_failed.clear()
        self._image_session = False
        log.info("QUEUE_LOAD card video %s + %s %s on %s", describe_url(card_url), clip.mime,
                 describe_url(clip.playback_url), self.device.name if self.device else "?")
        mc.send_message(message, inc_session_id=True)
        started = time.monotonic()
        deadline = started + ACTIVE_TIMEOUT
        urls = (card_url, clip.playback_url)
        while True:
            if self.stop.is_set():
                raise RuntimeError("stopping")
            if self._load_failed.is_set():
                raise RuntimeError("Chromecast reported LOAD_FAILED")
            status = self._last_status
            if status is not None and getattr(status, "content_id", None) in urls:
                state = getattr(status, "player_state", None)
                if state and state != "IDLE":
                    log.info("card video playing (%s) %.1fs after QUEUE_LOAD", state, time.monotonic() - started)
                    return True
            now = time.monotonic()
            if now - started >= CARD_FETCH_TIMEOUT and not self.server.was_fetched(name):
                self._card_unreachable()
                return False
            if now >= deadline:
                raise TimeoutError("Chromecast did not start the card video within {:.0f}s".format(ACTIVE_TIMEOUT))
            with self._status_cond:
                self._status_cond.wait(min(0.25, deadline - now))

    # -- receiver selection -------------------------------------------------------
    def reset_receiver_choice(self):
        """Settings changed: try the custom receiver again on the next clip."""
        self._custom_failed = False
        self._receiver_warned = False

    def wants_custom_receiver(self):
        mode = (self.options.receiver_mode or "auto").lower()
        if mode == "default" or not self.options.receiver_app_id:
            return False
        if mode == "auto" and self._custom_failed:
            return False
        return True

    def custom_receiver_running(self):
        app = self.options.receiver_app_id
        return bool(app) and self.cast is not None and getattr(self.cast, "app_id", None) == app

    def _ensure_custom_receiver(self):
        """Launch the pygoals receiver unless it is already up. False on failure."""
        cast = self.cast
        if cast is None:
            return False
        app = self.options.receiver_app_id
        if self.custom_receiver_running():
            return True
        log.info("launching the pygoals Cast receiver %s on %s", app, self.device.name if self.device else "?")
        started = time.monotonic()
        try:
            cast.start_app(app, timeout=CUSTOM_LAUNCH_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - RequestFailed / RequestTimeout / socket errors
            self._custom_receiver_failed(exc)
            return False
        log.info("pygoals receiver %s running (%.1fs)", app, time.monotonic() - started)
        self._image_session = False
        self._idle_shown = False
        return True

    def _custom_receiver_failed(self, exc):
        app = self.options.receiver_app_id
        auto = (self.options.receiver_mode or "auto").lower() == "auto"
        detail = str(exc) or type(exc).__name__
        device = self.device.name if self.device else "the TV"
        if auto:
            # Normal for most TVs while the receiver is unpublished: no toast.
            self._custom_failed = True
            log.info("pygoals receiver %s isn't available on %s (%s); using the standard Cast "
                     "receiver with video cards", app, device, detail)
            return
        log.warning("pygoals receiver %s did not launch on %s: %s", app, device, detail)
        if self._receiver_warned:
            return
        self._receiver_warned = True
        message = (
            "The pygoals receiver isn't available on {} yet, so goals play on the standard Cast "
            "receiver for now. It's in testing and only runs on TVs registered as Cast test "
            "devices. Set Cast receiver to Auto to stop this notice."
        ).format(device)
        self.report_error(ERR_RECEIVER, message)

    def _play_clip(self, clip):
        if not clip.playback_url:
            log.info("No playback URL for %s", clip.title)
            self.queue.mark_failed(clip.brightcove_id)
            return False
        self._refresh_rendition(clip)
        custom = self.wants_custom_receiver() and self._ensure_custom_receiver()
        extra = None
        if custom:
            lower = LOWER_THIRD_SECONDS if self.options.video_overlay else 0
            payload = receiver_card(clip, self.options.card_seconds if self.options.show_cards else 0,
                                    lower_seconds=lower)
            if not self.options.show_cards:
                payload = {"title": clip.title, "cardSeconds": 0, "lowerSeconds": lower}
            metadata = {"metadataType": 0}
            if self.options.video_overlay:
                metadata["title"] = clip.title
                if payload.get("player"):
                    metadata["subtitle"] = payload["player"]
                if payload.get("headshot"):
                    metadata["images"] = [{"url": payload["headshot"]}]
            extra = {"media_info": {"customData": {"pygoals": payload}}, "metadata": metadata}
        mode = self.options.card_mode if (self.options.show_cards and clip.player_id and not custom) else "off"
        if mode == "video" and not self._video_cards_ok:
            mode = "image"
        self._expect_url = clip.playback_url
        self._clip_playing_seen = False
        if getattr(clip, "rendition", ""):
            log.info("casting %s as %s", clip.title, clip.rendition)
        card = None
        loaded = False
        self._card_hold = 0.0
        if mode == "video":
            try:
                card = self._card_video_for(clip)
            except CardVideoUnavailable as exc:
                self._video_cards_ok = False
                log.warning("video cards unavailable (%s); using image cards", exc)
                mode = "image"
            except Exception:
                log.warning("card video failed; playing the clip without it", exc_info=True)
            if card is not None:
                self._reset_receiver_after_image()
                try:
                    loaded = self._play_with_card_video(card, clip)
                    if loaded:
                        self._card_hold = self._card_seconds()
                except Exception as exc:  # noqa: BLE001 - load the clip on its own
                    log.warning("card + clip queue failed (%s); loading the clip directly", exc)
        if mode == "image":
            try:
                card, _shown = self._show_card(clip)
            except Exception:
                log.warning("card failed; playing the clip without it", exc_info=True)
        if self.stop.is_set():
            return False
        if not loaded:
            if not custom:
                self._reset_receiver_after_image()
            try:
                self._play_media(clip.playback_url, clip.mime or "video/mp4", title=self._overlay_title(clip),
                                 extra=extra)
            except Exception as exc:
                self.report_error(ERR_PLAYBACK, "Could not play {}: {}".format(clip.title, exc))
                self.queue.mark_failed(clip.brightcove_id)
                return False
        self.queue.mark_started(clip)
        self._started_at = time.monotonic() + self._card_hold
        self._progress = (None, self._started_at)
        self._idle_shown = False
        self._save_seen()
        try:
            keep = self._drop_card_cache(keep=[card] if card else [])
            cleanup_cards(self.overlay_dir, keep=([card] if card else []) + keep)
        except Exception:
            log.debug("card cleanup failed", exc_info=True)
        log.info("Now playing %s (%s left)%s", clip.title, self.queue.pending_count(),
                 " on the pygoals receiver" if custom else "")
        self.events.emit(NOW_PLAYING, clip=clip)
        self._set_status("Playing")
        self._prefetch_next_card()
        return True

    def advance(self):
        """Start the next clip unless one is current. Serialized; safe to spam."""
        with self._advance_lock:
            while not self.stop.is_set():
                if self.cast is None:
                    return False
                clip = self.queue.begin_next()
                if clip is None:
                    if not self.queue.busy:
                        self._show_idle()
                        self.events.emit(NOW_PLAYING, clip=None)
                        self._set_status("Waiting for goals")
                    return False
                if self._play_clip(clip):
                    return True
                self.queue.abort_current()
            return False

    def kick(self):
        """Non-blocking ``advance`` on a worker thread."""
        if self.stop.is_set():
            return None
        thread = threading.Thread(target=self.advance, name="pygoals-advance", daemon=True)
        thread.start()
        return thread

    def on_media_status(self, status):
        """Every media status from the receiver (pychromecast thread)."""
        if (getattr(status, "player_state", None) == "PLAYING" and self._expect_url
                and getattr(status, "content_id", None) == self._expect_url):
            self._clip_playing_seen = True
        state = getattr(status, "player_state", None)
        reason = getattr(status, "idle_reason", None)
        content = getattr(status, "content_id", None)
        key = (state, reason, content)
        if key != self._status_key:
            self._status_key = key
            current = getattr(status, "current_time", None)
            duration = getattr(status, "duration", None)
            log.info(
                "Chromecast media: %s%s %s t=%s/%s stream=%s",
                state, "/" + reason if reason else "",
                describe_url(content) if content else "-",
                "{:.1f}".format(current) if isinstance(current, (int, float)) else "-",
                "{:.1f}".format(duration) if isinstance(duration, (int, float)) else "-",
                getattr(status, "stream_type", "-"),
            )
        with self._status_cond:
            self._last_status = status
            self._status_cond.notify_all()

    def start_watchdog(self):
        if self._watchdog is None or not self._watchdog.is_alive():
            self._watchdog = threading.Thread(target=self._watchdog_loop, name="pygoals-watchdog", daemon=True)
            self._watchdog.start()
        return self._watchdog

    def _watchdog_loop(self):
        last_refresh = 0.0
        while not self.stop.wait(WATCHDOG_INTERVAL):
            try:
                last_refresh = self.check_playback(last_refresh)
            except Exception:
                log.debug("watchdog check failed", exc_info=True)

    def check_playback(self, last_refresh=0.0, now=None):
        """Skip a clip that is stuck buffering or runs far past its length."""
        now = time.monotonic() if now is None else now
        clip = self.queue.current
        if clip is None or not self.queue.started:
            return last_refresh
        cast = self.cast
        if cast is not None and now - last_refresh >= STATUS_REFRESH:
            try:
                cast.media_controller.update_status()
            except Exception:
                log.debug("update_status failed", exc_info=True)
            last_refresh = now
        status = self._last_status
        reason = None
        if status is not None and getattr(status, "content_id", None) == clip.playback_url:
            current = getattr(status, "current_time", None)
            last_time, since = self._progress
            if current != last_time:
                self._progress = (current, now)
            elif getattr(status, "player_state", None) in ("BUFFERING", "PLAYING") and now - since >= STALL_SECONDS:
                reason = "stuck {} at {}s for {:.0f}s".format(status.player_state, current, now - since)
        limit = max(30.0, (clip.duration_ms or 0) / 1000.0) + OVERRUN_GRACE
        if reason is None and now - self._started_at > limit:
            reason = "still not finished {:.0f}s after start".format(now - self._started_at)
        if reason:
            finished = self.queue.finish_current()
            if finished is not None:
                self.report_error(ERR_PLAYBACK, "Skipping {}: {}".format(finished.title, reason))
                self.kick()
        return last_refresh

    def on_clip_ended(self, reason="FINISHED", content_id=None):
        # A late/duplicate FINISHED for an earlier clip must not end this one.
        def matches(current):
            return not content_id or not current.playback_url or content_id == current.playback_url

        current = self.queue.current
        if (reason == "FINISHED" and current is not None and self.queue.started
                and current.playback_url and current.playback_url == self._expect_url
                and not self._clip_playing_seen):
            # A queue reports the card's FINISHED with the next item's id
            # before the clip has started; that is not the clip ending.
            log.debug("ignoring FINISHED before %s started playing", current.title)
            return
        clip = self.queue.finish_current(matches)
        if clip is None:
            return
        log.debug("clip ended (%s): %s", reason, clip.title)
        self.kick()

    def on_load_failed(self, error_code=None):
        self._load_failed.set()
        clip = self.queue.finish_current()
        if clip is not None:
            self.report_error(ERR_PLAYBACK, "Chromecast failed to load {} ({})".format(clip.title, error_code))
            self.kick()

    def skip(self):
        clip = self.queue.finish_current()
        if clip is not None:
            log.info("Skipped %s", clip.title)
        return self.kick()

    # -- polling -----------------------------------------------------------
    def set_polling(self, enabled):
        if enabled:
            self.polling_enabled.set()
            self._poll_now.set()
        else:
            self.polling_enabled.clear()
        self.events.emit(POLLING, enabled=bool(enabled))
        self._set_status("Polling resumed" if enabled else "Polling paused")

    def poll_now(self):
        self._poll_now.set()

    def _poll_once(self):
        try:
            added = self.poll_listing()
        except requests.RequestException as exc:
            if not self._network_reported:
                self._network_reported = True
                self.report_error(ERR_NETWORK, "Could not reach NHL video listing: {}".format(exc))
            return []
        except Exception:
            log.exception("poll failed")
            return []
        if added:
            self.kick()
        return added

    def poll_loop(self):
        while not self.stop.is_set():
            self._poll_now.wait(self.options.poll_seconds)
            self._poll_now.clear()
            if self.stop.is_set():
                break
            if not self.polling_enabled.is_set():
                continue
            self._poll_once()

    def start_polling(self, immediately=False):
        if self.poll_thread is None or not self.poll_thread.is_alive():
            self.poll_thread = threading.Thread(target=self.poll_loop, name="pygoals-poll", daemon=True)
            self.poll_thread.start()
        if immediately:
            self._poll_now.set()
        return self.poll_thread

    def replay_all(self):
        """Forget what was played and re-queue the current listing."""
        self.queue.reset()
        self._logged_skips.clear()
        self._save_seen()
        self._set_status("Replaying all")
        self._poll_now.set()
        if self.poll_thread is None or not self.poll_thread.is_alive():
            threading.Thread(target=self._poll_once, name="pygoals-replay", daemon=True).start()

    reset_queue = replay_all

    def wait_until_drained(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stop.is_set():
            if self.queue.drained():
                return True
            if time.monotonic() >= deadline:
                return False
            self.stop.wait(0.5)
        return False

    # -- shutdown ----------------------------------------------------------
    def shutdown(self, *_args):
        with self._shutdown_lock:
            if self._shut_down:
                return
            self._shut_down = True
        log.info("Shutting down")
        self.stop.set()
        with self._status_cond:
            self._status_cond.notify_all()
        self._poll_now.set()
        self._load_failed.set()
        with self._device_lock:
            cast, self.cast = self.cast, None
            browsers = {id(b): b for b in (self._cast_browser, self._scan_browser) if b is not None}
            self._cast_browser = self._scan_browser = None
        if cast is not None:
            self._release_cast(cast)
        for browser in browsers.values():
            self._stop_browser(browser)
        if self.server is not None:
            try:
                self.server.stop()
            except Exception:
                log.debug("card server stop failed", exc_info=True)
        self._save_seen()
        if self._owns_overlay_dir:
            shutil.rmtree(self.overlay_dir, ignore_errors=True)
        else:
            try:
                cleanup_cards(self.overlay_dir)
            except Exception:
                pass
        self.events.emit(STOPPED)


_rendition_cache = {"options": None, "at": 0.0}
RENDITION_CACHE_SECONDS = 6 * 3600


def available_renditions(pk=None, player=None, fetch_listing=None, http_get=None, force=False):
    """Dropdown options ``[(key, label)]`` from what Brightcove really offers.

    Uses a clip the player already resolved, else looks up the newest goal in
    the NHL listing. Cached for a few hours; falls back to a static list
    (second value False) when offline or without a key.
    """
    import brightcove

    cache = _rendition_cache
    now = time.monotonic()
    if not force and cache["options"] and now - cache["at"] < RENDITION_CACHE_SECONDS:
        return cache["options"], True
    try:
        sources = player.known_sources() if player is not None else None
        if not sources:
            key = pk if pk is not None else policy_key()
            if not key:
                raise RuntimeError("no Brightcove key")
            payload = (fetch_listing or (lambda: get_json(VIDEO_URL)))()
            clips = clips_from_listing(payload)[0]
            if not clips:
                raise RuntimeError("no goal clips in the listing")
            probe = clips[0]
            resolve_clip(probe, http_get=http_get, pk=key)
            sources = getattr(probe, "sources", None)
        options = brightcove.rendition_options(sources or [], http_get=http_get)
        if len(options) <= 1:
            raise RuntimeError("no H.264 renditions offered")
    except Exception as exc:  # noqa: BLE001 - static list instead
        log.info("rendition list unavailable (%s); using the typical NHL list", exc)
        return list(brightcove.STATIC_OPTIONS), False
    cache["options"], cache["at"] = options, now
    return options, True

