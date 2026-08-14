"""One-time visible setup for the DPAPI-bound authenticated profile."""

import configparser
import subprocess

from .authenticated_transport import DPAPIProfileStore, PikPakLocalLayout
from .rclone_adapter import RcloneAdapter
from .operator_preflight import run_operator_preflight


def provision_interactively(layout=None, store=None, runner=subprocess.run):
    """Launch rclone's visible config once, then protect and remove its plaintext."""
    layout = layout or PikPakLocalLayout()
    store = store or DPAPIProfileStore(layout)
    executable = layout.bin / "rclone.exe"
    if not executable.is_file():
        raise FileNotFoundError("Portable rclone is missing from PikPakLLC/bin")
    temporary = layout.runtime / "provisioning.conf"
    layout.runtime.mkdir(parents=True, exist_ok=True)
    store.cleanup(temporary)
    try:
        print("一次性设置：创建 remote 名 pikpak_gate，Storage 选择 pikpak。")
        print("这里只输入当前 PikPak 账号；今后的日常剪辑不再要求重复输入。")
        runner([str(executable), "config", "--config", str(temporary)], check=True)
        if not temporary.is_file():
            raise RuntimeError("rclone setup did not create a configuration")
        if temporary.read_bytes().startswith(b"RCLONE_ENCRYPT_V0:"):
            raise RuntimeError(
                "Do not enable rclone config encryption; Windows DPAPI protects this profile"
            )
        config = configparser.ConfigParser(interpolation=None)
        config.read(temporary, encoding="utf-8")
        if config.get("pikpak_gate", "type", fallback="").casefold() != "pikpak":
            raise RuntimeError("One-time setup remote pikpak_gate must use PikPak storage")
        adapter = RcloneAdapter(executable, layout=layout, runner=runner)
        adapter.validate_profile(temporary)
        store.provision(temporary)
        print("安全 profile 已保存；临时明文配置已清理。")
    finally:
        store.cleanup(temporary)


def main():
    run_operator_preflight()
    provision_interactively()


if __name__ == "__main__":
    main()
