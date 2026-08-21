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


def test_provision_credentials_creates_config_and_provisions(tmp_path):
    layout = PikPakLocalLayout(tmp_path / "PikPakLLC")
    layout.bin.mkdir(parents=True)
    (layout.bin / "rclone.exe").touch()
    store = FakeStore()
    commands = []

    def runner(command, check, **kwargs):
        commands.append(command)
        if len(command) > 2 and command[1] == "config" and command[2] == "create":
            config = Path(command[command.index("--config") + 1])
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                f"[pikpak_gate]\ntype = pikpak\nuser = {command[command.index('user') + 1]}\n",
                encoding="utf-8",
            )
        return type("Result", (), {"stdout": "pikpak_gate:\n"})()

    from pikpak_llc.profile_setup import provision_credentials

    provision_credentials(
        "testuser@example.com",
        "secretpass",
        layout=layout,
        store=store,
        runner=runner,
    )

    create_cmd = commands[0]
    assert create_cmd[1:5] == ["config", "create", "pikpak_gate", "pikpak"]
    assert create_cmd[create_cmd.index("user") + 1] == "testuser@example.com"
    assert create_cmd[create_cmd.index("pass") + 1] == "secretpass"
    assert [command[1] for command in commands[1:]] == ["listremotes", "lsjson"]
    assert len(store.provisioned) == 1
    assert not store.provisioned[0].exists()


def test_main_cli_routing(monkeypatch):
    from pikpak_llc import profile_setup
    import pytest

    called = []
    monkeypatch.setattr(profile_setup, "run_operator_preflight", lambda: None)
    monkeypatch.setattr(
        profile_setup,
        "provision_credentials",
        lambda u, p: called.append(("credentials", u, p)),
    )
    monkeypatch.setattr(
        profile_setup, "provision_interactively", lambda: called.append(("interactive",))
    )

    profile_setup.main(["--user", "u@test.com", "--pass", "pw123"])
    assert called == [("credentials", "u@test.com", "pw123")]

    called.clear()
    profile_setup.main([])
    assert called == [("interactive",)]

    called.clear()
    with pytest.raises(SystemExit):
        profile_setup.main(["--user", "u@test.com"])

