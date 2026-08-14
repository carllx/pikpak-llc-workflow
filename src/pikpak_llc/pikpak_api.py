import re
import json
import urllib.parse
import requests
import uuid
import time
import hashlib
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov",
    ".mp4", ".mpeg", ".mpg", ".mts", ".ts", ".webm", ".wmv",
}


class ProxyVariantNotFound(ValueError):
    pass

def get_default_headers(device_id, client_id, client_version, package_name):
    return {
      'x-device-id': device_id,
      'x-client-id': client_id,
      'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

def generate_captcha_sign(client_id, client_version, package_name, device_id, timestamp_str):
    # Complete published WEB_ALGORITHMS sequence
    WEB_ALGORITHMS = [
        "C9qPpZLN8ucRTaTiUMWYS9cQvWOE",
        "+r6CQVxjzJV6LCV",
        "F",
        "pFJRC",
        "9WXYIDGrwTCz2OiVlgZa90qpECPD6olt",
        "/750aCr4lm/Sly/c",
        "RB+DT/gZCrbV",
        "",
        "CyLsf7hdkIRxRm215hl",
        "7xHvLi2tOYP0Y92b",
        "ZGTXXxu8E/MIWaEDB+Sm/",
        "1UI3",
        "E7fP5Pfijd+7K+t6Tg/NhuLq0eEUVChpJSkrKxpO",
        "ihtqpG6FMt65+Xk+tWUH2",
        "NhXXU9rg4XXdzo7u5o",
    ]
    base = f"{client_id}{client_version}{package_name}{device_id}{timestamp_str}"
    for salt in WEB_ALGORITHMS:
        base = hashlib.md5((base + salt).encode('utf-8')).hexdigest()
    return f"1.{base}"

def get_captcha_token(device_id, client_id, client_version, package_name):
    url = 'https://user.mypikpak.com/v1/shield/captcha/init'
    headers = get_default_headers(device_id, client_id, client_version, package_name)
    
    timestamp = str(int(time.time() * 1000))
    captcha_sign = generate_captcha_sign(client_id, client_version, package_name, device_id, timestamp)
    
    data = {
        'action': 'GET:/drive/v1/share',
        'client_id': client_id,
        'device_id': device_id,
        'meta': {
            'captcha_sign': captcha_sign,
            'client_version': client_version,
            'package_name': package_name,
            'user_id': '',
            'timestamp': timestamp
        }
    }
    
    resp = requests.post(url, json=data, headers=headers)
    resp.raise_for_status()
    return resp.json().get('captcha_token', '')

def _candidate_type(item, direct_file=False):
    kind = str(item.get("kind") or item.get("type") or "").lower()
    if "folder" in kind:
        return "non_video"
    mime_type = str(item.get("mime_type") or item.get("mimeType") or "").lower()
    category = str(item.get("category") or "").lower()
    filename = item.get("name") or item.get("file_name") or ""
    if mime_type.startswith("video/") or category in {"video", "category_video"}:
        return "video"
    if Path(filename).suffix.lower() in VIDEO_EXTENSIONS:
        return "video"
    return "video" if direct_file and not mime_type and not category else "non_video"


def _share_items(share_data):
    if isinstance(share_data.get("file"), dict):
        return [(share_data["file"], True)]
    if isinstance(share_data.get("share"), dict):
        item = {
            "id": share_data["share"].get("file_id"),
            "name": share_data["share"].get("file_name", "download"),
            "mime_type": share_data["share"].get("mime_type"),
            "category": share_data["share"].get("category"),
        }
        return [(item, True)]
    return [(item, False) for item in share_data.get("files", [])]


class ShareMediaClient:
    """One resolved Share session with stable file-id media access."""

    def __init__(self, share_id, pass_code_token, headers, files):
        self.share_id = share_id
        self.pass_code_token = pass_code_token
        self.headers = headers
        self.files = files

    @classmethod
    def open(cls, share_url):
        match = re.search(r'/s/([^/]+)', share_url)
        if not match:
            raise ValueError("Invalid PikPak share URL")
        share_id = match.group(1)
        device_id = uuid.uuid4().hex
        client_id = "YUMx5nI8ZU8Ap8pm"
        client_version = "2.0.0"
        package_name = "mypikpak.com"
        captcha_token = get_captcha_token(
            device_id, client_id, client_version, package_name
        )
        headers = get_default_headers(
            device_id, client_id, client_version, package_name
        )
        if captcha_token:
            headers['x-captcha-token'] = captcha_token
        detail_url = (
            "https://api-drive.mypikpak.com/drive/v1/share"
            f"?share_id={share_id}"
        )
        response = requests.get(detail_url, headers=headers)
        response.raise_for_status()
        share_data = response.json()
        files = []
        for item, direct_file in _share_items(share_data):
            file_id = item.get("id")
            if not file_id:
                continue
            files.append(
                {
                    "file_id": file_id,
                    "filename": item.get("name", "download"),
                    "candidate_type": _candidate_type(item, direct_file),
                }
            )
        if not files:
            raise ValueError("Share contains no identifiable files")
        return cls(
            share_id,
            share_data.get('pass_code_token', ''),
            headers,
            files,
        )

    def media_variants_for_file(self, file_id):
        if file_id not in {item["file_id"] for item in self.files}:
            raise ValueError("file_id is not part of this Share")
        info_url = (
            "https://api-drive.mypikpak.com/drive/v1/share/file_info"
            f"?share_id={self.share_id}&file_id={file_id}"
            f"&pass_code_token={urllib.parse.quote(self.pass_code_token)}"
        )
        response = requests.get(info_url, headers=self.headers)
        response.raise_for_status()
        file_info = response.json()
        medias = file_info.get("medias")
        if medias is None:
            medias = file_info.get("file_info", {}).get("medias")
        if medias is None:
            medias = file_info.get("file", {}).get("medias")
        if not medias:
            raise ValueError(f"No media variants found for file_id {file_id}")
        return medias

    def proxy_for_file(self, file_id):
        for media in self.media_variants_for_file(file_id):
            if str(media.get("resolution_name")).upper() == "480P":
                url = media.get("link", {}).get("url")
                if url:
                    return url
        raise ProxyVariantNotFound(f"480P proxy not found for file_id {file_id}")

    def origin_for_file(self, file_id):
        for media in self.media_variants_for_file(file_id):
            if media.get("is_origin") or media.get("category") == "category_origin":
                url = media.get("link", {}).get("url")
                if url:
                    return url
        raise ValueError(f"Origin media not found for file_id {file_id}")


def list_share_files(share_url):
    return ShareMediaClient.open(share_url).files


def get_media_variants_for_file(share_url, file_id):
    return ShareMediaClient.open(share_url).media_variants_for_file(file_id)


def get_proxy_for_file(share_url, file_id):
    return ShareMediaClient.open(share_url).proxy_for_file(file_id)


def get_origin_for_file(share_url, file_id):
    return ShareMediaClient.open(share_url).origin_for_file(file_id)


def _single_file_client(share_url):
    client = ShareMediaClient.open(share_url)
    if len(client.files) != 1:
        raise ValueError("Single-file helper requires exactly one Share file")
    return client, client.files[0]


def _get_media_variants_with_filename(share_url):
    client, file = _single_file_client(share_url)
    return client.media_variants_for_file(file["file_id"]), file["filename"]


def get_media_variants(share_url):
    """Compatibility wrapper returning a list for a single-file Share."""
    medias, _ = _get_media_variants_with_filename(share_url)
    return medias

def download_range(url, bytes_range="0-65535", max_bytes=65536):
    headers = {'Range': f'bytes={bytes_range}'}
    resp = requests.get(url, headers=headers, stream=True)
    
    if resp.status_code == 200:
        resp.close()
        raise ValueError("Server returned 200 OK (full file). Aborting.")
    elif resp.status_code != 206:
        resp.close()
        raise ValueError(f"Server did not return 206 Partial Content. Status: {resp.status_code}")
        
    content_range = resp.headers.get('Content-Range')
    if not content_range:
        resp.close()
        raise ValueError("Missing Content-Range header")
        
    # Structural parse of Content-Range: bytes START-END/TOTAL
    match = re.match(r'^bytes\s+(\d+)-(\d+)/(?:\d+|\*)$', content_range.strip(), re.IGNORECASE)
    if not match:
        resp.close()
        raise ValueError(f"Malformed Content-Range header: {content_range}")
        
    start_resp, end_resp = int(match.group(1)), int(match.group(2))
    
    # Parse requested range
    req_match = re.match(r'^(\d+)-(\d+)$', bytes_range.strip())
    if not req_match:
        resp.close()
        raise ValueError(f"Invalid requested bytes_range format: {bytes_range}")
        
    start_req, end_req = int(req_match.group(1)), int(req_match.group(2))
    
    if start_resp != start_req or end_resp != end_req:
        resp.close()
        raise ValueError(f"Content-Range mismatch: requested {start_req}-{end_req}, got {start_resp}-{end_resp}")
        
    downloaded = bytearray()
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            downloaded.extend(chunk)
            if len(downloaded) >= max_bytes:
                break
                
    resp.close()
    
    result = bytes(downloaded[:max_bytes])
    expected_length = end_req - start_req + 1
    if len(result) != expected_length:
        raise ValueError(f"Incomplete download: expected {expected_length} bytes, got {len(result)} bytes")
        
    return result

def get_origin_url(share_url):
    """
    Discover the Origin URL from the share file info.
    It inspects the medias[] array for the is_origin flag or category_origin.
    """
    medias = get_media_variants(share_url)
    for m in medias:
        if m.get('is_origin') or m.get('category') == 'category_origin':
            if 'link' in m and 'url' in m['link']:
                return m['link']['url']
    
    raise ValueError("Origin media not found in the variants.")

def get_proxy_url(share_url):
    """
    Discover the 480P proxy URL and original filename from the share file info.
    Returns (url, filename)
    """
    medias, filename = _get_media_variants_with_filename(share_url)
    for m in medias:
        if str(m.get('resolution_name')).upper() == '480P':
            if 'link' in m and 'url' in m['link']:
                return m['link']['url'], filename
                
    raise ValueError("Proxy media (480P) strictly not found in the variants. No silent fallback allowed.")


def _matching_stem(filename):
    stem = Path(filename).stem.casefold()
    for suffix in ("_h264", "-h264", "_p480", "-p480"):
        if stem.endswith(suffix):
            return stem[:-len(suffix)]
    return stem


def select_share_video(files, media_filename):
    """Select one video by unique filename or normalized proxy stem."""
    if not media_filename:
        raise ValueError("LLC mediaFileName is required for source selection")
    videos = [item for item in files if item["candidate_type"] == "video"]
    requested_name = Path(media_filename).name.casefold()
    exact = [item for item in videos if item["filename"].casefold() == requested_name]
    matches = exact or [
        item
        for item in videos
        if _matching_stem(item["filename"]) == _matching_stem(media_filename)
    ]
    if not matches:
        raise ValueError("LLC mediaFileName does not match a Share video")
    if len(matches) != 1:
        raise ValueError("LLC mediaFileName matches multiple Share videos")
    return matches[0]

def download_proxy_video(share_url, output_path):
    """
    Downloads the 480P proxy video completely.
    """
    import urllib.request
    
    proxy_url, _ = get_proxy_url(share_url)
    
    # We will use streaming requests or just a simple download tool
    # Here we can just use requests with streaming to download it to file
    with requests.get(proxy_url, stream=True) as r:
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                if chunk:
                    f.write(chunk)

