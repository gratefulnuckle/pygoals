import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ENV_VARS = ("BRIGHTCOVE_PK", "PYGOALS_DEVICE", "PYGOALS_KNOWN_HOSTS", "PYGOALS_POLL_SECONDS",
            "PYGOALS_PORT", "PYGOALS_LOG_LEVEL")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real settings.ini / logs / state.json next to the app."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PYGOALS_HOME", str(home))
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    import brightcove

    brightcove.set_policy_key("")
    yield home
    brightcove.set_policy_key("")
