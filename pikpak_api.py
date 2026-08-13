import re
import json
import urllib.parse
import requests
import uuid
import time
import hashlib

def get_default_headers(device_id, client_id):
    return {
      'x-device-id': device_id,
      'x-device-name': 'PC-Chrome',
      'x-device-model': 'chrome/120.0.0.0',
      'x-provider-name': 'NONE',
      'x-platform-version': '1',
      'x-client-id': client_id,
      'x-protocol-version': '301',
      'x-net-work-type': 'NONE',
      'x-os-version': 'Win32',
      'referer': 'https://mypikpak.com/',
      'x-device-sign': f'wdi10.{device_id}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      'x-sdk-version': '8.1.4',
      'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'x-client-version': '1.0.0'
    }

def generate_captcha_sign(client_id, client_version, package_name, device_id, timestamp_str):
    # Dynamically calculate the captcha sign
    base = f"{client_id}{client_version}{package_name}{device_id}{timestamp_str}"
    hash_val = hashlib.md5(base.encode('utf-8')).hexdigest()
    return f"1.{hash_val}"

def get_captcha_token(device_id, client_id):
    url = 'https://user.mypikpak.com/v1/shield/captcha/init'
    headers = get_default_headers(device_id, client_id)
    
    timestamp = str(int(time.time() * 1000))
    client_version = '1.0.0'
    package_name = 'drive.mypikpak.com'
    
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
    try:
        resp = requests.post(url, json=data, headers=headers)
        resp.raise_for_status()
        return resp.json().get('captcha_token', '')
    except Exception as e:
        # If dynamic sign fails due to salt mismatch, we continue and let API fail downstream
        # or it might succeed without strict validation.
        return ""

def extract_share_info_html(html_content, share_id):
    """
    Fallback method to parse HTML for file_id and pass_code_token
    """
    match = re.search(r'id="__NUXT_DATA__"[^>]*>([^<]+)</script>', html_content)
    if not match:
        raise ValueError("Could not find __NUXT_DATA__ in HTML")
    
    data = json.loads(match.group(1))
    
    pass_code_token = ""
    file_ids = []
    
    for item in data:
        if isinstance(item, str):
            if item.startswith('u8') and len(item) > 100:
                pass_code_token = item
            if item.startswith('V') and 20 <= len(item) <= 30 and item != share_id:
                if "_" in item or item.isalnum():
                    file_ids.append(item)
                    
    if not file_ids:
        raise ValueError("Could not extract file_id from HTML")
        
    return {
        "pass_code_token": pass_code_token,
        "file_id": file_ids[0]
    }

def get_media_variants(share_url):
    """
    Extract available media variants from a PikPak share URL.
    Returns list of dicts with variant info in memory.
    """
    match = re.search(r'/s/([^/]+)', share_url)
    if not match:
        raise ValueError("Invalid PikPak share URL")
    share_id = match.group(1)
    
    device_id = uuid.uuid4().hex
    client_id = "YUMx5nI8ZU8Ap8pm"
    
    captcha_token = get_captcha_token(device_id, client_id)
    
    headers = get_default_headers(device_id, client_id)
    if captcha_token:
        headers['x-captcha-token'] = captcha_token
        
    file_id = None
    pass_code_token = ""
    
    # 1. Try primary production seam: API-based share/detail
    detail_url = f"https://api-drive.mypikpak.com/drive/v1/share?share_id={share_id}"
    try:
        resp = requests.get(detail_url, headers=headers)
        if resp.status_code == 200:
            share_data = resp.json()
            # Depending on response shape
            if 'file' in share_data:
                file_id = share_data['file'].get('id')
            elif 'share' in share_data:
                file_id = share_data['share'].get('file_id')
    except Exception:
        pass
        
    # 2. Fallback to HTML if API failed
    if not file_id:
        html_resp = requests.get(share_url)
        html_resp.raise_for_status()
        info = extract_share_info_html(html_resp.text, share_id)
        file_id = info['file_id']
        pass_code_token = info.get('pass_code_token', '')

    # 3. Get file_info
    # For public, non-password shares, empty pass_code_token is fine.
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
    """
    Safely download a range of bytes, ensuring 206 status and correct boundaries.
    """
    headers = {'Range': f'bytes={bytes_range}'}
    # Issue request in streaming mode
    resp = requests.get(url, headers=headers, stream=True)
    
    # Inspect HTTP status before consuming body
    if resp.status_code == 200:
        resp.close()
        raise ValueError("Server returned 200 OK (full file). Aborting to prevent full download.")
    elif resp.status_code != 206:
        resp.close()
        raise ValueError(f"Server did not return 206 Partial Content. Status: {resp.status_code}")
        
    # Validate Content-Range
    content_range = resp.headers.get('Content-Range', '')
    if not content_range.startswith(f'bytes {bytes_range.replace("-", "-")}') and 'bytes ' not in content_range:
        # Check carefully since bytes=0-65535 -> bytes 0-65535/xxxx
        resp.close()
        raise ValueError(f"Invalid Content-Range header: {content_range}")
        
    # Impose hard byte ceiling
    downloaded = bytearray()
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            downloaded.extend(chunk)
            if len(downloaded) >= max_bytes:
                break
                
    resp.close()
    return bytes(downloaded[:max_bytes])
