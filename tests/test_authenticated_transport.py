from pathlib import Path

import pytest

from pikpak_llc.authenticated_transport import (
    AuthenticatedTransport,
    DPAPIProfileStore,
    PikPakLocalLayout,
    ProfileProvisioningRequired,
)


class FakeProfileStore:
    def __init__(self, available=True):
        self.available = available
        self.materialized = []
        self.cleaned = []

    def materialize(self, path):
        if not self.available:
            raise ProfileProvisioningRequired("profile missing")
        Path(path).write_text("safe config", encoding="utf-8")
        self.materialized.append(Path(path))

    def cleanup(self, path):
        Path(path).unlink(missing_ok=True)
        self.cleaned.append(Path(path))


class FakeRclone:
    def __init__(self):
        self.started = []
        self.stopped = []

    def find_unique_file(self, config, media_filename):
        assert Path(config).exists()
        return {"path": f"folder/{media_filename}", "size": 4_000_000_000}

    def start_original_service(self, config, parent_path):
        self.started.append((Path(config), parent_path))
        return {"process": "service", "base_url": "http://127.0.0.1:1234"}

    def stop_service(self, service):
        self.stopped.append(service)


def test_authenticated_transport_auto_starts_and_cleans_runtime_profile(tmp_path):
    profile = FakeProfileStore()
    rclone = FakeRclone()
    transport = AuthenticatedTransport(profile, rclone, tmp_path / "runtime")

    with transport.open_for("movie.mp4") as opened:
        assert opened.origin_url == "http://127.0.0.1:1234/movie.mp4"
        assert opened.origin_total == 4_000_000_000
        assert rclone.started[0][1] == "folder"

    assert rclone.stopped == [{"process": "service", "base_url": "http://127.0.0.1:1234"}]
    assert not profile.materialized[0].exists()
    assert profile.cleaned[0] == profile.materialized[0]
    assert profile.cleaned[-1] == profile.materialized[0]
    assert len(profile.cleaned) == 2


def test_authenticated_transport_missing_profile_requests_one_time_setup(tmp_path):
    transport = AuthenticatedTransport(
        FakeProfileStore(available=False), FakeRclone(), tmp_path / "runtime"
    )

    with pytest.raises(ProfileProvisioningRequired):
        with transport.open_for("movie.mp4"):
            pass


class FakeProtector:
    def protect(self, data):
        return b"protected:" + data

    def unprotect(self, data):
        assert data.startswith(b"protected:")
        return data.removeprefix(b"protected:")


def test_dpapi_profile_store_materializes_and_removes_runtime_plaintext(tmp_path):
    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    store = DPAPIProfileStore(layout, protector=FakeProtector())
    source = tmp_path / "source.conf"
    source.write_bytes(b"[pikpak_gate]\ntype = pikpak\n")
    store.provision(source)
    runtime = layout.runtime / "job-rclone.conf"

    store.materialize(runtime)
    assert runtime.read_bytes() == source.read_bytes()
    store.cleanup(runtime)

    assert not runtime.exists()
    assert layout.profile_blob.exists()
    assert layout.bin == layout.root / "bin"
    assert layout.logs == layout.root / "logs"
