"""Serve card PNGs on the LAN so Chromecast can GET them. Not 127.0.0.1."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import logging
import socket
import threading
from pathlib import Path

log = logging.getLogger(__name__)


def lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)


class CardServer:
    def __init__(self, directory, bind="0.0.0.0"):
        self.directory = Path(directory)
        self.bind = bind
        self._httpd = None
        self._thread = None
        self.port = None
        self.host_for_clients = lan_ip()

    def start(self):
        directory = self.directory

        class Bound(_Handler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

        self._httpd = ThreadingHTTPServer((self.bind, 0), Bound)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info("card server on http://%s:%s", self.host_for_clients, self.port)
        return self

    def url_for(self, path):
        name = Path(path).name
        return "http://{}:{}/{}".format(self.host_for_clients, self.port, name)

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
