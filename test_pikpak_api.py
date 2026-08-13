import pytest
from pikpak_api import extract_share_info_html, get_media_variants, download_range

def test_extract_share_info_html():
    html_content = '''<html>
    <script id="__NUXT_DATA__" type="application/json">
    ["u812345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678912", "VOzuAuSrUkan_TaiMNnhSZmro2", "VOzuCvKmZUsWl46t2khdDdcDo2"]
    </script>
    </html>'''
    info = extract_share_info_html(html_content, "VOzuCvKmZUsWl46t2khdDdcDo2")
    assert info['pass_code_token'].startswith('u8')
    assert info['file_id'] == 'VOzuAuSrUkan_TaiMNnhSZmro2'

def test_get_media_variants(monkeypatch):
    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self.json_data = json_data
            self.status_code = status_code
        def json(self):
            return self.json_data
        def raise_for_status(self):
            pass

    def mock_post(*args, **kwargs):
        return MockResponse({'captcha_token': 'test_token'})
        
    def mock_get(url, *args, **kwargs):
        if 'drive/v1/share?' in url:
            return MockResponse({'share': {'file_id': 'file123'}})
        if 'file_info' in url:
            return MockResponse({
                'medias': [
                    {'resolution_name': '480P', 'link': {'url': 'http://test/480p'}},
                    {'resolution_name': '1080P', 'link': {'url': 'http://test/1080p'}}
                ]
            })
        return MockResponse({})

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.get", mock_get)

    medias = get_media_variants("https://mypikpak.com/s/share123")
    assert len(medias) == 2
    assert medias[0]['resolution_name'] == '480P'

def test_download_range_success(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 206
            self.headers = {'Content-Range': 'bytes 0-65535/1048576'}
        def iter_content(self, chunk_size):
            yield b"a" * 65536
        def close(self):
            pass

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    data = download_range("http://test/url")
    assert len(data) == 65536
    assert data == b"a" * 65536

def test_download_range_safety_guard_200_ok(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
            self.closed = False
        def iter_content(self, chunk_size):
            raise RuntimeError("Body consumed for 200 OK! Safety guard failed.")
        def close(self):
            self.closed = True

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    
    with pytest.raises(ValueError, match="Server returned 200 OK"):
        download_range("http://test/url")
