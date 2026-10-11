import urllib.error
import urllib.request

import pytest

from media_server import CardServer, is_allowed_name, is_loopback, lan_ip


@pytest.fixture
def server(tmp_path):
    (tmp_path / "idle.png").write_bytes(b"idle")
    (tmp_path / "card-8478402-abc123.png").write_bytes(b"card")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    (tmp_path / "other.png").write_bytes(b"other")
    srv = CardServer(tmp_path, bind="127.0.0.1", port=0, host_for_clients="127.0.0.1").start()
    yield srv
    srv.stop()
    srv.stop()  # idempotent


def fetch(srv, path):
    url = "http://127.0.0.1:{}{}".format(srv.port, path)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, b"", exc.headers


def test_serves_only_cards_and_idle(server):
    status, body, headers = fetch(server, "/idle.png")
    assert (status, body) == (200, b"idle")
    assert headers["Content-Type"] == "image/png"
    assert fetch(server, "/card-8478402-abc123.png")[:2] == (200, b"card")
    for path in ("/secret.txt", "/other.png", "/", "/../secret.txt", "/%2e%2e/secret.txt",
                 "/sub/idle.png", "/card-..png"):
        assert fetch(server, path)[0] == 404, path


def test_no_directory_listing(server):
    status, body, _ = fetch(server, "/")
    assert status == 404
    assert b"secret.txt" not in body


def test_url_for_rejects_other_files(server, tmp_path):
    assert server.url_for(tmp_path / "idle.png").endswith("/idle.png")
    with pytest.raises(ValueError):
        server.url_for(tmp_path / "secret.txt")


def test_allowed_names():
    assert is_allowed_name("card-1-a.png")
    assert not is_allowed_name("card-1/../x.png")
    assert not is_allowed_name("Idle.PNG")


def test_loopback_detection_and_lan_ip_fallback():
    assert is_loopback("127.0.0.1")
    assert not is_loopback("192.168.1.20")
    assert not is_loopback("not-an-ip")
    assert lan_ip("127.0.0.1") == "127.0.0.1"
