"""Serve player-card PNGs on the LAN so the Chromecast can GET them.

Only ``idle.png`` and ``card-*.png`` in the card directory are served; no
directory listings, no other files, no path traversal.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import logging
import re
import socket
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger(__name__)

ALLOWED_NAME = re.compile(r"^(idle\.png|card-[A-Za-z0-9_-]+\.png)$")


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
        if path is None:
            self.send_error(404, "Not Found")
            return
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
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

    def start(self):
        directory = self.directory

        class Bound(_CardHandler):
            pass

        Bound.directory = directory
        self._httpd = ThreadingHTTPServer((self.bind, self.requested_port), Bound)
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
