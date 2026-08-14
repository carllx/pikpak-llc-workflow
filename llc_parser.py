"""Compatibility entrypoint for LosslessCut project parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pikpak_llc.llc_parser import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
