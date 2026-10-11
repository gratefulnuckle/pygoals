import io
from pathlib import Path

from PIL import Image, ImageDraw

from cards import _font, cleanup_cards, render_card, wrap_text
from team_theme import THEMES, contrast_ratio, text_color_for


def _png(color="red", mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def test_render_card_uses_temp_dir_and_rgba_logo(tmp_path):
    png = _png()

    path = render_card(
        "8478402", "PIT", "Crosby scores", out_dir=tmp_path,
        http_get_json=lambda _url: {"headshot": "http://example.test/head.png"},
        http_get_bytes=lambda _url: png,
    )
    assert Path(path).is_file()
    assert path.name.startswith("card-8478402-")
    assert "Users/jonat/image.png" not in str(path).replace("\\", "/")
    Image.open(path).verify()


def test_card_names_are_unique_per_render(tmp_path):
    kwargs = dict(out_dir=tmp_path, http_get_json=lambda _u: {}, http_get_bytes=lambda _u: b"")
    first = render_card("1", "TOR", "A", **kwargs)
    second = render_card("1", "TOR", "B", **kwargs)
    assert first != second
    assert cleanup_cards(tmp_path, keep=[second]) == 1
    assert [p.name for p in tmp_path.glob("card-*.png")] == [second.name]


def test_detroit_title_is_not_white_on_white():
    secondary = THEMES["DET"]["secondary"]
    assert secondary.upper() == "#FFFFFF"
    color = text_color_for(secondary)
    assert color != "#FFFFFF"
    assert contrast_ratio(color, secondary) >= 4.5


def test_every_team_title_is_readable():
    for code, theme in THEMES.items():
        color = text_color_for(theme["secondary"])
        assert contrast_ratio(color, theme["secondary"]) >= 4.5, code


def test_detroit_card_pixels_use_dark_text(tmp_path):
    path = render_card(None, "DET", "Larkin scores on the power play", out_dir=tmp_path,
                       http_get_json=lambda _u: {}, http_get_bytes=lambda _u: b"")
    image = Image.open(path).convert("RGB")
    band = image.crop((0, 440, 1280, 520))
    darkest, _brightest = band.convert("L").getextrema()
    assert darkest < 60  # dark text drawn on the white band


def test_long_titles_wrap_within_width():
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = _font(32)
    title = "An absolutely ridiculous between-the-legs goal " * 6
    lines = wrap_text(draw, title, font, 1160)
    assert 1 < len(lines) <= 3
    assert lines[-1].endswith("\u2026")
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        assert bbox[2] - bbox[0] <= 1160
