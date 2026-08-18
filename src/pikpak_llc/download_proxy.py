import os
import sys
import json
import requests
from .pikpak_api import ProxyVariantNotFound, ShareMediaClient
import subprocess
import shutil
from pathlib import Path

from .workspace import JobWorkspace
from .operator_preflight import OperatorPreflightError, run_operator_preflight

def build_encoder_args(encoder):
    """Return the production encoding profile for a supported H.264 encoder."""
    profiles = {
        "h264_nvenc": [
            "-c:v", "h264_nvenc", "-preset", "p4",
            "-rc", "vbr", "-cq", "23", "-b:v", "0",
        ],
        "h264_qsv": [
            "-c:v", "h264_qsv", "-preset", "fast",
            "-global_quality", "23",
        ],
        "h264_amf": [
            "-c:v", "h264_amf", "-quality", "balanced",
            "-rc", "cqp", "-qp_i", "23", "-qp_p", "23",
        ],
        "libx264": [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        ],
    }
    try:
        return profiles[encoder].copy()
    except KeyError as error:
        raise ValueError(f"Unsupported encoder profile: {encoder}") from error

def _can_encode_with(encoder):
    """Probe one frame using the same profile as production transcoding."""
    command = [
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
        "-frames:v", "1", "-an",
        *build_encoder_args(encoder),
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0

def check_hw_encoder():
    """Select the first hardware encoder that passes a real encode probe."""
    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        if _can_encode_with(encoder):
            return encoder
    return "libx264"

def build_transcode_command(input_path, output_path, encoder):
    """Build the production FFmpeg command from the shared encoder profile."""
    return [
        "ffmpeg", "-y", "-i", input_path,
        *build_encoder_args(encoder),
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]


def _proxy_output_paths(filename, output_path, multiple):
    if multiple:
        destination = Path(output_path or ".")
        if destination.exists() and not destination.is_dir():
            raise ValueError("Folder Share output must be a directory")
        destination.mkdir(parents=True, exist_ok=True)
        raw_output = destination / filename
    elif output_path and Path(output_path).is_dir():
        raw_output = Path(output_path) / filename
    else:
        raw_output = Path(output_path or filename)
    compatible = (
        raw_output.with_name(f"{raw_output.stem}_h264.mp4")
        if raw_output.suffix.lower() == ".mp4"
        else raw_output.with_suffix(".mp4")
    )
    return raw_output, compatible


def _probe_compatible_proxy(output_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name:format=duration",
            "-of", "json", str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        probe = json.loads(result.stdout)
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        h264 = any(
            stream.get("codec_name") == "h264"
            for stream in probe.get("streams", [])
        )
    except (ValueError, TypeError):
        duration, h264 = 0, False
    if result.returncode != 0 or not h264 or duration <= 0:
        raise RuntimeError("Compatible proxy ffprobe validation failed")


def _download_and_transcode(proxy_url, raw_output, compatible_output, encoder):
    if raw_output.exists() or compatible_output.exists():
        raise FileExistsError("Refusing to overwrite an existing proxy output")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(proxy_url, stream=True) as response:
        response.raise_for_status()
        with raw_output.open("wb") as destination:
            for chunk in response.iter_content(chunk_size=8192 * 4):
                if chunk:
                    destination.write(chunk)
    temp_output = compatible_output.with_name(f"{compatible_output.name}.tmp.mp4")
    subprocess.run(
        build_transcode_command(raw_output, temp_output, encoder),
        check=True,
    )
    os.replace(temp_output, compatible_output)
    _probe_compatible_proxy(compatible_output)


def download_proxy(share_url, output_path=None):
    """Prepare P480/H.264 proxies for every video in a Share."""
    client = ShareMediaClient.open(share_url)
    candidates = [
        item for item in client.files if item["candidate_type"] == "video"
    ]
    if not candidates:
        raise ValueError("Share contains zero video candidates")
    if output_path is None:
        raise ValueError("Proxy downloads require an explicit output path")
    destination = Path(output_path).resolve()
    working_directory = Path.cwd().resolve()
    if destination == working_directory or destination.parent == working_directory:
        raise ValueError("Proxy output must not target the repository root")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required")
    encoder = check_hw_encoder()
    report = []
    for candidate in candidates:
        item = {
            "file_id": candidate["file_id"],
            "filename": candidate["filename"],
            "status": "FAIL",
        }
        try:
            proxy_url = client.proxy_for_file(candidate["file_id"])
            raw_output, compatible_output = _proxy_output_paths(
                candidate["filename"], output_path, len(candidates) > 1
            )
            _download_and_transcode(
                proxy_url, raw_output, compatible_output, encoder
            )
            item.update(
                {
                    "status": "PASS",
                    "raw_proxy": str(raw_output),
                    "compatible_proxy": str(compatible_output),
                }
            )
        except Exception as error:
            item["error_type"] = type(error).__name__
        report.append(item)
    return report


def prepare_share_proxies(share_url, workspace_root="workspace"):
    """Create one Share Job and prepare every proxy inside its public proxy dir."""
    workspace = JobWorkspace(workspace_root)
    job = workspace.start_share(share_url)
    files = download_proxy(share_url, job.proxies)
    job_proxies_dir = job.proxies.resolve()
    for item in files:
        if item.get("status") == "PASS":
            raw_path = Path(item.get("raw_proxy", "")).resolve()
            comp_path = Path(item.get("compatible_proxy", "")).resolve()
            try:
                raw_path.relative_to(job_proxies_dir)
                comp_path.relative_to(job_proxies_dir)
            except ValueError:
                item["status"] = "FAIL"
                item["error_type"] = "WorkspaceJobMismatch"
    return {**workspace.public_output_paths(job=job), "files": files}

def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        run_operator_preflight()
    except OperatorPreflightError as error:
        print(json.dumps({"STATUS": "FAIL", "ERROR": error.code}))
        return 1
    if len(args) < 1:
        print("Usage: python download_proxy.py <share_url> [output_file_or_dir]")
        return 1
        
    share_url = args[0]
    output_path = args[1] if len(args) > 1 else None
    
    # If the URL is just an ID, construct the full URL
    if not share_url.startswith("http"):
        share_url = f"https://mypikpak.com/s/{share_url}"
        
    try:
        result = (
            download_proxy(share_url, output_path)
            if output_path
            else prepare_share_proxies(share_url)
        )
    except Exception as error:
        result = [{"status": "FAIL", "error_type": type(error).__name__}]
    batch = result.get("files", []) if isinstance(result, dict) else result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "PASS" for item in batch) else 1


if __name__ == '__main__':
    raise SystemExit(main())
