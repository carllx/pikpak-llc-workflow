"""Compatibility import for the packaged PikPak interface."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pikpak_llc.pikpak_api import *  # noqa: F401,F403
