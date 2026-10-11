"""Pure positioning math for the tray media bar and toasts (no Qt).

Rectangles are ``(x, y, width, height)`` tuples in global screen
coordinates, right/bottom exclusive. ``screen`` is the full monitor rect and
``avail`` the work area (screen minus taskbar), as Qt's QScreen.geometry() and
QScreen.availableGeometry() report them.
"""

from __future__ import annotations

EDGES = ("bottom", "top", "left", "right")


def taskbar_edge(screen, avail):
    """Which edge the taskbar occupies, or None (auto-hide / no taskbar)."""
    sx, sy, sw, sh = screen
    ax, ay, aw, ah = avail
    gaps = {
        "bottom": (sy + sh) - (ay + ah),
        "top": ay - sy,
        "left": ax - sx,
        "right": (sx + sw) - (ax + aw),
    }
    edge = max(EDGES, key=lambda e: gaps[e])
    return edge if gaps[edge] > 0 else None


def nearest_edge(point, screen):
    px, py = point
    sx, sy, sw, sh = screen
    distances = {
        "bottom": (sy + sh) - py,
        "top": py - sy,
        "left": px - sx,
        "right": (sx + sw) - px,
    }
    return min(EDGES, key=lambda e: distances[e])


def _valid(rect):
    return rect is not None and rect[2] > 0 and rect[3] > 0


def _contains(rect, point):
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


def clamp(pos, size, avail, margin=0):
    x, y = pos
    w, h = size
    ax, ay, aw, ah = avail
    max_x = ax + aw - w - margin
    max_y = ay + ah - h - margin
    x = max(ax + margin, min(x, max_x)) if max_x >= ax + margin else ax
    y = max(ay + margin, min(y, max_y)) if max_y >= ay + margin else ay
    return int(round(x)), int(round(y))


def anchor_position(size, icon, screen, avail, margin=10):
    """Top-left for a popup of ``size`` next to the tray ``icon``.

    The popup sits ``margin`` px off the taskbar, centered on the icon along
    the taskbar, on whichever edge the taskbar is. Returns ``(x, y, edge)``.
    """
    w, h = size
    ax, ay, aw, ah = avail
    edge = taskbar_edge(screen, avail)
    if not _valid(icon) or not _contains(screen, (icon[0] + icon[2] / 2, icon[1] + icon[3] / 2)):
        # No usable icon geometry: bottom-right corner of the work area,
        # biased toward wherever the taskbar is.
        corner = {
            "top": (ax + aw - 1, ay - 1),
            "left": (ax - 1, ay + ah - 1),
            "right": (ax + aw, ay + ah - 1),
        }.get(edge, (ax + aw - 1, ay + ah))
        icon = (corner[0], corner[1], 1, 1)
    ix, iy, iw, ih = icon
    cx, cy = ix + iw / 2.0, iy + ih / 2.0
    if edge is None:
        edge = nearest_edge((cx, cy), screen)
    if edge == "bottom":
        x, y = cx - w / 2.0, min(ay + ah, iy) - h - margin
    elif edge == "top":
        x, y = cx - w / 2.0, max(ay, iy + ih) + margin
    elif edge == "left":
        x, y = max(ax, ix + iw) + margin, cy - h / 2.0
    else:  # right
        x, y = min(ax + aw, ix) - w - margin, cy - h / 2.0
    x, y = clamp((x, y), size, avail, margin)
    return x, y, edge


def stack_positions(sizes, icon, screen, avail, margin=10, gap=8, reserved=0):
    """Positions for toasts stacked away from the taskbar.

    ``reserved`` is space (px) already used next to the anchor, e.g. by the
    visible media bar. Toasts that would leave the work area are dropped,
    so the result can be shorter than ``sizes``.
    """
    positions = []
    offset = reserved + (gap if reserved else 0)
    ax, ay, aw, ah = avail
    for size in sizes:
        x, y, edge = anchor_position(size, icon, screen, avail, margin)
        if edge == "top":
            y = y + offset
            fits = y + size[1] <= ay + ah - margin
        else:
            y = y - offset
            fits = y >= ay + margin
        if not fits:
            break
        positions.append((x, y))
        offset += size[1] + gap
    return positions


def visible_on_any(pos, size, avails, min_visible=40):
    """True if at least ``min_visible`` px of the rect lands on some screen."""
    x, y = pos
    w, h = size
    for ax, ay, aw, ah in avails:
        overlap_w = min(x + w, ax + aw) - max(x, ax)
        overlap_h = min(y + h, ay + ah) - max(y, ay)
        if overlap_w >= min(min_visible, w) and overlap_h >= min(min_visible, h):
            return True
    return False
