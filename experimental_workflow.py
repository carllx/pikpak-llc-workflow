"""Experimental real-use workflow with instrumented Origin extraction."""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from llc_parser import parse_llc
from pikpak_api import get_origin_url
from range_guard import RangeGuard, TransferLedger, fetch_exact_range


PROBE_RANGE = "bytes=0-65535"
IDENTITY_CHUNK_BYTES = 4 * 1024 * 1024


class WorkflowError(RuntimeError):
    pass


def normalize_share_url(value):
    if value.startswith(("http://", "https://")):
        return value
    return f"https://mypikpak.com/s/{value}"


def validate_segments(segments):
    if not segments:
        raise WorkflowError("LLC contains no validated cutSegments")
    for index, segment in enumerate(segments, start=1):
        start = segment["start"]
        end = segment["end"]
        if not math.isfinite(start) or not math.isfinite(end):
            raise WorkflowError(f"Segment {index} has a non-finite timestamp")
        if start < 0 or end <= start:
            raise WorkflowError(f"Segment {index} has an invalid time range")


def run_command(command, expect_json=False):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorkflowError(f"Command failed: {Path(command[0]).name}")
    if not expect_json:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Command returned invalid JSON: {Path(command[0]).name}") from error


def probe_media(path_or_url):
    return run_command(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size,format_name",
            "-show_entries", "stream=index,codec_type,codec_name",
            "-of", "json",
            str(path_or_url),
        ],
        expect_json=True,
    )


def packet_probe(path_or_url, read_interval=None):
    command = ["ffprobe", "-v", "error"]
    if read_interval:
        command.extend(["-read_intervals", read_interval])
    command.extend(
        [
            "-show_packets",
            "-show_entries",
            "packet=stream_index,codec_type,pts_time,dts_time,duration_time,size,flags,data_hash",
            "-show_data_hash", "sha256",
            "-of", "json",
            str(path_or_url),
        ]
    )
    return run_command(command, expect_json=True).get("packets", [])


def build_segment_command(ffmpeg, guard_url, segment, output_path):
    return [
        ffmpeg,
        "-v", "error",
        "-n",
        "-ss", format(segment["start"], ".15g"),
        "-to", format(segment["end"], ".15g"),
        "-i", guard_url,
        "-map", "0",
        "-c", "copy",
        str(output_path),
    ]


def safe_range_summary(ledger):
    events = ledger.events
    return {
        "RANGE_ONLY": "PASS" if events and all(event["range"] for event in events) else "FAIL",
        "UPSTREAM_HTTP_206": (
            "PASS" if events and all(event["status"] == 206 for event in events) else "FAIL"
        ),
        "HTTP_200_FULL_BODY": (
            "NONE" if all(event["status"] != 200 for event in events) else "DETECTED"
        ),
        "TOTAL_UPSTREAM_BYTES": ledger.total_upstream_bytes,
        "UPSTREAM_TRANSFERRED": ledger.total_upstream_bytes,
        "RANGE_EVENTS": events,
    }


def output_is_playable(probe):
    streams = probe.get("streams", [])
    duration = float(probe.get("format", {}).get("duration", 0) or 0)
    return duration > 0 and any(stream.get("codec_type") == "video" for stream in streams)


def stream_inventory(probe):
    return [
        {
            "index": stream.get("index"),
            "codec_type": stream.get("codec_type"),
            "codec_name": stream.get("codec_name"),
        }
        for stream in probe.get("streams", [])
    ]


def require_mp4_origin(probe):
    format_names = probe.get("format", {}).get("format_name", "").split(",")
    if "mp4" not in format_names:
        raise WorkflowError("Only MP4 Origin input is supported by this prototype")


def extract_with_guard(origin_url, segments, output_dir, ledger, limit=None):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or shutil.which("ffprobe") is None:
        raise WorkflowError("ffmpeg and ffprobe are required")
    selected = segments[:limit] if limit else segments
    destination = Path(output_dir)
    outputs = [destination / f"segment_{index:03d}.mp4" for index in range(1, len(selected) + 1)]
    conflicts = [path.name for path in outputs if path.exists()]
    if conflicts:
        raise WorkflowError("Refusing to overwrite existing segment output")
    destination.mkdir(parents=True, exist_ok=True)

    probes = []
    with RangeGuard(origin_url, ledger) as guard:
        source_probe = probe_media(guard.url)
        guard.raise_if_failed()
        require_mp4_origin(source_probe)
        source_inventory = stream_inventory(source_probe)
        for segment, output in zip(selected, outputs):
            run_command(build_segment_command(ffmpeg, guard.url, segment, output))
            guard.raise_if_failed()
            if not output.is_file() or output.stat().st_size == 0:
                raise WorkflowError("FFmpeg did not create a non-empty Origin segment")
            probe = probe_media(output)
            if not output_is_playable(probe):
                raise WorkflowError("Extracted Origin segment is not probeable")
            if stream_inventory(probe) != source_inventory:
                raise WorkflowError("Origin stream inventory was not preserved in MP4 output")
            probes.append(probe)
    return outputs, probes, source_inventory


def identity_sample_ranges(total_size, chunk_bytes=IDENTITY_CHUNK_BYTES):
    if total_size <= 0:
        raise WorkflowError("Origin total size must be positive")
    width = min(chunk_bytes, total_size)
    last_start = total_size - width
    starts = [round(last_start * fraction) for fraction in (0, 0.25, 0.5, 0.75, 1)]
    return [(start, start + width - 1) for start in starts]


def distributed_identity(origin_url, local_path, origin_total, ledger):
    local_file = Path(local_path)
    local_size = local_file.stat().st_size
    if local_size != origin_total:
        raise WorkflowError("Official local file size differs from Origin total")
    samples = []
    with local_file.open("rb") as local:
        for start, end in identity_sample_ranges(local_size):
            local.seek(start)
            local_bytes = local.read(end - start + 1)
            remote_bytes, reported_total = fetch_exact_range(
                origin_url, f"bytes={start}-{end}", ledger
            )
            passed = (
                reported_total == local_size
                and hashlib.sha256(remote_bytes).digest()
                == hashlib.sha256(local_bytes).digest()
            )
            samples.append(
                {
                    "range": f"bytes={start}-{end}",
                    "remote_total": reported_total,
                    "sha256_identical": passed,
                }
            )
    if not all(sample["sha256_identical"] for sample in samples):
        raise WorkflowError("Distributed identity sample mismatch")
    return samples


def map_packet_sequence(source_packets, output_packets):
    source_by_hash = {}
    for index, packet in enumerate(source_packets):
        source_by_hash.setdefault(packet.get("data_hash"), []).append(index)

    mappings = []
    unmatched = []
    previous_source_by_stream = {}
    for output_index, packet in enumerate(output_packets):
        candidates = source_by_hash.get(packet.get("data_hash"), [])
        stream_index = packet.get("stream_index")
        source_index = next(
            (
                index
                for index in candidates
                if index > previous_source_by_stream.get(stream_index, -1)
                and source_packets[index].get("stream_index") == stream_index
                and source_packets[index].get("codec_type") == packet.get("codec_type")
            ),
            None,
        )
        if source_index is None:
            unmatched.append(
                {
                    "output_index": output_index,
                    "hash_in_source_window": bool(candidates),
                    **{
                        key: packet.get(key)
                        for key in (
                            "stream_index", "codec_type", "pts_time", "dts_time",
                            "duration_time", "size", "flags", "data_hash",
                        )
                    },
                }
            )
            continue
        mappings.append((output_index, source_index))
        previous_source_by_stream[stream_index] = source_index

    first_video = next(
        (
            (output_index, source_index)
            for output_index, source_index in mappings
            if output_packets[output_index].get("codec_type") == "video"
        ),
        None,
    )
    timestamp_offsets = {}
    timestamp_mapped = True
    for output_index, source_index in mappings:
        output_packet = output_packets[output_index]
        source_packet = source_packets[source_index]
        stream_index = output_packet.get("stream_index")
        output_time = output_packet.get("pts_time") or output_packet.get("dts_time")
        source_time = source_packet.get("pts_time") or source_packet.get("dts_time")
        if output_time is None or source_time is None:
            timestamp_mapped = False
            continue
        offset = float(output_time) - float(source_time)
        baseline = timestamp_offsets.setdefault(stream_index, offset)
        if abs(offset - baseline) > 0.002:
            timestamp_mapped = False
    if len(mappings) != len(output_packets):
        timestamp_mapped = False
    return mappings, unmatched, first_video, timestamp_mapped


def packet_acceptance(guard, segment, output_path):
    source_start = max(0, segment["start"] - 5)
    source_duration = segment["end"] - segment["start"] + 10
    source_packets = packet_probe(
        guard.url,
        f"{format(source_start, '.15g')}%+{format(source_duration, '.15g')}",
    )
    guard.raise_if_failed()
    output_packets = packet_probe(output_path)
    mappings, unmatched, first_video, timestamp_mapped = map_packet_sequence(
        source_packets, output_packets
    )
    mapping_details = [
        {
            "output_index": output_index,
            "source_index": source_index,
            "stream_index": output_packets[output_index].get("stream_index"),
            "codec_type": output_packets[output_index].get("codec_type"),
            "output_pts": output_packets[output_index].get("pts_time"),
            "source_pts": source_packets[source_index].get("pts_time"),
            "data_hash": output_packets[output_index].get("data_hash"),
        }
        for output_index, source_index in mappings
    ]

    first_source = None
    preroll = None
    keyframe = None
    if first_video is not None:
        _, source_index = first_video
        first_source = source_packets[source_index]
        source_pts = float(first_source["pts_time"])
        preroll = segment["start"] - source_pts
        keyframe = (
            first_source.get("codec_type") == "video"
            and "K" in (first_source.get("flags") or "")
        )
    return {
        "SOURCE_PACKET_COUNT": len(source_packets),
        "SEGMENT_PACKET_COUNT": len(output_packets),
        "PACKET_MATCH": f"{len(mappings)}/{len(output_packets)}",
        "PACKET_SEQUENCE_STRICT": len(mappings) == len(output_packets) and not unmatched,
        "PACKET_TIMESTAMP_MAPPED": timestamp_mapped,
        "PACKET_MAPPINGS": mapping_details,
        "UNMATCHED_PACKETS": unmatched,
        "FIRST_SOURCE_PACKET": (
            {
                key: first_source.get(key)
                for key in (
                    "stream_index", "codec_type", "pts_time", "dts_time",
                    "duration_time", "size", "flags", "data_hash",
                )
            }
            if first_source
            else None
        ),
        "KEYFRAME_ALIGNED": keyframe,
        "PREROLL_SECONDS": preroll,
    }


def _initial_report(mode, max_origin_bytes):
    return {
        "MODE": mode,
        "STATUS": "FAIL",
        "MAX_ORIGIN_BYTES": max_origin_bytes,
    }


def verification_evidence_passes(report):
    return (
        report["OUTPUT_PLAYABLE"]
        and report["PACKET_SEQUENCE_STRICT"]
        and report["PACKET_TIMESTAMP_MAPPED"]
        and report["KEYFRAME_ALIGNED"] is True
        and report["STREAM_INVENTORY_PRESERVED"] is True
    )


def segments_mode(share, llc_path, output_dir, max_origin_bytes):
    report = _initial_report("segments", max_origin_bytes)
    ledger = TransferLedger(max_origin_bytes)
    try:
        segments = parse_llc(llc_path)
        validate_segments(segments)
        origin_url = get_origin_url(normalize_share_url(share))
        _, origin_total = fetch_exact_range(origin_url, PROBE_RANGE, ledger)
        outputs, probes, source_inventory = extract_with_guard(
            origin_url, segments, output_dir, ledger
        )
        report.update(
            {
                "STATUS": "PASS",
                "CUT_SEGMENTS": len(segments),
                "ORIGIN_TOTAL": origin_total,
                "OUTPUTS": [str(path) for path in outputs],
                "OUTPUT_PLAYABLE": all(output_is_playable(probe) for probe in probes),
                "SOURCE_STREAM_INVENTORY": source_inventory,
                "STREAM_INVENTORY_PRESERVED": True,
            }
        )
    except Exception as error:
        report["ERROR_TYPE"] = type(error).__name__
    report.update(safe_range_summary(ledger))
    if (
        report.get("RANGE_ONLY") != "PASS"
        or report.get("UPSTREAM_HTTP_206") != "PASS"
        or report.get("HTTP_200_FULL_BODY") != "NONE"
    ):
        report["STATUS"] = "FAIL"
    return report


def verify_mode(
    share,
    llc_path,
    output_dir,
    max_origin_bytes,
    official_file=None,
):
    report = _initial_report("verify", max_origin_bytes)
    ledger = TransferLedger(max_origin_bytes)
    try:
        segments = parse_llc(llc_path)
        validate_segments(segments)
        first_segment = segments[0]
        origin_url = get_origin_url(normalize_share_url(share))
        _, origin_total = fetch_exact_range(origin_url, PROBE_RANGE, ledger)
        report["ORIGIN_TOTAL"] = origin_total

        if official_file:
            samples = distributed_identity(
                origin_url, official_file, origin_total, ledger
            )
            report["IDENTITY_SAMPLES"] = f"{len(samples)}/{len(samples)} PASS"
            report["IDENTITY_DETAILS"] = samples
        else:
            report["IDENTITY_SAMPLES"] = "SKIPPED (official local file not provided)"

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None or shutil.which("ffprobe") is None:
            raise WorkflowError("ffmpeg and ffprobe are required")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / "verification_segment.mp4"
        if output.exists():
            raise WorkflowError("Refusing to overwrite verification output")

        with RangeGuard(origin_url, ledger) as guard:
            source_probe = probe_media(guard.url)
            guard.raise_if_failed()
            require_mp4_origin(source_probe)
            source_inventory = stream_inventory(source_probe)
            report["SOURCE_STREAM_INVENTORY"] = source_inventory
            run_command(build_segment_command(ffmpeg, guard.url, first_segment, output))
            guard.raise_if_failed()
            if not output.is_file() or output.stat().st_size == 0:
                raise WorkflowError("FFmpeg did not create a non-empty verification segment")
            output_probe = probe_media(output)
            output_inventory = stream_inventory(output_probe)
            report["OUTPUT_STREAM_INVENTORY"] = output_inventory
            report["STREAM_INVENTORY_PRESERVED"] = (
                output_inventory == source_inventory
            )
            packet_report = packet_acceptance(guard, first_segment, output)

        output_size = int(output_probe.get("format", {}).get("size", 0) or 0)
        selected_duration = first_segment["end"] - first_segment["start"]
        report.update(packet_report)
        transfer_ratio = ledger.total_upstream_bytes / origin_total
        report.update(
            {
                "SELECTED_DURATION": selected_duration,
                "OUTPUT_SIZE": output_size,
                "OUTPUT_PLAYABLE": output_is_playable(output_probe),
                "STREAM_COPY": "PASS",
                "UPSTREAM_TRANSFERRED": ledger.total_upstream_bytes,
                "TRANSFER_RATIO": transfer_ratio,
            }
        )
        report["STATUS"] = "PASS" if verification_evidence_passes(report) else "FAIL"
    except Exception as error:
        report["ERROR_TYPE"] = type(error).__name__
    report.update(safe_range_summary(ledger))
    if (
        report.get("RANGE_ONLY") != "PASS"
        or report.get("UPSTREAM_HTTP_206") != "PASS"
        or report.get("HTTP_200_FULL_BODY") != "NONE"
    ):
        report["STATUS"] = "FAIL"
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        description="Experimental PikPak LLC workflow with guarded Origin transfers"
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("segments", "verify"):
        command = subparsers.add_parser(mode)
        command.add_argument("share", help="PikPak share URL or token")
        command.add_argument("llc", help="LosslessCut .llc file")
        command.add_argument("output_dir", help="Output directory")
        command.add_argument("--max-origin-bytes", type=int, required=True)
        if mode == "verify":
            command.add_argument("--official-file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.mode == "segments":
        report = segments_mode(
            args.share, args.llc, args.output_dir, args.max_origin_bytes
        )
    else:
        report = verify_mode(
            args.share,
            args.llc,
            args.output_dir,
            args.max_origin_bytes,
            official_file=args.official_file,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
