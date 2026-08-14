from pathlib import Path

from pikpak_llc.authenticated_transport import PikPakLocalLayout
from pikpak_llc.profile_setup import provision_interactively


class FakeStore:
    def __init__(self):
        self.provisioned = []
        self.cleaned = []

    def provision(self, path):
        assert "type = pikpak" in Path(path).read_text(encoding="utf-8")
        self.provisioned.append(Path(path))

    def cleanup(self, path):
        Path(path).unlink(missing_ok=True)
        self.cleaned.append(Path(path))


def test_one_time_setup_launches_visible_config_and_removes_plaintext(tmp_path):
    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    layout.bin.mkdir(parents=True)
    (layout.bin / "rclone.exe").touch()
    store = FakeStore()
    commands = []

    def runner(command, check, **kwargs):
        commands.append(command)
        if command[1] == "config":
            config = Path(command[command.index("--config") + 1])
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("[pikpak_gate]\ntype = pikpak\n", encoding="utf-8")
        return type("Result", (), {"stdout": "pikpak_gate:\n"})()

    provision_interactively(layout=layout, store=store, runner=runner)

    assert [command[1] for command in commands] == ["config", "listremotes", "lsjson"]
    assert store.provisioned[0] == store.cleaned[0] == store.cleaned[-1]
    assert len(store.cleaned) == 2
    assert not store.provisioned[0].exists()


def test_setup_rejects_rclone_password_encrypted_config(tmp_path):
    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    layout.bin.mkdir(parents=True)
    (layout.bin / "rclone.exe").touch()
    store = FakeStore()

    def runner(command, check, **kwargs):
        config = Path(command[command.index("--config") + 1])
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("RCLONE_ENCRYPT_V0:\nopaque", encoding="utf-8")

    import pytest

    with pytest.raises(RuntimeError, match="rclone config encryption"):
        provision_interactively(layout=layout, store=store, runner=runner)

    assert store.provisioned == []


def test_setup_rejects_same_name_remote_with_wrong_storage_type(tmp_path):
    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    layout.bin.mkdir(parents=True)
    (layout.bin / "rclone.exe").touch()
    store = FakeStore()

    def runner(command, check, **kwargs):
        config = Path(command[command.index("--config") + 1])
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("[pikpak_gate]\ntype = local\n", encoding="utf-8")

    import pytest

    with pytest.raises(RuntimeError, match="must use PikPak storage"):
        provision_interactively(layout=layout, store=store, runner=runner)

    assert store.provisioned == []
