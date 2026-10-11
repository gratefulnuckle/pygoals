import logging

import requests

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


def get_json(url, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def get_bytes(url, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return response.content
