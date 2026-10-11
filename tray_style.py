"""Dark theme for the tray UI: palette, QSS and painter-drawn icons."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu

BG = "#12141A"
SURFACE = "#1A1D24"
SURFACE_HI = "#232733"
BORDER = "#2A2E37"
TEXT = "#E6E9EF"
MUTED = "#8B93A3"
ACCENT = "#5B8CFF"
DANGER = "#FF5A5F"
WARN = "#FFB020"
OK = "#3DDC84"

QSS = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 12px; color: %(TEXT)s; }
QFrame#Card { background-color: rgba(18, 20, 26, 238); border: 1px solid rgba(255, 255, 255, 26); border-radius: 14px; }
QFrame#Accent { border-radius: 2px; }
QLabel#Title { font-size: 13px; font-weight: 600; color: #F4F6FA; }
QLabel#Subtitle { color: %(MUTED)s; font-size: 11px; }
QLabel#Heading { font-size: 15px; font-weight: 600; }
QLabel#Hint { color: %(MUTED)s; font-size: 11px; }
QLabel#Error { color: %(DANGER)s; font-size: 11px; }
QLabel#Art { background-color: %(SURFACE_HI)s; border-radius: 10px; }
QToolButton { background: transparent; border: none; border-radius: 8px; padding: 5px; }
QToolButton:hover { background: rgba(255, 255, 255, 22); }
QToolButton:pressed { background: rgba(255, 255, 255, 38); }
QToolButton:checked { background: rgba(91, 140, 255, 48); }
QToolButton::menu-indicator { image: none; width: 0px; }
QPushButton { background-color: %(SURFACE_HI)s; border: 1px solid %(BORDER)s; border-radius: 8px; padding: 6px 14px; }
QPushButton:hover { background-color: #2B3040; }
QPushButton:pressed { background-color: #323849; }
QPushButton#Primary { background-color: %(ACCENT)s; border: 1px solid %(ACCENT)s; color: #FFFFFF; font-weight: 600; }
QPushButton#Primary:hover { background-color: #6F9BFF; }
QPushButton:disabled { color: #5E6573; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 7px; padding: 4px 8px;
    selection-background-color: %(ACCENT)s; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid %(ACCENT)s; }
QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] { border: 1px solid %(DANGER)s; }
QComboBox QAbstractItemView { background-color: %(SURFACE)s; border: 1px solid %(BORDER)s; selection-background-color: %(SURFACE_HI)s; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid %(BORDER)s; background: %(SURFACE)s; }
QCheckBox::indicator:checked { background: %(ACCENT)s; border: 1px solid %(ACCENT)s; }
QTableWidget { background-color: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px; gridline-color: transparent;
    selection-background-color: %(SURFACE_HI)s; selection-color: %(TEXT)s; }
QHeaderView::section { background-color: %(BG)s; color: %(MUTED)s; border: none; padding: 6px; font-weight: 600; }
QTableCornerButton::section { background-color: %(BG)s; border: none; }
QProgressBar { background-color: %(SURFACE)s; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background-color: %(ACCENT)s; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #3A3F4B; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }
QMenu { background-color: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; background: transparent; }
QMenu::item:selected { background-color: %(SURFACE_HI)s; }
QMenu::item:disabled { color: %(MUTED)s; }
QMenu::separator { height: 1px; background: %(BORDER)s; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; }
QToolTip { background-color: %(SURFACE)s; color: %(TEXT)s; border: 1px solid %(BORDER)s; padding: 4px 8px; border-radius: 6px; }
""" % dict(TEXT=TEXT, MUTED=MUTED, DANGER=DANGER, SURFACE=SURFACE, SURFACE_HI=SURFACE_HI, BORDER=BORDER, ACCENT=ACCENT, BG=BG)


def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: SURFACE_HI,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE_HI,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: SURFACE,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: MUTED,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5E6573"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5E6573"))
    app.setPalette(palette)
    app.setStyleSheet(QSS)


def style_menu(menu: QMenu):
    """Rounded, shadowless dark menu (QSS radius needs a translucent window)."""
    menu.setWindowFlags(
        menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return menu


def _canvas(size):
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def glyph_icon(kind, color=TEXT, size=18):
    """Small line icons drawn with QPainter (no icon font dependency)."""
    pixmap, p = _canvas(size)
    c = QColor(color)
    pen = QPen(c, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = float(size)
    m = s * 0.2

    def triangle(x0, x1):
        path = QPainterPath()
        path.moveTo(x0, m + 1)
        path.lineTo(x1, s / 2)
        path.lineTo(x0, s - m - 1)
        path.closeSubpath()
        p.fillPath(path, c)

    if kind == "skip":
        triangle(m, s * 0.48)
        triangle(s * 0.46, s * 0.74)
        p.drawLine(QPointF(s - m, m + 1), QPointF(s - m, s - m - 1))
    elif kind == "pause":
        bar = QPen(c, 2.6)
        bar.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(bar)
        p.drawLine(QPointF(s * 0.38, m + 1), QPointF(s * 0.38, s - m - 1))
        p.drawLine(QPointF(s * 0.62, m + 1), QPointF(s * 0.62, s - m - 1))
    elif kind == "play":
        triangle(s * 0.3, s * 0.78)
    elif kind == "replay":
        rect = QRectF(m, m, s - 2 * m, s - 2 * m)
        p.drawArc(rect, 90 * 16, 290 * 16)
        tip = QPointF(s / 2, m)
        p.drawLine(tip, QPointF(s / 2 - 3.2, m - 2.4))
        p.drawLine(tip, QPointF(s / 2 - 2.6, m + 3.2))
    elif kind == "device":
        p.drawRoundedRect(QRectF(m, m + 1, s - 2 * m, s * 0.5), 2, 2)
        p.drawLine(QPointF(s * 0.35, s - m), QPointF(s * 0.65, s - m))
        p.drawLine(QPointF(s / 2, m + 1 + s * 0.5), QPointF(s / 2, s - m))
    elif kind == "settings":
        center = QPointF(s / 2, s / 2)
        p.drawEllipse(center, s * 0.14, s * 0.14)
        for i in range(8):
            angle = math.radians(i * 45)
            inner = QPointF(s / 2 + math.cos(angle) * s * 0.26, s / 2 + math.sin(angle) * s * 0.26)
            outer = QPointF(s / 2 + math.cos(angle) * s * 0.38, s / 2 + math.sin(angle) * s * 0.38)
            p.drawLine(inner, outer)
        p.drawEllipse(center, s * 0.26, s * 0.26)
    elif kind == "pin":
        p.drawEllipse(QPointF(s / 2, s * 0.42), s * 0.2, s * 0.2)
        p.drawLine(QPointF(s / 2, s * 0.62), QPointF(s / 2, s - m))
        p.drawLine(QPointF(m, s - m + 1), QPointF(s - m, s - m + 1))
    elif kind == "close":
        p.drawLine(QPointF(m + 1, m + 1), QPointF(s - m - 1, s - m - 1))
        p.drawLine(QPointF(s - m - 1, m + 1), QPointF(m + 1, s - m - 1))
    elif kind == "power":
        p.drawArc(QRectF(m, m + 1, s - 2 * m, s - 2 * m), 120 * 16, 300 * 16)
        p.drawLine(QPointF(s / 2, m - 1), QPointF(s / 2, s / 2))
    elif kind == "log":
        p.drawRoundedRect(QRectF(m + 1, m, s - 2 * m - 2, s - 2 * m), 2, 2)
        for frac in (0.38, 0.52, 0.66):
            p.drawLine(QPointF(m + 4, s * frac), QPointF(s - m - 4, s * frac))
    elif kind == "scan":
        for radius in (0.18, 0.32, 0.46):
            rect = QRectF(s * 0.2 - s * radius, s * 0.8 - s * radius, 2 * s * radius, 2 * s * radius)
            p.drawArc(rect, 0, 90 * 16)
        p.setBrush(c)
        p.drawEllipse(QPointF(s * 0.22, s * 0.78), 1.4, 1.4)
    p.end()
    return QIcon(pixmap)


STATE_COLORS = {
    "playing": "#FF3B30",
    "idle": "#7C8594",
    "paused": ACCENT,
    "error": WARN,
}


def tray_icon(state="idle", size=32):
    """Goal-light tray icon: dark disc, colored lamp for the current state."""
    pixmap, p = _canvas(size)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(BG))
    p.drawEllipse(QRectF(1, 1, s - 2, s - 2))
    lamp = QColor(STATE_COLORS.get(state, STATE_COLORS["idle"]))
    glow = QColor(lamp)
    glow.setAlpha(80)
    p.setBrush(glow)
    p.drawEllipse(QPointF(s / 2, s * 0.44), s * 0.32, s * 0.32)
    p.setBrush(lamp)
    p.drawEllipse(QPointF(s / 2, s * 0.44), s * 0.2, s * 0.2)
    p.setBrush(QColor(TEXT))
    p.drawRoundedRect(QRectF(s * 0.28, s * 0.7, s * 0.44, s * 0.1), 1.5, 1.5)
    p.end()
    return QIcon(pixmap)


def rounded_pixmap(pixmap, size, radius=10):
    if pixmap is None or pixmap.isNull():
        return QPixmap()
    scaled = pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
    )
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return out
