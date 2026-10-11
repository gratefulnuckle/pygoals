"""PyQt6 system-tray front end (the default mode).

The Chromecast player runs on worker threads; its events are re-emitted as Qt
signals by ``Bridge`` so every widget update happens on the GUI thread.
"""

from __future__ import annotations

import io
import logging
import signal
import threading
import time

from PyQt6.QtCore import QObject, QPoint, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCursor, QDesktopServices, QGuiApplication, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import player as player_mod
import settings as settings_mod
from _version import __version__
from brightcove import policy_key
from config import app_dir, set_log_level
from team_theme import accent_on_dark
from tray_geometry import anchor_position, stack_positions, visible_on_any
from tray_style import DANGER, WARN, apply_dark_theme, glyph_icon, style_menu, tray_icon
from tray_widgets import DevicesDialog, PlaybarWindow, SettingsDialog, ToastManager

log = logging.getLogger("pygoals.tray")

ERROR_TITLES = {
    player_mod.ERR_AUTH: "Brightcove key rejected",
    player_mod.ERR_NO_KEY: "Brightcove key needed",
    player_mod.ERR_NO_DEVICE: "No Chromecast",
    player_mod.ERR_LOOPBACK: "Cards unreachable",
    player_mod.ERR_NETWORK: "Network problem",
    player_mod.ERR_PLAYBACK: "Playback problem",
}
REFOCUS_GUARD = 0.35  # s: ignore the tray click that just closed the bar


def _rect_tuple(rect):
    return (rect.x(), rect.y(), rect.width(), rect.height())


class Bridge(QObject):
    """Player events (any thread) -> Qt signals (GUI thread)."""

    status = pyqtSignal(str)
    now_playing = pyqtSignal(object)
    new_clips = pyqtSignal(object)
    error = pyqtSignal(str, str)
    devices = pyqtSignal(object)
    device = pyqtSignal(object)
    polling = pyqtSignal(bool)
    discovering = pyqtSignal(bool)
    stopped = pyqtSignal()
    art = pyqtSignal(str, object)
    connect_result = pyqtSignal(object, bool)
    setup_needed = pyqtSignal(str)

    def attach(self, events):
        events.subscribe(player_mod.STATUS, lambda text: self.status.emit(text))
        events.subscribe(player_mod.NOW_PLAYING, lambda clip: self.now_playing.emit(clip))
        events.subscribe(player_mod.NEW_CLIPS, lambda clips: self.new_clips.emit(clips))
        events.subscribe(player_mod.ERROR, lambda kind, message: self.error.emit(kind, message))
        events.subscribe(player_mod.DEVICES, lambda devices: self.devices.emit(devices))
        events.subscribe(player_mod.DEVICE, lambda device: self.device.emit(device))
        events.subscribe(player_mod.POLLING, lambda enabled: self.polling.emit(enabled))
        events.subscribe(player_mod.DISCOVERING, lambda active: self.discovering.emit(active))
        events.subscribe(player_mod.STOPPED, lambda: self.stopped.emit())


class TrayApp(QObject):
    def __init__(self, app, player, runtime, start_threads=True):
        super().__init__()
        self.app = app
        self.player = player
        self.runtime = runtime
        self.start_threads = start_threads
        self.current_clip = None
        self.device = None
        self.polling_enabled = True
        self.status_text = "Starting"
        self.last_error = None
        self._error_seen = {}
        self._settings_dialog = None
        self._devices_dialog = None
        self._quitting = False

        self.bridge = Bridge()
        self.bridge.attach(player.events)

        self.tray = QSystemTrayIcon(tray_icon("idle"), self)
        self.playbar = PlaybarWindow()
        self.toasts = ToastManager(self._toast_positions)
        self.device_menu = style_menu(QMenu("Chromecast"))
        self.device_group = QActionGroup(self.device_menu)
        self.device_group.setExclusive(True)
        self.menu = style_menu(QMenu())
        self._build_menu()
        self._wire()
        self._rebuild_device_menu([])
        self._apply_ui_settings()
        self._refresh_texts()

    # -- settings ----------------------------------------------------------
    @property
    def settings(self):
        return self.runtime.effective()

    def _apply_ui_settings(self):
        eff = self.settings
        self.playbar.auto_hide = bool(eff.snap_to_tray)
        self.playbar.set_pinned(not eff.snap_to_tray and eff.bar_position is not None)

    # -- construction --------------------------------------------------------
    def _build_menu(self):
        menu = self.menu
        self.now_action = QAction("Nothing playing", menu)
        self.now_action.setEnabled(False)
        menu.addAction(self.now_action)
        menu.addSeparator()
        self.show_action = QAction(glyph_icon("pin"), "Show media bar", menu)
        self.skip_action = QAction(glyph_icon("skip"), "Skip", menu)
        self.pause_action = QAction(glyph_icon("pause"), "Pause polling", menu)
        self.replay_action = QAction(glyph_icon("replay"), "Replay all", menu)
        self.devices_action = QAction(glyph_icon("device"), "Devices\u2026", menu)
        self.settings_action = QAction(glyph_icon("settings"), "Settings\u2026", menu)
        self.log_action = QAction(glyph_icon("log"), "Open log", menu)
        self.quit_action = QAction(glyph_icon("power"), "Quit", menu)
        menu.addAction(self.show_action)
        menu.addAction(self.skip_action)
        menu.addAction(self.pause_action)
        self.device_menu.setIcon(glyph_icon("device"))
        menu.addMenu(self.device_menu)
        menu.addAction(self.replay_action)
        menu.addSeparator()
        menu.addAction(self.devices_action)
        menu.addAction(self.settings_action)
        menu.addAction(self.log_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self.tray.setContextMenu(menu)
        self.playbar.device_button.setMenu(self.device_menu)

    def _wire(self):
        b = self.bridge
        b.status.connect(self._on_status)
        b.now_playing.connect(self._on_now_playing)
        b.new_clips.connect(self._on_new_clips)
        b.error.connect(self._on_error)
        b.devices.connect(self._on_devices)
        b.device.connect(self._on_device)
        b.polling.connect(self._on_polling)
        b.discovering.connect(self._on_discovering)
        b.art.connect(self._on_art)
        b.connect_result.connect(self._on_connect_result)
        b.setup_needed.connect(self._on_setup_needed)

        self.tray.activated.connect(self._on_tray_activated)
        self.show_action.triggered.connect(lambda: self.show_playbar(force=True))
        self.skip_action.triggered.connect(self.skip)
        self.pause_action.triggered.connect(self.toggle_polling)
        self.replay_action.triggered.connect(self.replay_all)
        self.devices_action.triggered.connect(self.open_devices)
        self.settings_action.triggered.connect(self.open_settings)
        self.log_action.triggered.connect(self.open_log)
        self.quit_action.triggered.connect(self.quit)

        pb = self.playbar
        pb.skip_button.clicked.connect(self.skip)
        pb.pause_button.clicked.connect(self.toggle_polling)
        pb.replay_button.clicked.connect(self.replay_all)
        pb.settings_button.clicked.connect(self.open_settings)
        pb.quit_button.clicked.connect(self.quit)
        pb.moved.connect(self._on_bar_moved)
        pb.snap_requested.connect(self.snap_to_tray)

    def _rebuild_device_menu(self, devices):
        menu = self.device_menu
        menu.clear()
        for action in list(self.device_group.actions()):
            self.device_group.removeAction(action)
        active_uuid = self.device.uuid if self.device else ""
        if devices:
            for device in devices:
                label = device.name + ("  \u00b7  " + device.host if device.host else "")
                action = QAction(label, menu)
                action.setCheckable(True)
                action.setChecked(bool(active_uuid) and device.uuid == active_uuid)
                action.triggered.connect(lambda _checked=False, d=device: self.select_device(d))
                self.device_group.addAction(action)
                menu.addAction(action)
        else:
            empty = QAction("No devices yet", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
        menu.addSeparator()
        scan = QAction(glyph_icon("scan"), "Scan for devices", menu)
        scan.triggered.connect(self.scan_devices)
        menu.addAction(scan)
        manage = QAction(glyph_icon("device"), "Manage devices\u2026", menu)
        manage.triggered.connect(self.open_devices)
        menu.addAction(manage)

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        self.tray.show()
        if self.settings.show_bar_on_start:
            QTimer.singleShot(300, lambda: self.show_playbar(force=True))
        if self.start_threads:
            threading.Thread(target=self._boot, name="pygoals-boot", daemon=True).start()

    def _boot(self):
        """Worker thread: first poll, discovery, connect to the saved device."""
        player = self.player
        if not policy_key():
            self.bridge.setup_needed.emit("key")
        else:
            player._poll_once()
        devices = player.discover()
        eff = self.settings
        device = player_mod.match_device(devices, eff.device_uuid, eff.device_name, eff.device_host)
        if device is None and devices and not (eff.device_uuid or eff.device_name or eff.device_host) \
                and len(devices) == 1:
            device = devices[0]
        if device is not None:
            ok = player.connect(device)
            self.bridge.connect_result.emit(device, ok)
        elif devices:
            self.bridge.setup_needed.emit("device")
        player.start_polling()
        player.kick()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self.playbar.hide()
        self.toasts.clear()
        for dialog in (self._settings_dialog, self._devices_dialog):
            if dialog is not None:
                dialog.reject()
        self.tray.hide()
        self.app.quit()

    def close(self):
        self.toasts.clear()
        self.playbar.close()
        self.tray.hide()

    # -- actions ---------------------------------------------------------------
    def skip(self):
        self.player.skip()

    def toggle_polling(self):
        self.player.set_polling(not self.player.polling_enabled.is_set())

    def replay_all(self):
        self.player.replay_all()

    def scan_devices(self):
        threading.Thread(target=self.player.discover, name="pygoals-scan", daemon=True).start()

    def select_device(self, device):
        def work():
            ok = self.player.connect(device)
            self.bridge.connect_result.emit(device, ok)
            if ok:
                self.player.kick()

        threading.Thread(target=work, name="pygoals-connect", daemon=True).start()

    def open_log(self):
        target = self.runtime.log_file
        if target is None or not target.exists():
            target = app_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # -- pages -----------------------------------------------------------------
    def open_settings(self):
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return self._settings_dialog
        dialog = SettingsDialog(self.runtime.stored, self.runtime.settings_path,
                                key_from_env=settings_mod.key_from_environment())
        dialog.saved.connect(self.apply_settings)
        dialog.open_devices.connect(self.open_devices)
        dialog.open_file.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.runtime.settings_path))))
        dialog.finished.connect(lambda _r: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        self._center(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def open_devices(self):
        if self._devices_dialog is not None:
            self._devices_dialog.raise_()
            self._devices_dialog.activateWindow()
            return self._devices_dialog
        dialog = DevicesDialog()
        dialog.set_devices(self.player.devices, self.device.uuid if self.device else "")
        dialog.scan_requested.connect(self.scan_devices)
        dialog.device_chosen.connect(self.select_device)
        dialog.finished.connect(lambda _r: setattr(self, "_devices_dialog", None))
        self._devices_dialog = dialog
        self._center(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if not self.player.devices:
            self.scan_devices()
        return dialog

    def apply_settings(self, stored):
        """Persisted already by the dialog; apply what can change live."""
        old = self.settings
        self.runtime.stored = stored
        eff = self.settings
        self.runtime.apply_to_player(self.player)
        set_log_level(eff.log_level)
        self._apply_ui_settings()
        if eff.policy_key != old.policy_key:
            self.player._auth_reported = False
            self.player.poll_now()
        if eff.snap_to_tray and self.playbar.isVisible():
            self.show_playbar(force=True)
        if eff.port != old.port:
            self.notify("Settings saved", "The card port changes after a restart.", WARN)
        else:
            self.notify("Settings saved", "Applied.", None)

    # -- media bar placement ---------------------------------------------------
    def _icon_rect(self):
        rect = self.tray.geometry()
        if rect.isValid() and rect.width() > 0:
            return _rect_tuple(rect)
        return None

    def _screen_for(self, icon):
        screen = None
        if icon is not None:
            screen = QGuiApplication.screenAt(QPoint(icon[0] + icon[2] // 2, icon[1] + icon[3] // 2))
        if screen is None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return screen

    def anchor_for(self, size):
        icon = self._icon_rect()
        screen = self._screen_for(icon)
        return anchor_position(size, icon, _rect_tuple(screen.geometry()),
                               _rect_tuple(screen.availableGeometry()), margin=10)

    def _toast_positions(self, sizes):
        icon = self._icon_rect()
        screen = self._screen_for(icon)
        reserved = 0
        if self.playbar.isVisible() and self.settings.snap_to_tray:
            reserved = self.playbar.height()
        return stack_positions(sizes, icon, _rect_tuple(screen.geometry()),
                               _rect_tuple(screen.availableGeometry()), margin=10, gap=4, reserved=reserved)

    def place_playbar(self):
        size = (self.playbar.width(), self.playbar.height())
        eff = self.settings
        if not eff.snap_to_tray and eff.bar_position is not None:
            avails = [_rect_tuple(s.availableGeometry()) for s in QGuiApplication.screens()]
            if visible_on_any(eff.bar_position, size, avails):
                self.playbar.move(*eff.bar_position)
                return eff.bar_position
        x, y, _edge = self.anchor_for(size)
        self.playbar.move(x, y)
        return (x, y)

    def show_playbar(self, force=False):
        if self.playbar.isVisible() and not force:
            self.playbar.hide()
            return
        if not force and time.monotonic() - self.playbar.last_hidden_at < REFOCUS_GUARD:
            return  # this click is the one that just closed it
        self.place_playbar()
        self.playbar.show()
        self.playbar.raise_()
        self.playbar.activateWindow()
        self.toasts.relayout()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_playbar()

    def _on_bar_moved(self, pos):
        stored = self.runtime.stored.copy(bar_x=pos.x(), bar_y=pos.y(), snap_to_tray=False)
        self._save_stored(stored)
        self._apply_ui_settings()

    def snap_to_tray(self):
        stored = self.runtime.stored.copy(bar_x=None, bar_y=None, snap_to_tray=True)
        self._save_stored(stored)
        self._apply_ui_settings()
        self.place_playbar()

    def _save_stored(self, stored):
        self.runtime.stored = stored
        try:
            settings_mod.save(stored, self.runtime.settings_path)
        except OSError as exc:
            log.warning("could not save settings: %s", exc)

    def _center(self, dialog):
        dialog.adjustSize()
        screen = self._screen_for(self._icon_rect())
        area = screen.availableGeometry()
        dialog.move(area.x() + (area.width() - dialog.width()) // 2,
                    area.y() + (area.height() - dialog.height()) // 2)

    # -- notifications ---------------------------------------------------------
    def notify(self, title, body, accent, seconds=None, on_click=None):
        seconds = seconds or self.settings.toast_seconds
        return self.toasts.show(title, body, accent=accent or "#5B8CFF", seconds=seconds, on_click=on_click)

    # -- signal handlers (GUI thread) -------------------------------------------
    def _on_status(self, text):
        self.status_text = text
        self._refresh_texts()

    def _on_now_playing(self, clip):
        self.current_clip = clip
        if clip is None:
            self.playbar.set_now_playing("Waiting for goals", self._subtitle(), None)
            self.playbar.set_art(None)
        else:
            self.last_error = None
            accent = accent_on_dark(clip.team)
            self.playbar.set_now_playing(clip.title, self._subtitle(clip), accent)
            self.playbar.set_art(None, (clip.team or "")[:3])
            self._fetch_art(clip)
        self._refresh_texts()

    def _fetch_art(self, clip):
        def work():
            try:
                from cards import fetch_player_art

                headshot, logo = fetch_player_art(clip.player_id, clip.team)
                image = headshot or logo
                if image is None:
                    return
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                self.bridge.art.emit(clip.brightcove_id, buffer.getvalue())
            except Exception:
                log.debug("art fetch failed", exc_info=True)

        threading.Thread(target=work, name="pygoals-art", daemon=True).start()

    def _on_art(self, media_id, data):
        if self.current_clip is None or self.current_clip.brightcove_id != media_id:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.playbar.set_art(pixmap)

    def _on_new_clips(self, clips):
        if not self.settings.notify_goals or not clips:
            return
        for clip in clips[:3]:
            self.notify("GOAL \u2014 {}".format(clip.team or "NHL"), clip.title, accent_on_dark(clip.team))
        if len(clips) > 3:
            self.notify("{} more goals queued".format(len(clips) - 3), "Open the media bar to watch.", None)

    def _on_error(self, kind, message):
        self.last_error = (kind, message)
        self.tray.setIcon(tray_icon("error"))
        self._refresh_texts()
        if not self.settings.notify_errors:
            return
        now = time.monotonic()
        key = (kind, message)
        if now - self._error_seen.get(key, -1e9) < 60:
            return
        self._error_seen[key] = now
        on_click = None
        if kind in (player_mod.ERR_AUTH, player_mod.ERR_NO_KEY):
            on_click = self.open_settings
        elif kind == player_mod.ERR_NO_DEVICE:
            on_click = self.open_devices
        accent = WARN if kind in (player_mod.ERR_LOOPBACK, player_mod.ERR_NETWORK) else DANGER
        self.notify(ERROR_TITLES.get(kind, "pygoals"), message, accent, seconds=max(8, self.settings.toast_seconds),
                    on_click=on_click)

    def _on_devices(self, devices):
        self._rebuild_device_menu(devices)
        if self._devices_dialog is not None:
            self._devices_dialog.set_devices(devices, self.device.uuid if self.device else "")

    def _on_device(self, device):
        self.device = device
        self.last_error = None
        self._rebuild_device_menu(self.player.devices)
        if self._devices_dialog is not None:
            self._devices_dialog.set_devices(self.player.devices, device.uuid if device else "")
        self._refresh_texts()

    def _on_connect_result(self, device, ok):
        if ok:
            stored = self.runtime.stored.copy(device_name=device.name, device_uuid=device.uuid,
                                              device_host=device.host)
            if (stored.device_name, stored.device_uuid, stored.device_host) != (
                    self.runtime.stored.device_name, self.runtime.stored.device_uuid,
                    self.runtime.stored.device_host):
                self._save_stored(stored)
            if self._devices_dialog is not None:
                self._devices_dialog.set_status("Playing on {}.".format(device.name))
        elif self._devices_dialog is not None:
            self._devices_dialog.set_status("Could not connect to {}.".format(device.name), error=True)

    def _on_setup_needed(self, what):
        if what == "key":
            self.notify("Welcome to pygoals", "Add your Brightcove policy key to start.", None)
            self.open_settings()
        elif what == "device":
            self.notify("Pick a Chromecast", "Choose where goals should play.", None)
            self.open_devices()

    def _on_polling(self, enabled):
        self.polling_enabled = bool(enabled)
        self.playbar.set_polling(enabled)
        self.pause_action.setText("Pause polling" if enabled else "Resume polling")
        self.pause_action.setIcon(glyph_icon("pause" if enabled else "play"))
        self._refresh_texts()

    def _on_discovering(self, active):
        if self._devices_dialog is not None:
            self._devices_dialog.set_scanning(active)
        if active:
            self.playbar.set_subtitle("Scanning for Chromecasts\u2026")
        else:
            self._refresh_texts()

    # -- text ------------------------------------------------------------------
    def _subtitle(self, clip=None):
        parts = []
        if clip is not None and clip.team:
            parts.append(clip.team)
        parts.append(self.device.name if self.device else "No device")
        if not self.polling_enabled:
            parts.append("polling paused")
        elif clip is None:
            parts.append(self.status_text)
        return "  \u00b7  ".join(parts)

    def _refresh_texts(self):
        clip = self.current_clip
        title = clip.title if clip else "Nothing playing"
        self.now_action.setText(("\u25B6  " + title) if clip else title)
        if clip is None:
            self.playbar.set_subtitle(self._subtitle())
        else:
            self.playbar.set_subtitle(self._subtitle(clip))
        if self.last_error:
            state = "error"
        elif not self.polling_enabled:
            state = "paused"
        elif clip is not None:
            state = "playing"
        else:
            state = "idle"
        self.tray.setIcon(tray_icon(state))
        short = title if len(title) <= 48 else title[:47] + "\u2026"
        tip = "pygoals {}\n{}\n{}\nPolling {}".format(
            __version__, short, self.device.name if self.device else "No Chromecast",
            "on" if self.polling_enabled else "paused")
        if self.last_error:
            tip += "\n\u26A0 " + ERROR_TITLES.get(self.last_error[0], "error")
        self.tray.setToolTip(tip[:127])


def run_tray(runtime, player=None):
    """Run the Qt event loop. Returns the process exit code."""
    app = QApplication.instance() or QApplication(["pygoals"])
    app.setApplicationName("pygoals")
    app.setApplicationDisplayName("pygoals")
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("No system tray available; showing the media bar only.")
    player = player or runtime.make_player()
    controller = TrayApp(app, player, runtime)
    interrupted = {"flag": False}

    def on_sigint(*_args):
        interrupted["flag"] = True
        controller.quit()

    previous = signal.signal(signal.SIGINT, on_sigint)
    heartbeat = QTimer()
    heartbeat.start(250)  # lets Python run signal handlers during exec()
    heartbeat.timeout.connect(lambda: None)
    controller.start()
    try:
        code = app.exec()
    finally:
        heartbeat.stop()
        signal.signal(signal.SIGINT, previous)
        controller.close()
        player.shutdown()
    return 130 if interrupted["flag"] else code


def show_fatal(message):
    """Dark message box for errors before the tray exists."""
    from PyQt6.QtWidgets import QMessageBox

    app = QApplication.instance() or QApplication(["pygoals"])
    apply_dark_theme(app)
    box = QMessageBox(QMessageBox.Icon.Critical, "pygoals", message)
    box.exec()
