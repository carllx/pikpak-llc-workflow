"""Minimal localhost adapter for authenticated PikPak original-file reads."""

import json
import socket
import subprocess
import time
from pathlib import Path

from .authenticated_transport import PikPakLocalLayout, ProfileProvisioningRequired


class RcloneTargetError(RuntimeError):
    """Raised when the requested media filename is missing or ambiguous."""


def _free_loopback_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_loopback(base_url, process, timeout=10):
    port = int(base_url.rsplit(":", 1)[1])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Authenticated rclone service exited during startup")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Authenticated rclone service did not become ready")


class RcloneAdapter:
    """Expose one authenticated remote directory on a loopback-only HTTP port."""

    def __init__(
        self,
        executable,
        remote_name="pikpak_gate",
        layout=None,
        runner=subprocess.run,
        popen=subprocess.Popen,
        port_factory=_free_loopback_port,
        readiness_probe=_wait_for_loopback,
    ):
        self.executable = Path(executable)
        self.remote_name = remote_name
        self.layout = layout or PikPakLocalLayout()
        self.runner = runner
        self.popen = popen
        self.port_factory = port_factory
        self.readiness_probe = readiness_probe

    def _base_command(self):
        if not self.executable.is_file():
            raise ProfileProvisioningRequired("Portable rclone executable is missing")
        return [str(self.executable)]

    @staticmethod
    def _raise_if_auth_failure(error):
        detail = f"{getattr(error, 'stderr', '')} {getattr(error, 'stdout', '')}".casefold()
        auth_markers = (
            "401",
            "unauthorized",
            "invalid_grant",
            "invalid credentials",
            "token expired",
        )
        if any(marker in detail for marker in auth_markers):
            raise ProfileProvisioningRequired(
                "Authenticated PikPak profile is expired or invalid; run one-time setup"
            ) from error

    def validate_profile(self, config):
        """Confirm the expected remote and an authenticated original-mode request."""
        common = ["--config", str(config)]
        listed = self.runner(
            self._base_command() + ["listremotes", *common],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if f"{self.remote_name}:" not in listed.stdout.splitlines():
            raise ProfileProvisioningRequired(
                f"One-time setup must create remote {self.remote_name}"
            )
        try:
            self.runner(
                self._base_command()
                + [
                    "lsjson",
                    f"{self.remote_name}:",
                    "--max-depth",
                    "1",
                    "--pikpak-no-media-link",
                    *common,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as error:
            self._raise_if_auth_failure(error)
            raise

    def find_unique_file(self, config, media_filename):
        command = self._base_command() + [
            "lsjson",
            f"{self.remote_name}:",
            "--recursive",
            "--files-only",
            "--pikpak-no-media-link",
            "--config",
            str(config),
        ]
        try:
            completed = self.runner(
                command, check=True, capture_output=True, text=True, encoding="utf-8"
            )
        except subprocess.CalledProcessError as error:
            self._raise_if_auth_failure(error)
            raise
        candidates = [
            item
            for item in json.loads(completed.stdout)
            if item.get("Name") == media_filename
        ]
        if len(candidates) != 1:
            raise RcloneTargetError(
                f"Authenticated target filename must match exactly once; got {len(candidates)}"
            )
        item = candidates[0]
        return {"path": item["Path"], "size": int(item["Size"])}

    def start_original_service(self, config, parent_path):
        port = self.port_factory()
        base_url = f"http://127.0.0.1:{port}"
        remote_path = f"{self.remote_name}:{parent_path}".rstrip("/")
        command = self._base_command() + [
            "serve",
            "http",
            remote_path,
            "--addr",
            f"127.0.0.1:{port}",
            "--pikpak-no-media-link",
            "--buffer-size",
            "0",
            "--config",
            str(config),
        ]
        self.layout.runtime.mkdir(parents=True, exist_ok=True)
        process = self.popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        service = {"process": process, "base_url": base_url}
        try:
            self.readiness_probe(base_url, process)
        except Exception:
            self.stop_service(service)
            raise
        return service

    @staticmethod
    def stop_service(service):
        process = service["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
