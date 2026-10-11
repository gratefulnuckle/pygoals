"""Dark frameless widgets for the tray app: media bar, toasts, Settings and
Devices pages. No player logic here; ``tray.TrayApp`` wires them up."""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
    QWidget,
)

import brightcove as brightcove_mod
import settings as settings_mod
from tray_style import ACCENT, DANGER, MUTED, glyph_icon, logo_pixmap, rounded_pixmap

SHADOW_MARGIN = 14


def _shadow(widget):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(28)
    effect.setOffset(0, 6)
    effect.setColor(QColor(0, 0, 0, 150))
    widget.setGraphicsEffect(effect)


def _tool_button(kind, tip, checkable=False):
    button = QToolButton()
    button.setIcon(glyph_icon(kind))
    button.setToolTip(tip)
    button.setAutoRaise(True)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setObjectName("Btn_" + kind)
    return button


class _DragMixin:
    """Click-drag anywhere that is not a button to move the window."""

    moved = None  # subclasses define a pyqtSignal(QPoint)

    def _drag_init(self):
        self._drag_offset = None
        self._drag_start = None
        self._dragged = False

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            self._drag_offset = global_pos - self.frameGeometry().topLeft()
            self._drag_start = global_pos
            self._dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            if not self._dragged and (global_pos - self._drag_start).manhattanLength() > 3:
                self._dragged = True
            if self._dragged:
                self.move(global_pos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.button() == Qt.MouseButton.LeftButton:
            dragged = self._dragged
            self._drag_offset = None
            self._dragged = False
            if dragged and self.moved is not None:
                self.moved.emit(self.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlaybarWindow(_DragMixin, QWidget):
    """Compact now-playing bar anchored above the tray icon."""

    moved = pyqtSignal(QPoint)
    snap_requested = pyqtSignal()
    hidden_by_focus = pyqtSignal()

    ART = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_init()
        self.setObjectName("Playbar")
        self.setWindowTitle("pygoals")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.auto_hide = True
        self.last_hidden_at = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        card = QFrame(self)
        card.setObjectName("Card")
        _shadow(card)
        outer.addWidget(card)

        row = QHBoxLayout(card)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(10)

        self.accent = QFrame(card)
        self.accent.setObjectName("Accent")
        self.accent.setFixedWidth(4)
        self.set_accent(ACCENT)
        row.addWidget(self.accent)

        self.art = QLabel(card)
        self.art.setObjectName("Art")
        self.art.setFixedSize(self.ART, self.ART)
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.art)

        column = QVBoxLayout()
        column.setSpacing(2)
        self.title = QLabel("Waiting for goals", card)
        self.title.setObjectName("Title")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.subtitle = QLabel("Starting\u2026", card)
        self.subtitle.setObjectName("Subtitle")
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column.addWidget(self.title)
        column.addWidget(self.subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(2)
        self.skip_button = _tool_button("skip", "Skip clip")
        self.pause_button = _tool_button("pause", "Pause polling", checkable=True)
        self.device_button = _tool_button("device", "Chromecast")
        self.device_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.replay_button = _tool_button("replay", "Replay all")
        self.settings_button = _tool_button("settings", "Settings")
        self.snap_button = _tool_button("pin", "Snap back to the tray")
        self.quit_button = _tool_button("power", "Quit pygoals")
        for button in (self.skip_button, self.pause_button, self.device_button, self.replay_button,
                       self.settings_button):
            controls.addWidget(button)
        controls.addStretch(1)
        controls.addWidget(self.snap_button)
        controls.addWidget(self.quit_button)
        self.snap_button.clicked.connect(self.snap_requested.emit)
        self.snap_button.setVisible(False)
        column.addLayout(controls)
        row.addLayout(column, 1)

        self.setFixedSize(400 + 2 * SHADOW_MARGIN, 96 + 2 * SHADOW_MARGIN)
        self.set_art(None, "")

    # -- content -------------------------------------------------------
    def set_accent(self, color):
        self.accent.setStyleSheet("QFrame#Accent { background-color: %s; border-radius: 2px; }" % color)
        self.accent_color = color

    def set_now_playing(self, title, subtitle, accent=None):
        metrics = self.title.fontMetrics()
        width = max(120, self.title.width() or 260)
        self.title.setText(metrics.elidedText(title, Qt.TextElideMode.ElideRight, width))
        self.title.setToolTip(title)
        self.subtitle.setText(subtitle)
        self.set_accent(accent or ACCENT)

    def set_subtitle(self, text):
        self.subtitle.setText(text)

    def set_art(self, pixmap, initials=""):
        if pixmap is not None and not pixmap.isNull():
            self.art.setPixmap(rounded_pixmap(pixmap, self.ART, 10))
            self.art.setText("")
        elif not initials and logo_pixmap(self.ART) is not None:
            # Nothing playing: the pygoals logo as a brand mark.
            self.art.clear()
            self.art.setPixmap(logo_pixmap(self.ART))
        else:
            self.art.setPixmap(rounded_pixmap(None, self.ART))
            self.art.clear()
            self.art.setText(initials or "\u25CF")
            self.art.setStyleSheet("QLabel#Art { color: %s; font-size: 18px; font-weight: 700; }" % MUTED)

    def set_polling(self, enabled):
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(not enabled)
        self.pause_button.blockSignals(False)
        self.pause_button.setIcon(glyph_icon("pause" if enabled else "play"))
        self.pause_button.setToolTip("Pause polling" if enabled else "Resume polling")

    def set_pinned(self, pinned):
        self.snap_button.setVisible(bool(pinned))

    # -- behaviour -----------------------------------------------------
    def changeEvent(self, event):  # noqa: N802
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow():
            if self.auto_hide and self.isVisible() and self._drag_offset is None:
                QTimer.singleShot(0, self._hide_after_focus_loss)
        super().changeEvent(event)

    def _hide_after_focus_loss(self):
        if self.isVisible() and not self.isActiveWindow() and self.auto_hide:
            self.hide()
            self.hidden_by_focus.emit()

    def hideEvent(self, event):  # noqa: N802
        self.last_hidden_at = time.monotonic()
        super().hideEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.snap_requested.emit()
        event.accept()


class Toast(QWidget):
    """One dark notification card. Click to dismiss (or run ``on_click``)."""

    closed = pyqtSignal(object)

    WIDTH = 340

    def __init__(self, title, body, accent=ACCENT, seconds=6.0, on_click=None):
        super().__init__(None)
        self.setObjectName("Toast")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.on_click = on_click
        self._closing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        card = QFrame(self)
        card.setObjectName("Card")
        _shadow(card)
        outer.addWidget(card)
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 10, 12, 10)
        row.setSpacing(10)
        stripe = QFrame(card)
        stripe.setFixedWidth(4)
        stripe.setStyleSheet("background-color: %s; border-radius: 2px;" % accent)
        row.addWidget(stripe)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.title_label = QLabel(title, card)
        self.title_label.setObjectName("Title")
        self.body_label = QLabel(body, card)
        self.body_label.setObjectName("Subtitle")
        self.body_label.setWordWrap(True)
        column.addWidget(self.title_label)
        column.addWidget(self.body_label)
        row.addLayout(column, 1)
        close = _tool_button("close", "Dismiss")
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self.setFixedWidth(self.WIDTH + 2 * SHADOW_MARGIN)
        self.adjustSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(int(max(1.0, seconds) * 1000))
        self._fade = None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            callback, self.on_click = self.on_click, None
            if callback:
                callback()
            self.dismiss()
        event.accept()

    def enterEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if not self._closing:
            self._timer.start(2500)
        super().leaveEvent(event)

    def dismiss(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self):
        self.hide()
        self.closed.emit(self)
        self.deleteLater()


class ToastManager:
    """Stacks toasts above the tray icon (or above the media bar)."""

    MAX = 4

    def __init__(self, layout_fn):
        # layout_fn(sizes) -> list[(x, y)], provided by the controller.
        self._layout_fn = layout_fn
        self.toasts = []

    def show(self, title, body, accent=ACCENT, seconds=6.0, on_click=None):
        toast = Toast(title, body, accent=accent, seconds=seconds, on_click=on_click)
        toast.closed.connect(self._closed)
        self.toasts.append(toast)
        while len(self.toasts) > self.MAX:
            self.toasts[0].dismiss()
            self.toasts.pop(0)
        self.relayout()
        toast.show()
        return toast

    def _closed(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        self.relayout()

    def relayout(self):
        newest_first = list(reversed(self.toasts))
        sizes = [(t.width(), t.sizeHint().height()) for t in newest_first]
        positions = self._layout_fn(sizes)
        for index, toast in enumerate(newest_first):
            if index < len(positions):
                toast.move(*positions[index])
            else:
                toast.dismiss()

    def clear(self):
        for toast in list(self.toasts):
            toast.hide()
            toast.deleteLater()
        self.toasts.clear()


class DarkDialog(_DragMixin, QDialog):
    """Frameless rounded dark dialog with a draggable header."""

    moved = None

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._drag_init()
        self.setWindowTitle("pygoals \u2014 " + title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        self.card = QFrame(self)
        self.card.setObjectName("Card")
        _shadow(self.card)
        outer.addWidget(self.card)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(10)
        header = QHBoxLayout()
        heading = QLabel(title, self.card)
        heading.setObjectName("Heading")
        header.addWidget(heading)
        header.addStretch(1)
        close = _tool_button("close", "Close")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        self.body.addLayout(header)


# Settings page --------------------------------------------------------------

class SettingsDialog(DarkDialog):
    """Edit settings.ini. Emits ``saved(Settings)`` after a successful save."""

    saved = pyqtSignal(object)
    open_devices = pyqtSignal()
    open_file = pyqtSignal()

    renditions_loaded = pyqtSignal(object, bool)

    def __init__(self, stored, path, key_from_env=False, parent=None, rendition_loader=None):
        super().__init__("Settings", parent)
        self.stored = stored
        self._rendition_loader = rendition_loader
        self.path = path
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.widgets = {}

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit(stored.policy_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Brightcove player policy key")
        reveal = _tool_button("scan", "Show / hide key", checkable=True)
        reveal.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(reveal)
        form.addRow("Policy key", key_row)
        self.widgets["policy_key"] = self.key_edit
        if key_from_env:
            hint = QLabel("BRIGHTCOVE_PK is set in the environment/.env and overrides this value.")
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            form.addRow("", hint)

        device_row = QHBoxLayout()
        device_text = stored.device_name or "(none selected)"
        if stored.device_host:
            device_text += "  \u00b7  " + stored.device_host
        self.device_label = QLabel(device_text)
        devices_button = QPushButton("Devices\u2026")
        devices_button.clicked.connect(self.open_devices.emit)
        device_row.addWidget(self.device_label, 1)
        device_row.addWidget(devices_button)
        form.addRow("Chromecast", device_row)

        self.hosts_edit = QLineEdit(", ".join(stored.known_hosts))
        self.hosts_edit.setPlaceholderText("Optional IPs, comma separated")
        form.addRow("Known hosts", self.hosts_edit)
        self.widgets["known_hosts"] = self.hosts_edit

        self.poll_spin = self._double(settings_mod.MIN_POLL_SECONDS, settings_mod.MAX_POLL_SECONDS,
                                      stored.poll_seconds, " s")
        form.addRow("Poll every", self.poll_spin)
        self.widgets["poll_seconds"] = self.poll_spin
        self.receiver_combo = QComboBox()
        for value, label in (("auto", "Auto \u2014 pygoals receiver if it launches, else default"),
                             ("custom", "pygoals receiver (HTML cards, no gap)"),
                             ("default", "Default Media Receiver")):
            self.receiver_combo.addItem(label, value)
        self._select(self.receiver_combo, stored.receiver_mode, stored.receiver_mode)
        form.addRow("Cast receiver", self.receiver_combo)
        self.widgets["receiver_mode"] = self.receiver_combo
        self.app_id_edit = QLineEdit(stored.receiver_app_id)
        self.app_id_edit.setPlaceholderText("Cast app ID, e.g. 7B4ABD0E (blank = default receiver)")
        self.app_id_edit.setMaxLength(8)
        self.app_id_edit.setToolTip("Unpublished receivers only run on devices registered as Cast test devices")
        form.addRow("Receiver app ID", self.app_id_edit)
        self.widgets["receiver_app_id"] = self.app_id_edit
        self.video_overlay = self._check("Show title text over the goal video", stored.video_overlay)
        self.video_overlay.setToolTip("Off: the card shows the details, then the goal plays as clean video")
        form.addRow("", self.video_overlay)
        self.widgets["video_overlay"] = self.video_overlay

        self.card_mode_combo = QComboBox()
        for value, label in (("video", "Video \u2014 seamless into the goal"),
                             ("image", "Image \u2014 receiver restarts before the goal"),
                             ("off", "Off \u2014 no player card")):
            self.card_mode_combo.addItem(label, value)
        self._select(self.card_mode_combo, stored.card_mode, stored.card_mode)
        self.card_mode_combo.setToolTip("Video cards need ffmpeg (pip install imageio-ffmpeg); "
                                        "without it image cards are used")
        form.addRow("Player card", self.card_mode_combo)
        self.widgets["card_mode"] = self.card_mode_combo
        self.card_spin = self._double(0, 30, stored.card_seconds, " s")
        self.card_spin.setToolTip("How long the card shows (video cards last at least 1 s)")
        form.addRow("Card duration", self.card_spin)
        self.widgets["card_seconds"] = self.card_spin
        self.card_mode_combo.currentIndexChanged.connect(
            lambda _i: self.card_spin.setEnabled(self.card_mode_combo.currentData() != "off"))
        self.card_spin.setEnabled(stored.card_mode != "off")
        self.quality_combo = QComboBox()
        self.quality_combo.setToolTip("Renditions Brightcove offers for NHL goals (H.264 only)")
        self._fill_quality(brightcove_mod.STATIC_OPTIONS)
        quality_box = QVBoxLayout()
        quality_box.setSpacing(2)
        quality_box.addWidget(self.quality_combo)
        self.quality_note = QLabel("Typical NHL renditions" if rendition_loader is None
                                   else "Loading the renditions Brightcove offers\u2026")
        self.quality_note.setObjectName("Hint")
        quality_box.addWidget(self.quality_note)
        form.addRow("Video quality", quality_box)
        self.widgets["quality"] = self.quality_combo

        self.height_combo = QComboBox()
        for height in ("2160", "1440", "1080", "720", "540", "360"):
            self.height_combo.addItem("{}p".format(height), height)
        self._select(self.height_combo, str(stored.max_height), "{}p".format(stored.max_height))
        self.height_combo.setToolTip("Auto picks the tallest H.264 rendition up to this height")
        form.addRow("Auto max height", self.height_combo)
        self.widgets["max_height"] = self.height_combo
        self.remember_seen = self._check("Remember played clips across restarts", stored.remember_seen)
        form.addRow("", self.remember_seen)
        self.widgets["remember_seen"] = self.remember_seen

        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setValue(stored.port)
        self.port_spin.setSpecialValueText("auto")
        form.addRow("Card port", self.port_spin)
        self.widgets["port"] = self.port_spin

        self.snap = self._check("Keep the media bar snapped above the tray", stored.snap_to_tray)
        form.addRow("", self.snap)
        self.widgets["snap_to_tray"] = self.snap
        self.show_bar = self._check("Show the media bar at startup", stored.show_bar_on_start)
        form.addRow("", self.show_bar)
        self.widgets["show_bar_on_start"] = self.show_bar
        self.notify_goals = self._check("Notify on new goals", stored.notify_goals)
        form.addRow("", self.notify_goals)
        self.widgets["notify_goals"] = self.notify_goals
        self.notify_errors = self._check("Notify on errors", stored.notify_errors)
        form.addRow("", self.notify_errors)
        self.widgets["notify_errors"] = self.notify_errors
        self.toast_spin = self._double(2, 60, stored.toast_seconds, " s")
        form.addRow("Toast time", self.toast_spin)
        self.widgets["toast_seconds"] = self.toast_spin

        self.level_combo = QComboBox()
        for level in settings_mod.LOG_LEVELS:
            self.level_combo.addItem(level, level)
        self._select(self.level_combo, stored.log_level, stored.log_level)
        form.addRow("Log level", self.level_combo)
        self.widgets["log_level"] = self.level_combo
        self.log_file = self._check("Write logs/pygoals.log", stored.log_to_file)
        form.addRow("", self.log_file)
        self.widgets["log_to_file"] = self.log_file

        self.body.addLayout(form)
        self.error_label = QLabel("")
        self.error_label.setObjectName("Error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.body.addWidget(self.error_label)
        note = QLabel("Saved to {}. Port changes apply after restart.".format(path))
        note.setObjectName("Hint")
        note.setWordWrap(True)
        self.body.addWidget(note)

        buttons = QHBoxLayout()
        open_file = QPushButton("Open settings.ini")
        open_file.clicked.connect(self.open_file.emit)
        buttons.addWidget(open_file)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        self.body.addLayout(buttons)
        self.save_button = save
        self.setMinimumWidth(500)

    @staticmethod
    def _select(combo, value, label):
        index = combo.findData(value)
        if index < 0:
            combo.addItem(label, value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _fill_quality(self, options):
        current = self.quality_combo.currentData() or self.stored.quality
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        for key, label in options:
            self.quality_combo.addItem(label, key)
        if self.quality_combo.findData(current) < 0:
            self.quality_combo.addItem("{} (not offered right now)".format(current), current)
        self.quality_combo.setCurrentIndex(self.quality_combo.findData(current))
        self.quality_combo.blockSignals(False)

    def _on_renditions(self, options, live):
        if options:
            self._fill_quality(options)
        self.quality_note.setText("Offered by Brightcove for a recent goal" if live
                                  else "Couldn't reach Brightcove \u2014 typical NHL renditions shown")

    def load_renditions(self):
        """Fetch the real rendition list off the UI thread (cached by the loader)."""
        if self._rendition_loader is None:
            return
        loader = self._rendition_loader
        self.renditions_loaded.connect(self._on_renditions)

        def work():
            try:
                options, live = loader()
            except Exception:  # noqa: BLE001
                options, live = None, False
            try:
                self.renditions_loaded.emit(options, live)
            except RuntimeError:  # dialog already closed
                pass

        threading.Thread(target=work, name="renditions", daemon=True).start()

    @staticmethod
    def _double(low, high, value, suffix):
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(0 if high > 100 else 1)
        spin.setSuffix(suffix)
        spin.setValue(value)
        return spin

    @staticmethod
    def _check(text, value):
        box = QCheckBox(text)
        box.setChecked(bool(value))
        return box

    def values(self):
        def text(widget):
            if isinstance(widget, QCheckBox):
                return "true" if widget.isChecked() else "false"
            if isinstance(widget, QComboBox):
                data = widget.currentData()
                return str(data) if data is not None else widget.currentText()
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                return "{:g}".format(widget.value())
            return widget.text()

        return {attr: text(widget) for attr, widget in self.widgets.items()}

    def save(self):
        for widget in self.widgets.values():
            widget.setProperty("invalid", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        try:
            updated = settings_mod.validate_values(self.values(), base=self.stored)
        except settings_mod.SettingsError as exc:
            for attr in exc.errors:
                widget = self.widgets.get(attr)
                if widget is not None:
                    widget.setProperty("invalid", True)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
            self.error_label.setText("Fix: " + "; ".join(
                "{} \u2014 {}".format(k.replace("_", " "), v) for k, v in exc.errors.items()))
            self.error_label.setVisible(True)
            return False
        try:
            settings_mod.save(updated, self.path)
        except OSError as exc:
            self.error_label.setText("Could not write {}: {}".format(self.path, exc))
            self.error_label.setVisible(True)
            return False
        self.stored = updated
        self.saved.emit(updated)
        self.accept()
        return True


# Devices page ---------------------------------------------------------------

class DevicesDialog(DarkDialog):
    scan_requested = pyqtSignal()
    device_chosen = pyqtSignal(object)

    COLUMNS = ("", "Name", "Model", "IP address")

    def __init__(self, parent=None):
        super().__init__("Devices", parent)
        self.devices = []
        self.active_uuid = ""
        hint = QLabel("Chromecasts found on your network. Pick one to play goals on.")
        hint.setObjectName("Hint")
        self.body.addWidget(hint)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.body.addWidget(self.progress)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 28)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._choose())
        self.table.setMinimumHeight(180)
        self.body.addWidget(self.table)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.body.addWidget(self.status)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.scan_button.setIcon(glyph_icon("scan"))
        self.scan_button.clicked.connect(self.scan_requested.emit)
        buttons.addWidget(self.scan_button)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.use_button = QPushButton("Use this device")
        self.use_button.setObjectName("Primary")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self._choose)
        buttons.addWidget(close)
        buttons.addWidget(self.use_button)
        self.body.addLayout(buttons)
        self.setMinimumSize(560, 360)

    def set_scanning(self, active):
        self.progress.setVisible(bool(active))
        self.scan_button.setEnabled(not active)
        if active:
            self.status.setText("Scanning the network\u2026")

    def set_devices(self, devices, active_uuid=""):
        self.devices = list(devices)
        self.active_uuid = active_uuid or ""
        self.table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            mark = "\u25CF" if device.uuid and device.uuid == self.active_uuid else ""
            values = (mark, device.name, device.model, device.host)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setForeground(QColor(ACCENT))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        if self.devices:
            self.status.setText("{} device(s) found.".format(len(self.devices)))
        else:
            self.status.setText("No Chromecasts found. Check that this PC and the TV are on the same network.")
        self._selection_changed()

    def set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet("color: %s;" % (DANGER if error else MUTED))

    def selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def _selection_changed(self):
        self.use_button.setEnabled(self.selected() is not None)

    def _choose(self):
        device = self.selected()
        if device is not None:
            self.set_status("Connecting to {}\u2026".format(device.name))
            self.device_chosen.emit(device)
