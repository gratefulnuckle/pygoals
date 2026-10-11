"""Shared HTTP session: timeouts, bounded retries on 429/5xx, a User-Agent."""

import logging
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from _version import USER_AGENT

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
RETRY_STATUSES = (429, 500, 502, 503, 504)

_session = None
_session_lock = threading.Lock()


def make_session(retries=3, backoff=0.5):
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session


def session():
    global _session
    with _session_lock:
        if _session is None:
            _session = make_session()
        return _session


def get(url, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return session().get(url, **kwargs)


def get_json(url, **kwargs):
    response = get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def get_bytes(url, **kwargs):
    response = get(url, **kwargs)
    response.raise_for_status()
    return response.content
