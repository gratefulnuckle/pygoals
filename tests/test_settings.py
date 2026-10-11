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
                          poll_seconds=30, card_seconds=2.5, show_cards=False, port=8765,
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
            "show_cards": "maybe",
            "known_hosts": "192.168.1.5, bad host!",
            "toast_seconds": "nan",
            "nonsense": "1",
        })
    assert set(info.value.errors) == {"poll_seconds", "port", "log_level", "show_cards",
                                      "known_hosts", "toast_seconds", "nonsense"}


def test_validation_accepts_good_values():
    result = s.validate_values({"poll_seconds": "45", "port": "0", "log_level": "warning",
                                "show_cards": "no", "known_hosts": "192.168.1.5; tv.lan",
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
    assert loaded.port == 0


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
    assert eff.port == 0  # invalid env value ignored
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
