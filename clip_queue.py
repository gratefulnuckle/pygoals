"""Thread-safe play queue and seen-state, independent of Chromecast.

Lifecycle of a clip: ``add`` -> pending -> ``begin_next`` (busy, current) ->
``mark_started`` (seen) -> ``finish_current`` (FINISHED/skip) or
``abort_current`` (load failure). Only one clip is ever "current", which is
what stops overlapping advances.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

from config import load_json, save_json

DEFAULT_SEEN_LIMIT = 5000
DEFAULT_FAILED_TTL = 1800.0


class ClipQueue:
    def __init__(self, seen=(), seen_limit=DEFAULT_SEEN_LIMIT, failed_ttl=DEFAULT_FAILED_TTL, clock=time.monotonic):
        self._lock = threading.RLock()
        self._pending = deque()
        self._queued = set()
        self._seen = OrderedDict()
        self._failed = {}
        self._seen_limit = max(1, int(seen_limit))
        self._failed_ttl = float(failed_ttl)
        self._clock = clock
        self._busy = False
        self._current = None
        self._started = False
        for item in seen or ():
            self._remember(str(item))

    # -- internal -------------------------------------------------------
    def _remember(self, media_id):
        self._seen[media_id] = None
        self._seen.move_to_end(media_id)
        while len(self._seen) > self._seen_limit:
            self._seen.popitem(last=False)

    def _failed_active(self, media_id):
        expiry = self._failed.get(media_id)
        if expiry is None:
            return False
        if self._clock() >= expiry:
            del self._failed[media_id]
            return False
        return True

    # -- queries --------------------------------------------------------
    def is_known(self, media_id):
        with self._lock:
            return media_id in self._queued or media_id in self._seen or self._failed_active(media_id)

    @property
    def busy(self):
        with self._lock:
            return self._busy

    @property
    def current(self):
        with self._lock:
            return self._current

    @property
    def started(self):
        with self._lock:
            return self._busy and self._started

    def pending_count(self):
        with self._lock:
            return len(self._pending)

    def pending(self):
        with self._lock:
            return list(self._pending)

    def drained(self):
        with self._lock:
            return not self._busy and not self._pending

    def seen_ids(self):
        with self._lock:
            return list(self._seen)

    # -- mutations ------------------------------------------------------
    def add(self, clips):
        added = []
        with self._lock:
            for clip in clips:
                media_id = clip.brightcove_id
                if media_id in self._queued or media_id in self._seen or self._failed_active(media_id):
                    continue
                self._pending.append(clip)
                self._queued.add(media_id)
                added.append(clip)
        return added

    def mark_failed(self, media_id, ttl=None):
        with self._lock:
            self._queued.discard(media_id)
            self._failed[media_id] = self._clock() + (self._failed_ttl if ttl is None else ttl)
            if len(self._failed) > self._seen_limit:
                now = self._clock()
                for key in [k for k, v in self._failed.items() if v <= now]:
                    del self._failed[key]

    def begin_next(self):
        """Claim the next clip, or None if one is already current/empty."""
        with self._lock:
            if self._busy or not self._pending:
                return None
            clip = self._pending.popleft()
            self._busy = True
            self._current = clip
            self._started = False
            return clip

    def mark_started(self, clip):
        with self._lock:
            if self._current is not clip:
                return False
            self._started = True
            self._queued.discard(clip.brightcove_id)
            self._remember(clip.brightcove_id)
            return True

    def finish_current(self, matches=None):
        """Release a clip that had started. Returns it, or None (no-op).

        Called on FINISHED/skip; a second call for the same clip is a no-op,
        so duplicate status events cannot advance twice. ``matches(clip)``
        can veto (e.g. the FINISHED was for a different media URL).
        """
        with self._lock:
            if not (self._busy and self._started):
                return None
            if matches is not None and not matches(self._current):
                return None
            clip = self._current
            self._busy = False
            self._current = None
            self._started = False
            return clip

    def abort_current(self):
        """Release whatever is current (load failure, device switch)."""
        with self._lock:
            clip = self._current
            if clip is not None:
                self._queued.discard(clip.brightcove_id)
            self._busy = False
            self._current = None
            self._started = False
            return clip

    def reset(self):
        """Forget everything (Replay all). A playing clip keeps playing."""
        with self._lock:
            self._pending.clear()
            self._queued.clear()
            self._seen.clear()
            self._failed.clear()
            if self._current is not None:
                self._queued.add(self._current.brightcove_id)


class SeenStore:
    """``state.json`` next to the app: the bounded list of played ids."""

    def __init__(self, path, limit=DEFAULT_SEEN_LIMIT):
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()

    def load(self):
        data = load_json(self.path, default={}) or {}
        seen = data.get("seen") if isinstance(data, dict) else None
        if not isinstance(seen, list):
            return []
        return [str(item) for item in seen][-self.limit:]

    def save(self, seen_ids):
        with self._lock:
            save_json(self.path, {"version": 1, "seen": list(seen_ids)[-self.limit:]})
