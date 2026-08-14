"""Compatibility import for the packaged Range Guard."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pikpak_llc.range_guard import *  # noqa: F401,F403
