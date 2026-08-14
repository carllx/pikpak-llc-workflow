import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import subprocess

from pikpak_llc.authenticated_transport import (
    PikPakLocalLayout,
    ProfileProvisioningRequired,
)
from pikpak_llc.rclone_adapter import RcloneAdapter, RcloneTargetError


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps(self.payload), returncode=0)


def test_find_unique_file_uses_original_mode_and_stable_filename(tmp_path):
    executable = tmp_path / "rclone.exe"
    executable.touch()
    runner = FakeRunner(
        [{"Path": "folder/movie.mp4", "Name": "movie.mp4", "Size": 1234}]
    )
    adapter = RcloneAdapter(executable, runner=runner)

    item = adapter.find_unique_file(tmp_path / "rclone.conf", "movie.mp4")

    command = runner.calls[0][0]
    assert item == {"path": "folder/movie.mp4", "size": 1234}
    assert "--pikpak-no-media-link" in command
    assert "--config" in command


@pytest.mark.parametrize("payload", [[], [
    {"Path": "a/movie.mp4", "Name": "movie.mp4", "Size": 1},
    {"Path": "b/movie.mp4", "Name": "movie.mp4", "Size": 1},
]])
def test_find_unique_file_fails_closed_for_missing_or_ambiguous_target(tmp_path, payload):
    executable = tmp_path / "rclone.exe"
    executable.touch()
    adapter = RcloneAdapter(executable, runner=FakeRunner(payload))
    with pytest.raises(RcloneTargetError):
        adapter.find_unique_file(tmp_path / "rclone.conf", "movie.mp4")


def test_start_service_binds_loopback_and_preserves_original_mode(tmp_path):
    commands = []
    executable = tmp_path / "rclone.exe"
    executable.touch()

    class FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            pass

    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return FakeProcess()

    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    adapter = RcloneAdapter(
        executable, layout=layout, popen=popen, port_factory=lambda: 43210,
        readiness_probe=lambda url, process: None,
    )
    service = adapter.start_original_service(tmp_path / "rclone.conf", "folder")

    command = commands[0][0]
    assert service["base_url"] == "http://127.0.0.1:43210"
    assert "127.0.0.1:43210" in command
    assert "--pikpak-no-media-link" in command
    assert "--config" in command


def test_authentication_failure_requests_one_time_profile_setup(tmp_path):
    executable = tmp_path / "rclone.exe"
    executable.touch()

    def failed(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="unauthorized")

    adapter = RcloneAdapter(executable, runner=failed)
    with pytest.raises(ProfileProvisioningRequired):
        adapter.find_unique_file(tmp_path / "rclone.conf", "movie.mp4")


def test_non_authentication_failure_remains_transport_error(tmp_path):
    executable = tmp_path / "rclone.exe"
    executable.touch()

    def failed(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="network timeout")

    adapter = RcloneAdapter(executable, runner=failed)
    with pytest.raises(subprocess.CalledProcessError):
        adapter.find_unique_file(tmp_path / "rclone.conf", "movie.mp4")
