import pytest

from tray_geometry import anchor_position, stack_positions, taskbar_edge, visible_on_any

SCREEN = (0, 0, 1920, 1080)
SIZE = (428, 124)


@pytest.mark.parametrize("avail, edge", [
    ((0, 0, 1920, 1040), "bottom"),
    ((0, 40, 1920, 1040), "top"),
    ((60, 0, 1860, 1080), "left"),
    ((0, 0, 1860, 1080), "right"),
    ((0, 0, 1920, 1080), None),
])
def test_taskbar_edge(avail, edge):
    assert taskbar_edge(SCREEN, avail) == edge


def test_bottom_taskbar_sits_10px_above_and_centres_on_icon():
    x, y, edge = anchor_position(SIZE, (1000, 1048, 24, 24), SCREEN, (0, 0, 1920, 1040))
    assert edge == "bottom"
    assert y == 1040 - 124 - 10
    assert x == 1012 - 214


def test_clamped_inside_work_area_near_corner():
    x, y, _ = anchor_position(SIZE, (1880, 1048, 24, 24), SCREEN, (0, 0, 1920, 1040))
    assert x == 1920 - 428 - 10


def test_top_left_right_taskbars():
    assert anchor_position(SIZE, (1800, 8, 24, 24), SCREEN, (0, 40, 1920, 1040))[:2] == (1920 - 428 - 10, 50)
    x, y, edge = anchor_position(SIZE, (18, 1000, 24, 24), SCREEN, (60, 0, 1860, 1080))
    assert (x, edge) == (70, "left") and y + 124 <= 1080 - 10
    x, y, edge = anchor_position(SIZE, (1878, 1000, 24, 24), SCREEN, (0, 0, 1860, 1080))
    assert (x, edge) == (1860 - 428 - 10, "right")


def test_second_monitor_with_negative_coordinates():
    screen = (-1920, 0, 1920, 1080)
    avail = (-1920, 0, 1920, 1040)
    x, y, edge = anchor_position(SIZE, (-200, 1050, 24, 24), screen, avail)
    assert edge == "bottom" and -1920 <= x <= -428 and y == 906


def test_invalid_icon_falls_back_to_tray_corner():
    x, y, edge = anchor_position(SIZE, (0, 0, 0, 0), SCREEN, (0, 0, 1920, 1040))
    assert (x, y, edge) == (1920 - 428 - 10, 1040 - 124 - 10, "bottom")
    x, y, edge = anchor_position(SIZE, None, SCREEN, (0, 40, 1920, 1040))
    assert (x, y, edge) == (1920 - 428 - 10, 50, "top")


def test_autohide_taskbar_uses_icon_position():
    x, y, edge = anchor_position(SIZE, (1800, 1070, 10, 10), SCREEN, SCREEN)
    assert edge == "bottom" and y == 1070 - 124 - 10


def test_toasts_stack_upward_above_reserved_bar_and_drop_overflow():
    sizes = [(368, 100)] * 20
    positions = stack_positions(sizes, (1800, 1048, 24, 24), SCREEN, (0, 0, 1920, 1040), gap=4, reserved=124)
    first_y = 1040 - 100 - 10 - (124 + 4)
    assert positions[0][1] == first_y
    assert positions[1][1] == first_y - 104
    assert all(y >= 10 for _x, y in positions)
    assert len(positions) < 20


def test_toasts_stack_downward_for_top_taskbar():
    positions = stack_positions([(368, 100)] * 2, (1800, 8, 24, 24), SCREEN, (0, 40, 1920, 1040), gap=4)
    assert positions[0][1] == 50 and positions[1][1] == 154


def test_visible_on_any():
    avails = [(0, 0, 1920, 1040), (-1920, 0, 1920, 1040)]
    assert visible_on_any((100, 100), SIZE, avails)
    assert visible_on_any((-600, 100), SIZE, avails)
    assert not visible_on_any((5000, 100), SIZE, avails)
    assert not visible_on_any((1910, 100), SIZE, avails[:1])
