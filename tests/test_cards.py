import io
from pathlib import Path

from PIL import Image

from cards import render_card


def test_render_card_uses_temp_dir_and_rgba_logo(tmp_path):
    rgb = Image.new("RGB", (64, 64), "red")
    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    png = buf.getvalue()

    def fake_json(_url):
        return {"headshot": "http://example.test/head.png"}

    def fake_bytes(_url):
        return png

    path = render_card(
        "8478402",
        "PIT",
        "Crosby scores",
        out_dir=tmp_path,
        http_get_json=fake_json,
        http_get_bytes=fake_bytes,
    )
    assert Path(path).is_file()
    assert path.name.startswith("card-")
    assert "Users/jonat/image.png" not in str(path).replace("\\", "/")
    Image.open(path).verify()
