import configparser

import pytest

import settings as s
from config import parse_dotenv, load_dotenv


def test_first_load_creates_defaults(tmp_path):
    path = tmp_path / "settings.ini"
    loaded = s.load(path)
    assert loaded == s.Settings()
    assert path.is_file()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    assert parser.get("playback", "poll_seconds") == "60"
    assert parser.get("brightcove", "policy_key") == ""


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "settings.ini"
    original = s.Settings(policy_key="abc%def", device_name="Living Room", device_uuid="u-1",
                          device_host="192.168.1.50", known_hosts=["192.168.1.50", "tv.lan"],
                          poll_seconds=30, card_seconds=2.5, card_mode="image", port=8765,
                          snap_to_tray=False, bar_x=-1200, bar_y=40, notify_goals=False,
                          toast_seconds=9, log_level="DEBUG", log_to_file=False)
    s.save(original, path)
    assert s.load(path) == original
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no temp files


def test_validation_reports_every_bad_field():
    with pytest.raises(s.SettingsError) as info:
        s.validate_values({
            "poll_seconds": "1",
            "port": "70000",
            "log_level": "LOUD",
            "card_mode": "maybe",
            "known_hosts": "192.168.1.5, bad host!",
            "toast_seconds": "nan",
            "nonsense": "1",
        })
    assert set(info.value.errors) == {"poll_seconds", "port", "log_level", "card_mode",
                                      "known_hosts", "toast_seconds", "nonsense"}


def test_validation_accepts_good_values():
    result = s.validate_values({"poll_seconds": "45", "port": "0", "log_level": "warning",
                                "card_mode": "off", "known_hosts": "192.168.1.5; tv.lan",
                                "bar_x": "", "policy_key": "  key  "})
    assert result.poll_seconds == 45.0
    assert result.log_level == "WARNING"
    assert result.show_cards is False
    assert result.known_hosts == ["192.168.1.5", "tv.lan"]
    assert result.bar_x is None
    assert result.policy_key == "key"


def test_bad_values_in_file_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("[playback]\npoll_seconds = fast\ncard_seconds = 3\n[server]\nport = -4\n", encoding="utf-8")
    loaded = s.load(path)
    assert loaded.poll_seconds == 60.0
    assert loaded.card_seconds == 3.0
    assert loaded.port == 8765  # invalid -> default


def test_garbage_file_does_not_crash(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("this is not ini", encoding="utf-8")
    assert s.load(path) == s.Settings()


def test_environment_overrides_ini():
    stored = s.Settings(policy_key="from-ini", poll_seconds=60, device_name="Kitchen")
    eff = s.effective(stored, environ={"BRIGHTCOVE_PK": "from-env", "PYGOALS_POLL_SECONDS": "15",
                                       "PYGOALS_PORT": "bogus"})
    assert eff.policy_key == "from-env"
    assert eff.poll_seconds == 15.0
    assert eff.port == 8765  # invalid env value ignored
    assert eff.device_name == "Kitchen"
    assert stored.policy_key == "from-ini"  # stored copy untouched


def test_as_strings_is_inverse_of_validate():
    original = s.Settings(known_hosts=["a.lan"], bar_x=5, bar_y=6, poll_seconds=12.5)
    assert s.validate_values(s.as_strings(original)) == original


def test_dotenv_parser_and_loader(tmp_path, monkeypatch):
    values = parse_dotenv('# c\nexport A=1\nB="two words"\nC=3 # note\nEMPTY=\nbad line\n')
    assert values == {"A": "1", "B": "two words", "C": "3", "EMPTY": ""}
    env = tmp_path / ".env"
    env.write_text("BRIGHTCOVE_PK=from-dotenv\nPYGOALS_DEVICE=\n", encoding="utf-8")
    monkeypatch.delenv("BRIGHTCOVE_PK", raising=False)
    assert load_dotenv(env) == {"BRIGHTCOVE_PK": "from-dotenv"}
    monkeypatch.setenv("BRIGHTCOVE_PK", "real-env")
    load_dotenv(env)
    import os
    assert os.environ["BRIGHTCOVE_PK"] == "real-env"  # real environment wins


def test_env_device_replaces_saved_device_identity():
    stored = s.Settings(device_name="Kitchen", device_uuid="u-kitchen", device_host="192.168.1.9")
    eff = s.effective(stored, environ={"PYGOALS_DEVICE": "Den"})
    assert (eff.device_name, eff.device_uuid, eff.device_host) == ("Den", "", "")


def test_default_card_port_is_fixed():
    assert s.Settings().port == 8765
    assert "port = 8765" in s.to_text(s.Settings())


def test_log_file_is_utf8_with_bom_and_rolls_old_files(tmp_path):
    import logging

    from config import setup_logging

    path = tmp_path / "logs" / "pygoals.log"
    path.parent.mkdir()
    path.write_bytes("old line without bom\n".encode("utf-8"))
    written = setup_logging("INFO", to_file=True, path=path)
    logging.getLogger("pygoals.test").info("skip All of Saturday\u2019s goals")
    for handler in logging.getLogger().handlers:
        handler.flush()
    data = path.read_bytes()
    assert written == path
    assert data.startswith(b"\xef\xbb\xbf")
    assert "Saturday\u2019s".encode("utf-8") in data
    assert (tmp_path / "logs" / "pygoals.log.1").read_bytes().startswith(b"old line")
    for handler in list(logging.getLogger().handlers):
        if getattr(handler, "_pygoals", False):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_max_height_setting():
    assert s.Settings().max_height == 1080
    assert "max_height = 1080" in s.to_text(s.Settings())
    assert s.validate_values({"max_height": "720"}).max_height == 720
    with pytest.raises(s.SettingsError):
        s.validate_values({"max_height": "100"})


def test_quality_setting():
    assert s.Settings().quality == "auto"
    assert s.validate_values({"quality": "HLS:1080"}).quality == "hls:1080"
    assert s.validate_values({"quality": "hls:adaptive"}).quality == "hls:adaptive"
    with pytest.raises(s.SettingsError):
        s.validate_values({"quality": "best"})


def test_card_mode_default_and_legacy_show_cards(tmp_path):
    assert s.Settings().card_mode == "video" and s.Settings().show_cards is True
    assert s.validate_values({"card_mode": "IMAGE"}).card_mode == "image"
    path = tmp_path / "settings.ini"
    path.write_text("[playback]\nshow_cards = false\n", encoding="utf-8")
    assert s.load(path).card_mode == "off"
    path.write_text("[playback]\nshow_cards = false\ncard_mode = image\n", encoding="utf-8")
    assert s.load(path).card_mode == "image"


def test_receiver_settings():
    d = s.Settings()
    assert (d.receiver_mode, d.receiver_app_id) == ("auto", "")
    r = s.validate_values({"receiver_mode": "Custom", "receiver_app_id": "a7c76189"})
    assert (r.receiver_mode, r.receiver_app_id) == ("custom", "A7C76189")
    assert "[cast]" in s.to_text(r) and "receiver_app_id = A7C76189" in s.to_text(r)
    with pytest.raises(s.SettingsError) as info:
        s.validate_values({"receiver_mode": "chromecast", "receiver_app_id": "XYZ"})
    assert set(info.value.errors) == {"receiver_mode", "receiver_app_id"}


def test_video_overlay_default_off():
    assert s.Settings().video_overlay is False
    assert "video_overlay = false" in s.to_text(s.Settings())
    assert s.validate_values({"video_overlay": "on"}).video_overlay is True
