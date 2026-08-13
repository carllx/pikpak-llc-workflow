import re
import json
import urllib.parse
import requests

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

def extract_share_info(html_content, share_id):
    """
    Parses PikPak share page HTML to extract pass_code_token and file_id.
    """
    match = re.search(r'id="__NUXT_DATA__"[^>]*>([^<]+)</script>', html_content)
    if not match:
        raise ValueError("Could not find __NUXT_DATA__ in HTML")
    
    data = json.loads(match.group(1))
    
    pass_code_token = None
    file_ids = []
    
    for item in data:
        if isinstance(item, str):
            if item.startswith('u8') and len(item) > 100:
                pass_code_token = item
            # file_ids and share_ids in PikPak often start with V and are 26-28 chars long
            if item.startswith('V') and len(item) >= 20 and len(item) <= 30 and item != share_id:
                if "_" in item or item.isalnum():
                    file_ids.append(item)
                
    if not pass_code_token:
        raise ValueError("Could not extract pass_code_token")
    if not file_ids:
        raise ValueError("Could not extract file_id")
        
    return {
        "pass_code_token": pass_code_token,
        "file_id": file_ids[0]
    }

def get_captcha_token(device_id, client_id):
    url = 'https://user.mypikpak.com/v1/shield/captcha/init'
    headers = get_default_headers(device_id, client_id)
    # Spoofed metadata for stateless access
    data = {
        'action': 'GET:/drive/v1/share/file_info',
        'client_id': client_id,
        'device_id': device_id,
        'meta': {
            'captcha_sign': '1.89c77126398049a1110199474d60d745',
            'client_version': 'undefined',
            'package_name': 'drive.mypikpak.com',
            'user_id': '',
            'timestamp': '1786609722769'
        }
    }
    resp = requests.post(url, json=data, headers=headers)
    resp.raise_for_status()
    return resp.json().get('captcha_token')

def get_file_info(share_id, file_id, pass_code_token, device_id, client_id, captcha_token):
    url = f"https://api-drive.mypikpak.com/drive/v1/share/file_info?share_id={share_id}&file_id={file_id}&pass_code_token={urllib.parse.quote(pass_code_token)}"
    headers = get_default_headers(device_id, client_id)
    headers['x-captcha-token'] = captcha_token
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def probe_480p(share_id, html_content=None):
    if html_content is None:
        resp = requests.get(f"https://mypikpak.com/s/{share_id}")
        resp.raise_for_status()
        html_content = resp.text

    info = extract_share_info(html_content, share_id)
    device_id = "111f07c42c8b4e4080773f96b02df1e9"
    client_id = "YUMx5nI8ZU8Ap8pm"
    
    captcha_token = get_captcha_token(device_id, client_id)
    file_info = get_file_info(share_id, info['file_id'], info['pass_code_token'], device_id, client_id, captcha_token)
    
    # Check where medias is located
    medias = []
    if 'medias' in file_info:
        medias = file_info['medias']
    elif 'file_info' in file_info and 'medias' in file_info['file_info']:
        medias = file_info['file_info']['medias']
    elif 'file' in file_info and 'medias' in file_info['file']:
        medias = file_info['file']['medias']
        
    url_480p = None
    for m in medias:
        if m.get('resolution_name') == '480P':
            url_480p = m.get('link', {}).get('url')
            break
            
    if not url_480p:
        raise ValueError(f"480P media not found. Found keys: {list(file_info.keys())}")
        
    # Perform 64KB range request
    headers = {'Range': 'bytes=0-65535'}
    range_resp = requests.get(url_480p, headers=headers)
    
    if range_resp.status_code != 206:
        raise ValueError(f"Server does not support partial content. Status: {range_resp.status_code}")
        
    return range_resp.content
