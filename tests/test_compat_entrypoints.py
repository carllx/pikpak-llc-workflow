import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_root_compatibility_modules_still_import():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pikpak_api, download_proxy, llc_parser, range_guard, experimental_workflow",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
