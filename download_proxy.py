import os
import sys
import requests
from pikpak_api import get_proxy_url
import subprocess
import shutil

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

def download_proxy(share_url, output_path=None):
    print("Resolving proxy URL for the provided share...")
    
    try:
        proxy_url, file_name = get_proxy_url(share_url)
    except Exception as e:
        print(f"Error resolving proxy URL: {e}")
        sys.exit(1)
        
    # Determine the final output path based on user input and API filename
    if not output_path:
        output_path = file_name
    elif os.path.isdir(output_path):
        output_path = os.path.join(output_path, file_name)

    print(f"Target URL resolved. Original filename: {file_name}")
    print(f"Starting download to: {output_path}")
    
    try:
        with requests.get(proxy_url, stream=True) as r:
            r.raise_for_status()
            
            # Simple progress reporting
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192*4):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB ({percent:.1f}%)")
                        else:
                            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.2f} MB")
                        sys.stdout.flush()
                        
            print("\nDownload complete!")
    except Exception as e:
        print(f"\nError during download: {e}")
        sys.exit(1)

    # Automatically transcode to highly compatible H.264 MP4 using FFmpeg if available
    if shutil.which("ffmpeg"):
        encoder = check_hw_encoder()
        
        if encoder == "libx264":
            print("\nWARNING: No hardware encoder detected (NVENC/QSV/AMF). Falling back to CPU libx264.")
            print("This may take a significant amount of time depending on your CPU.")
        else:
            print(f"\nHardware encoder '{encoder}' detected. Proceeding with fast hardware transcode.")
            
        final_mp4 = os.path.splitext(output_path)[0] + ".mp4"
        temp_output = final_mp4 + ".tmp.mp4"
        
        try:
            cmd = build_transcode_command(output_path, temp_output, encoder)
            subprocess.run(cmd, check=True)
            
            os.replace(temp_output, final_mp4)
            # Retain original TS? "C. 保留原始下载文件直到兼容输出验证成功。"
            # It successfully transcoded. But let's follow explicit instructions to retain it for debugging.
            # "保留原始下载文件" implies we shouldn't delete it immediately.
            # We'll just leave `output_path` intact.
            print(f"Transcoding complete! File is ready for LosslessCut: {final_mp4}")
            print(f"Original file retained at: {output_path}")
        except Exception as e:
            print(f"FFmpeg transcoding failed (original file kept): {e}")
    else:
        print("Warning: FFmpeg not found on system PATH. Output may be an incompatible MPEG-TS stream disguised as .mp4.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python download_proxy.py <share_url> [output_file_or_dir]")
        sys.exit(1)
        
    share_url = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    # If the URL is just an ID, construct the full URL
    if not share_url.startswith("http"):
        share_url = f"https://mypikpak.com/s/{share_url}"
        
    download_proxy(share_url, output_path)
