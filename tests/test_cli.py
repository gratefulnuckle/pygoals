import sys
import types

import pytest

import pygoals
from brightcove import policy_key, set_policy_key
from fakes import FakeCast
from player import DeviceInfo
from pygoals import Runtime, build_parser, choose_device, main
from settings import Settings


def test_parser_flags():
    args = build_parser().parse_args(["--dry-run", "--quiet", "--device", "Kitchen", "--poll-seconds", "5"])
    assert args.dry_run
    assert args.quiet
    assert args.device == "Kitchen"
    assert args.poll_seconds == 5.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "abc", "100000"])
def test_poll_seconds_validated(value):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--poll-seconds", value])


def test_tray_flag_is_accepted_noop():
    args = build_parser().parse_args(["--tray"])
    assert args.tray and not args.cli


def test_policy_key_from_env(monkeypatch):
    monkeypatch.delenv("BRIGHTCOVE_PK", raising=False)
    assert policy_key() == ""
    set_policy_key("from-ini")
    assert policy_key() == "from-ini"
    monkeypatch.setenv("BRIGHTCOVE_PK", "test-key")
    assert policy_key() == "test-key"


def test_missing_pk_in_console_mode_exits_2(isolated_home):
    assert main(["--cli", "--quiet", "--no-log-file"]) == 2
    assert (isolated_home / "settings.ini").is_file()  # created next to the app


def test_no_args_launches_tray(monkeypatch):
    calls = []
    fake = types.ModuleType("tray")
    fake.run_tray = lambda runtime: calls.append(runtime) or 0
    monkeypatch.setitem(sys.modules, "tray", fake)
    assert main(["--no-log-file"]) == 0
    assert len(calls) == 1
    assert calls[0].args.cli is False


def test_falls_back_to_console_without_pyqt(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "tray", None)  # makes "import tray" raise ImportError
    assert main(["--no-log-file", "--quiet"]) == 2  # console mode, then missing key
    assert "falling back to console" in caplog.text


@pytest.mark.parametrize("flag", ["--dry-run", "--list-devices", "--once", "--cli"])
def test_headless_flags_never_import_tray(monkeypatch, flag):
    fake = types.ModuleType("tray")

    def boom(runtime):
        raise AssertionError("tray must not start")

    fake.run_tray = boom
    monkeypatch.setitem(sys.modules, "tray", fake)
    monkeypatch.setattr(pygoals, "run_console", lambda runtime: 0)
    assert main([flag, "--no-log-file"]) == 0


def test_cli_overrides_beat_env_and_ini(monkeypatch):
    monkeypatch.setenv("PYGOALS_POLL_SECONDS", "20")
    args = build_parser().parse_args(["--poll-seconds", "30", "--device", "Den", "--no-overlay"])
    runtime = Runtime(args, Settings(poll_seconds=90, device_name="Kitchen", device_uuid="u"), "x.ini")
    eff = runtime.effective()
    assert eff.poll_seconds == 30
    assert eff.device_name == "Den" and eff.device_uuid == ""
    assert eff.show_cards is False
    args = build_parser().parse_args([])
    assert Runtime(args, Settings(poll_seconds=90), "x.ini").effective().poll_seconds == 20


def _devices(*names):
    return [DeviceInfo.from_cast(FakeCast(name, uuid=name.lower())) for name in names]


def test_choose_device_no_console_exits_2():
    def no_stdin(_prompt):
        raise EOFError

    device, code = choose_device(_devices("A", "B"), Settings(), input_fn=no_stdin, out=lambda *_: None)
    assert device is None and code == 2


def test_choose_device_reprompts_then_accepts():
    answers = iter(["x", "9", "2"])
    device, code = choose_device(_devices("A", "B"), Settings(), input_fn=lambda _p: next(answers),
                                 out=lambda *_: None)
    assert device.name == "B" and code is None


def test_choose_device_from_settings_and_single_device():
    devices = _devices("Living Room", "Kitchen")
    device, _ = choose_device(devices, Settings(device_uuid="kitchen"))
    assert device.name == "Kitchen"
    device, code = choose_device(devices, Settings(device_name="Garage"))
    assert device is None and code == 1
    device, _ = choose_device(_devices("Only"), Settings(), input_fn=lambda _p: pytest.fail("prompted"))
    assert device.name == "Only"


def test_frozen_paths_live_next_to_the_exe(tmp_path, monkeypatch):
    import sys

    import config

    exe = tmp_path / "dist" / "pygoals" / "pygoals.exe"
    exe.parent.mkdir(parents=True)
    (exe.parent / "_internal" / "assets").mkdir(parents=True)
    (exe.parent / "_internal" / "assets" / "logo.png").write_bytes(b"png")
    monkeypatch.delenv("PYGOALS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(exe.parent / "_internal"), raising=False)
    assert config.app_dir() == exe.parent
    assert config.settings_path().parent == exe.parent
    assert config.asset_path("logo.png") == exe.parent / "_internal" / "assets" / "logo.png"


def test_cli_exe_defaults_to_console_mode(monkeypatch):
    import sys

    import pygoals

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\apps\pygoals\pygoals-cli.exe")
    assert pygoals._frozen_cli_default(["--device", "onn"]) == ["--cli", "--device", "onn"]
    assert pygoals._frozen_cli_default(["--tray"]) == ["--tray"]
    monkeypatch.setattr(sys, "executable", r"C:\apps\pygoals\pygoals.exe")
    assert pygoals._frozen_cli_default(["--device", "onn"]) == ["--device", "onn"]
