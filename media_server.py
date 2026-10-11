"""Serve player cards on the LAN so the Chromecast can GET them.

Only ``idle.png``, ``card-*.png`` and ``card-*.mp4`` in the card directory are
served (single byte ranges supported for the MP4s); no
directory listings, no other files, no path traversal.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import logging
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger(__name__)

ALLOWED_NAME = re.compile(r"^(idle\.png|card-[A-Za-z0-9_-]+\.(png|mp4))$")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def lan_ip(target=None):
    """Local address used to reach ``target`` (the Chromecast) or the internet.

    Connecting a UDP socket sends no packets; it just asks the OS routing
    table which interface it would use.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target or "8.8.8.8", 8009 if target else 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def is_loopback(ip):
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def is_allowed_name(name):
    return bool(ALLOWED_NAME.match(name or ""))


class _CardHandler(BaseHTTPRequestHandler):
    directory = Path(".")
    server_version = "pygoals-cards"

    on_fetch = None  # set per server: callback(name, client_ip)

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _resolve(self):
        raw = urlsplit(self.path).path
        name = unquote(raw).lstrip("/")
        if "/" in name or "\\" in name or not is_allowed_name(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None

    def _respond(self, include_body):
        path = self._resolve()
        client = self.client_address[0] if self.client_address else "?"
        name = unquote(urlsplit(self.path).path).lstrip("/")
        if path is None:
            log.info("card server: %s %s %s -> 404", client, self.command, name[:60])
            self.send_error(404, "Not Found")
            return
        log.info("card server: %s %s %s -> 200", client, self.command, path.name)
        if self.on_fetch is not None:
            self.on_fetch(path.name, client)
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "Not Found")
            return
        total = len(data)
        start, end = 0, total - 1
        match = _RANGE_RE.match(self.headers.get("Range", "").strip()) if self.headers else None
        if match and total and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), total - 1) if match.group(2) else total - 1
            else:
                start = max(0, total - int(match.group(2)))
            if start > end or start >= total:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */{}".format(total))
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, total))
            data = data[start:end + 1]
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4" if path.suffix == ".mp4" else "image/png")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_GET(self):  # noqa: N802 (http.server API)
        self._respond(True)

    def do_HEAD(self):  # noqa: N802
        self._respond(False)


class CardServer:
    def __init__(self, directory, bind="0.0.0.0", port=0, host_for_clients=None):
        self.directory = Path(directory)
        self.bind = bind
        self.requested_port = int(port or 0)
        self._httpd = None
        self._thread = None
        self.port = None
        self.host_for_clients = host_for_clients or lan_ip()
        self._stopped = False
        self._fetched = {}
        self._fetch_cond = threading.Condition()

    def _record_fetch(self, name, client):
        with self._fetch_cond:
            self._fetched[name] = client
            self._fetch_cond.notify_all()

    def was_fetched(self, name):
        with self._fetch_cond:
            return name in self._fetched

    def wait_for_fetch(self, name, timeout, stop=None):
        """True once a client GETs ``name`` (the Chromecast fetching the card)."""
        deadline = time.monotonic() + timeout
        with self._fetch_cond:
            while name not in self._fetched:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (stop is not None and stop.is_set()):
                    return False
                self._fetch_cond.wait(min(0.25, remaining))
            return True

    def start(self):
        directory = self.directory

        class Bound(_CardHandler):
            pass

        Bound.directory = directory
        Bound.on_fetch = staticmethod(self._record_fetch)
        try:
            self._httpd = ThreadingHTTPServer((self.bind, self.requested_port), Bound)
        except OSError as exc:
            if not self.requested_port:
                raise
            log.warning("card port %s unavailable (%s); using a random port this run", self.requested_port, exc)
            self._httpd = ThreadingHTTPServer((self.bind, 0), Bound)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="pygoals-cards", daemon=True)
        self._thread.start()
        log.info("card server on http://%s:%s", self.host_for_clients, self.port)
        return self

    def set_client_target(self, cast_host):
        """Pick the interface that routes to the Chromecast. Returns the IP."""
        self.host_for_clients = lan_ip(cast_host)
        log.info("card server reachable at http://%s:%s", self.host_for_clients, self.port)
        return self.host_for_clients

    def url_for(self, path):
        name = Path(path).name
        if not is_allowed_name(name):
            raise ValueError("refusing to serve " + name)
        return "http://{}:{}/{}".format(self.host_for_clients, self.port, name)

    def stop(self):
        if self._stopped or self._httpd is None:
            return
        self._stopped = True
        self._httpd.shutdown()
        self._httpd.server_close()
