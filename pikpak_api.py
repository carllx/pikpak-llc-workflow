import re
import json
import urllib.parse
import requests
import uuid
import time
import hashlib

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

def get_media_variants(share_url):
    match = re.search(r'/s/([^/]+)', share_url)
    if not match:
        raise ValueError("Invalid PikPak share URL")
    share_id = match.group(1)
    
    device_id = uuid.uuid4().hex
    client_id = "YUMx5nI8ZU8Ap8pm"
    client_version = "2.0.0"
    package_name = "mypikpak.com"
    
    captcha_token = get_captcha_token(device_id, client_id, client_version, package_name)
    
    headers = get_default_headers(device_id, client_id, client_version, package_name)
    if captcha_token:
        headers['x-captcha-token'] = captcha_token
        
    # 1. API-based share/detail
    detail_url = f"https://api-drive.mypikpak.com/drive/v1/share?share_id={share_id}"
    resp = requests.get(detail_url, headers=headers)
    resp.raise_for_status()
    
    share_data = resp.json()
    file_id = None
    pass_code_token = share_data.get('pass_code_token', '')
    
    if 'file' in share_data:
        file_id = share_data['file'].get('id')
    elif 'share' in share_data:
        file_id = share_data['share'].get('file_id')
    elif 'files' in share_data and share_data['files']:
        file_id = share_data['files'][0].get('id')

    if not file_id:
        raise ValueError(f"Could not extract file_id from API response. Got keys: {list(share_data.keys())}")

    # 2. Get file_info
    info_url = f"https://api-drive.mypikpak.com/drive/v1/share/file_info?share_id={share_id}&file_id={file_id}&pass_code_token={urllib.parse.quote(pass_code_token)}"
    info_resp = requests.get(info_url, headers=headers)
    info_resp.raise_for_status()
    file_info = info_resp.json()
    
    medias = []
    if 'medias' in file_info:
        medias = file_info['medias']
    elif 'file_info' in file_info and 'medias' in file_info['file_info']:
        medias = file_info['file_info']['medias']
    elif 'file' in file_info and 'medias' in file_info['file']:
        medias = file_info['file']['medias']
        
    if not medias:
        raise ValueError(f"No medias found. Found keys: {list(file_info.keys())}")
        
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
    Discover the 480P proxy URL from the share file info.
    """
    medias = get_media_variants(share_url)
    for m in medias:
        if str(m.get('resolution_name')).upper() == '480P':
            if 'link' in m and 'url' in m['link']:
                return m['link']['url']
                
    # Fallback to the first non-origin media if 480P doesn't exist
    for m in medias:
        if not m.get('is_origin') and m.get('category') != 'category_origin':
            if 'link' in m and 'url' in m['link']:
                return m['link']['url']
                
    raise ValueError("Proxy media (480P) not found in the variants.")

def download_proxy_video(share_url, output_path):
    """
    Downloads the 480P proxy video completely.
    """
    import urllib.request
    
    proxy_url = get_proxy_url(share_url)
    
    # We will use streaming requests or just a simple download tool
    # Here we can just use requests with streaming to download it to file
    with requests.get(proxy_url, stream=True) as r:
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                if chunk:
                    f.write(chunk)

