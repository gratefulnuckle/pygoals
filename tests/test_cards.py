import pytest
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


def test_card_video_builds_h264_aac_command(tmp_path):
    import cards

    png = tmp_path / "card-8-abc.png"
    png.write_bytes(b"png")
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"mp4")

    out = cards.card_video(png, 3, exe="ffmpeg", run=run)
    assert out == tmp_path / "card-8-abc.mp4" and out.read_bytes() == b"mp4"
    cmd = seen["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-c:a") + 1] == "aac"
    assert "scale=1920:1080" in cmd[cmd.index("-vf") + 1] and cmd[cmd.index("-t") + 1] == "3.00"
    assert not list(tmp_path.glob("*.part.mp4"))


def test_card_video_without_ffmpeg(tmp_path, monkeypatch):
    import cards

    monkeypatch.setattr(cards, "ffmpeg_exe", lambda: None)
    with pytest.raises(cards.CardVideoUnavailable):
        cards.card_video(tmp_path / "x.png", 3)


def test_cleanup_removes_card_videos(tmp_path):
    import cards

    tmp_path = tmp_path / "cards"
    tmp_path.mkdir()
    for name in ("card-1-a.png", "card-1-a.mp4", "card-2-b.mp4", "idle.png"):
        (tmp_path / name).write_bytes(b"x")
    cards.cleanup_cards(tmp_path, keep=["card-2-b.mp4"])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card-2-b.mp4", "idle.png"]
