"""Extract LosslessCut selections from a remote PikPak Origin media URL."""

import argparse
import math
import shutil
import subprocess
from pathlib import Path

from llc_parser import parse_llc
from pikpak_api import download_range, get_origin_url


RANGE_PROBE = "0-65535"
RANGE_PROBE_BYTES = 65536


def normalize_share_url(value):
    """Accept either a complete PikPak share URL or its share token."""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://mypikpak.com/s/{value}"


def _format_timestamp(value):
    return format(value, ".15g")


def _validate_segments(segments):
    if not segments:
        raise ValueError("LLC file contains no cut segments")

    for index, segment in enumerate(segments, start=1):
        start = segment["start"]
        end = segment["end"]
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError(f"Segment {index} has a non-finite timestamp")
        if start < 0 or end <= start:
            raise ValueError(f"Segment {index} has an invalid time range: {start} -> {end}")


def _run_ffmpeg(ffmpeg, origin_url, start, end, output_path):
    command = [
        ffmpeg,
        "-v",
        "error",
        "-n",
        "-ss",
        _format_timestamp(start),
        "-to",
        _format_timestamp(end),
        "-i",
        origin_url,
        "-c",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return

    output_path.unlink(missing_ok=True)
    detail = result.stderr.strip() or f"exit code {result.returncode}"
    raise RuntimeError(f"FFmpeg failed for {output_path.name}: {detail}")


def extract_origin_segments(share_url, llc_path, output_dir, ffmpeg="ffmpeg"):
    """Validate Origin Range support and stream-copy every LLC cut segment."""
    segments = parse_llc(llc_path)
    _validate_segments(segments)

    ffmpeg_path = shutil.which(ffmpeg)
    if ffmpeg_path is None:
        raise FileNotFoundError(f"FFmpeg executable not found: {ffmpeg}")

    destination = Path(output_dir)
    outputs = [
        destination / f"segment_{index:03d}.mp4"
        for index in range(1, len(segments) + 1)
    ]
    conflicts = [path for path in outputs if path.exists()]
    if conflicts:
        names = ", ".join(path.name for path in conflicts)
        raise FileExistsError(f"Refusing to overwrite existing output(s): {names}")

    origin_url = get_origin_url(normalize_share_url(share_url))

    # Mandatory safety gate: download_range aborts before consuming a 200 body.
    download_range(origin_url, RANGE_PROBE, RANGE_PROBE_BYTES)

    destination.mkdir(parents=True, exist_ok=True)
    for output_path, segment in zip(outputs, segments):
        _run_ffmpeg(
            ffmpeg_path,
            origin_url,
            segment["start"],
            segment["end"],
            output_path,
        )
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stream-copy LLC selections from a PikPak Origin URL"
    )
    parser.add_argument("share_url", help="PikPak share URL or share token")
    parser.add_argument("llc_file", help="LosslessCut .llc project file")
    parser.add_argument("output_dir", help="Directory for segment_NNN.mp4 outputs")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable")
    args = parser.parse_args(argv)

    outputs = extract_origin_segments(
        args.share_url,
        args.llc_file,
        args.output_dir,
        ffmpeg=args.ffmpeg,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
