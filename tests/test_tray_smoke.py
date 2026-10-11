"""Offscreen smoke tests: the tray UI builds, positions itself and exits.

No Chromecast, no network: the player uses fakes and no worker threads.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

import player as player_mod  # noqa: E402
import pygoals  # noqa: E402
from fakes import FakeCast, clip, fake_resolve, listing, make_discover  # noqa: E402
from player import NHLVideoPlayer, PlayerOptions  # noqa: E402
from settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["pygoals-test"])
    from tray_style import apply_dark_theme

    apply_dark_theme(app)
    yield app


@pytest.fixture
def controller(qapp, isolated_home):
    import tray

    args = pygoals.build_parser().parse_args(["--no-log-file"])
    runtime = pygoals.Runtime(args, Settings(), isolated_home / "settings.ini")
    p = NHLVideoPlayer(PlayerOptions(show_cards=False), fetch_listing=lambda: listing(1),
                       discover=make_discover(FakeCast("Living Room"), FakeCast("Den", uuid="den")),
                       resolve=fake_resolve)
    c = tray.TrayApp(qapp, p, runtime, start_threads=False)
    yield c
    c.close()
    p.shutdown()
    for widget in qapp.topLevelWidgets():
        widget.close()
    qapp.processEvents()


def test_menu_and_bar_build(controller, qapp):
    texts = [a.text() for a in controller.menu.actions() if a.text()]
    for expected in ("Nothing playing", "Show media bar", "Skip", "Pause polling", "Chromecast",
                     "Replay all", "Devices\u2026", "Settings\u2026", "Open log", "Quit"):
        assert expected in texts, expected
    assert not controller.now_action.isEnabled()
    controller.start()
    controller.show_playbar(force=True)
    qapp.processEvents()
    bar = controller.playbar
    assert bar.isVisible()
    area = qapp.primaryScreen().availableGeometry()
    assert area.contains(bar.geometry().topLeft())
    assert bar.geometry().bottom() <= area.bottom() - 9  # ~10 px above the taskbar


def test_now_playing_updates_label_tooltip_and_toast(controller, qapp):
    controller.bridge.now_playing.emit(clip(7, team="DET"))
    controller.bridge.new_clips.emit([clip(7, team="DET"), clip(8)])
    qapp.processEvents()
    assert controller.now_action.text().endswith("Goal 7")
    assert "Goal 7" in controller.tray.toolTip()
    assert len(controller.toasts.toasts) == 2
    controller.bridge.error.emit(player_mod.ERR_AUTH, "Brightcove rejected the policy key (HTTP 401)")
    controller.bridge.error.emit(player_mod.ERR_AUTH, "Brightcove rejected the policy key (HTTP 401)")
    qapp.processEvents()
    assert len(controller.toasts.toasts) == 3  # duplicate error suppressed


def test_pause_toggles_menu_text(controller, qapp):
    controller.toggle_polling()
    qapp.processEvents()
    assert controller.pause_action.text() == "Resume polling"
    assert controller.playbar.pause_button.isChecked()
    controller.toggle_polling()
    qapp.processEvents()
    assert controller.pause_action.text() == "Pause polling"


def test_drag_position_is_remembered_and_snaps_back(controller, qapp, isolated_home):
    from PyQt6.QtCore import QPoint

    controller.playbar.moved.emit(QPoint(123, 77))
    assert controller.runtime.stored.bar_position == (123, 77)
    assert controller.runtime.stored.snap_to_tray is False
    assert controller.place_playbar() == (123, 77)
    assert "bar_x = 123" in (isolated_home / "settings.ini").read_text(encoding="utf-8")
    controller.snap_to_tray()
    assert controller.runtime.stored.bar_position is None
    assert controller.place_playbar() != (123, 77)


def test_settings_dialog_validates_and_saves(controller, qapp, isolated_home):
    dialog = controller.open_settings()
    qapp.processEvents()
    dialog.hosts_edit.setText("bad host!")
    assert dialog.save() is False
    assert dialog.error_label.isVisible() or dialog.error_label.text()
    dialog.hosts_edit.setText("192.168.1.50")
    dialog.key_edit.setText("new-key")
    dialog.poll_spin.setValue(30)
    assert dialog.save() is True
    qapp.processEvents()
    assert controller.runtime.stored.policy_key == "new-key"
    assert controller.player.options.poll_seconds == 30
    text = (isolated_home / "settings.ini").read_text(encoding="utf-8")
    assert "policy_key = new-key" in text and "known_hosts = 192.168.1.50" in text


def test_devices_dialog_lists_and_selects(controller, qapp):
    devices = controller.player.discover()
    qapp.processEvents()
    dialog = controller.open_devices()
    qapp.processEvents()
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 1).text() == "Den"
    assert dialog.table.item(0, 3).text() == "192.168.1.50"
    assert controller.player.connect(devices[1])
    controller.bridge.connect_result.emit(devices[1], True)
    qapp.processEvents()
    assert controller.runtime.stored.device_name == "Living Room"
    assert controller.device.name == "Living Room"
    checked = [a.text() for a in controller.device_group.actions() if a.isChecked()]
    assert checked and checked[0].startswith("Living Room")


def test_quit_is_clean(controller, qapp):
    controller.start()
    controller.quit()
    qapp.processEvents()
    assert not controller.playbar.isVisible()


def test_settings_quality_dropdown_uses_live_renditions(controller, qapp, isolated_home, monkeypatch):
    import time as _time

    import player as player_mod

    offered = [("auto", "Auto (best compatible)"), ("hls:1080", "HLS 1080p"), ("mp4:720", "MP4 720p"),
               ("hls:adaptive", "HLS adaptive")]
    monkeypatch.setattr(player_mod, "available_renditions", lambda **kw: (offered, True))
    dialog = controller.open_settings()
    deadline = _time.monotonic() + 5
    while dialog.quality_combo.count() != len(offered) and _time.monotonic() < deadline:
        qapp.processEvents()
        _time.sleep(0.02)
    labels = [dialog.quality_combo.itemText(i) for i in range(dialog.quality_combo.count())]
    assert labels == [label for _key, label in offered]
    assert "recent goal" in dialog.quality_note.text()
    dialog.quality_combo.setCurrentIndex(dialog.quality_combo.findData("hls:1080"))
    dialog.height_combo.setCurrentIndex(dialog.height_combo.findData("720"))
    dialog.level_combo.setCurrentIndex(dialog.level_combo.findData("DEBUG"))
    assert dialog.card_mode_combo.currentData() == "video"
    dialog.card_mode_combo.setCurrentIndex(dialog.card_mode_combo.findData("off"))
    assert not dialog.card_spin.isEnabled()
    dialog.card_mode_combo.setCurrentIndex(dialog.card_mode_combo.findData("image"))
    dialog.card_spin.setValue(3)
    dialog.receiver_combo.setCurrentIndex(dialog.receiver_combo.findData("custom"))
    dialog.app_id_edit.setText("a7c76189")
    assert dialog.video_overlay.isChecked() is False
    dialog.video_overlay.setChecked(True)
    assert dialog.save() is True
    qapp.processEvents()
    assert controller.player.options.quality == "hls:1080"
    assert controller.player.options.max_height == 720
    assert controller.player.options.card_mode == "image" and controller.player.options.card_seconds == 3
    text = (isolated_home / "settings.ini").read_text(encoding="utf-8")
    assert "quality = hls:1080" in text and "max_height = 720" in text and "level = DEBUG" in text
    assert "card_mode = image" in text and "card_seconds = 3" in text
    assert "receiver_mode = custom" in text and "receiver_app_id = A7C76189" in text
    assert controller.player.options.receiver_app_id == "A7C76189"
    assert controller.player.options.video_overlay is True and "video_overlay = true" in text
