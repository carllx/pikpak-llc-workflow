"""Zero-prompt authenticated original transport lifecycle."""

import ctypes
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class ProfileProvisioningRequired(RuntimeError):
    """Raised when the one-time secure PikPak profile is absent or invalid."""


@dataclass(frozen=True)
class OpenedOrigin:
    origin_url: str
    origin_total: int


@dataclass(frozen=True)
class PikPakLocalLayout:
    root: Path

    def __init__(self, root=None):
        default = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PikPakLLC"
        object.__setattr__(self, "root", Path(root) if root else default)

    @property
    def bin(self):
        return self.root / "bin"

    @property
    def profiles(self):
        return self.root / "profiles"

    @property
    def runtime(self):
        return self.root / "runtime"

    @property
    def logs(self):
        return self.root / "logs"

    @property
    def profile_blob(self):
        return self.profiles / "authenticated-profile.dpapi"


class WindowsDPAPI:
    """Protect bytes for the current Windows user without a reusable password."""

    class _Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_byte))]

    @classmethod
    def _call(cls, function_name, data):
        if os.name != "nt":
            raise ProfileProvisioningRequired("Windows DPAPI is unavailable")
        buffer = ctypes.create_string_buffer(data, len(data))
        source = cls._Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        result = cls._Blob()
        function = getattr(ctypes.windll.crypt32, function_name)
        if not function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
            raise ProfileProvisioningRequired("Windows DPAPI operation failed")
        try:
            return ctypes.string_at(result.data, result.size)
        finally:
            ctypes.windll.kernel32.LocalFree(result.data)

    def protect(self, data):
        return self._call("CryptProtectData", data)

    def unprotect(self, data):
        return self._call("CryptUnprotectData", data)


class DPAPIProfileStore:
    """Keep rclone config encrypted at rest and materialize it only at runtime."""

    def __init__(self, layout=None, protector=None):
        self.layout = layout or PikPakLocalLayout()
        self.protector = protector or WindowsDPAPI()

    def provision(self, source_config):
        data = Path(source_config).read_bytes()
        self.layout.profiles.mkdir(parents=True, exist_ok=True)
        self.layout.profile_blob.write_bytes(self.protector.protect(data))

    def materialize(self, runtime_config):
        if not self.layout.profile_blob.is_file():
            raise ProfileProvisioningRequired("Secure PikPak profile is missing")
        destination = Path(runtime_config)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            plaintext = self.protector.unprotect(self.layout.profile_blob.read_bytes())
        except Exception as error:
            raise ProfileProvisioningRequired("Secure PikPak profile is invalid") from error
        destination.write_bytes(plaintext)

    def cleanup(self, runtime_config):
        Path(runtime_config).unlink(missing_ok=True)


class AuthenticatedTransport:
    """Materialize a secure profile, start rclone, and always clean plaintext."""

    def __init__(self, profile_store, rclone_adapter, runtime_dir):
        self.profile_store = profile_store
        self.rclone = rclone_adapter
        self.runtime_dir = Path(runtime_dir)

    @contextmanager
    def open_for(self, media_filename):
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        config = self.runtime_dir / "rclone.conf"
        service = None
        try:
            self.profile_store.cleanup(config)
            self.profile_store.materialize(config)
            item = self.rclone.find_unique_file(config, media_filename)
            parent = str(Path(item["path"]).parent).replace("\\", "/")
            service = self.rclone.start_original_service(config, parent)
            url = f"{service['base_url'].rstrip('/')}/{quote(media_filename)}"
            yield OpenedOrigin(url, int(item["size"]))
        finally:
            if service is not None:
                self.rclone.stop_service(service)
            self.profile_store.cleanup(config)


def build_default_authenticated_transport(layout=None):
    """Build the normal zero-prompt transport from the per-user local layout."""
    from .rclone_adapter import RcloneAdapter

    layout = layout or PikPakLocalLayout()
    return AuthenticatedTransport(
        DPAPIProfileStore(layout),
        RcloneAdapter(layout.bin / "rclone.exe", layout=layout),
        layout.runtime,
    )
