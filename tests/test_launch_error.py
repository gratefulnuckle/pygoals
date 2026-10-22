from types import SimpleNamespace

import player


def test_launch_error_reason_reads_last_failure():
    receiver = SimpleNamespace(launch_failure=SimpleNamespace(reason="NOT_ALLOWED"))
    assert player.launch_error_reason(receiver) == "NOT_ALLOWED"
    assert "registered" in player.launch_error_hint("NOT_ALLOWED")


def test_launch_error_reason_missing():
    assert player.launch_error_reason(None) is None
    assert player.launch_error_reason(SimpleNamespace(launch_failure=None)) is None
    assert player._receiver_controller(object()) is None
    assert player.launch_error_hint("SOMETHING_NEW")
