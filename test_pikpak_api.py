import pytest
from pikpak_api import extract_share_info, probe_480p

def test_extract_share_info():
    with open('share.html', 'r', encoding='utf-8') as f:
        html = f.read()
    share_id = 'VOzuCvKmZUsWl46t2khdDdcDo2'
    info = extract_share_info(html, share_id)
    assert info['pass_code_token'] is not None
    assert info['pass_code_token'].startswith('u8')
    assert info['file_id'] == 'VOzuAuSrUkan_TaiMNnhSZmro2'

def test_probe_480p():
    with open('share.html', 'r', encoding='utf-8') as f:
        html = f.read()
    share_id = 'VOzuCvKmZUsWl46t2khdDdcDo2'
    content = probe_480p(share_id, html_content=html)
    assert len(content) == 65536
