import pytest
from pikpak_api import get_media_variants, download_range

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

def test_get_proxy_url_includes_filename_without_changing_media_api(monkeypatch):
    monkeypatch.setattr(
        "pikpak_api._get_media_variants_with_filename",
        lambda url: (
            [{"resolution_name": "480P", "link": {"url": "http://test/480p"}}],
            "source.mkv",
        ),
    )

    from pikpak_api import get_proxy_url

    assert get_proxy_url("https://mypikpak.com/s/share123") == (
        "http://test/480p",
        "source.mkv",
    )

def test_download_proxy_video_passes_only_url_to_requests(monkeypatch, tmp_path):
    class MockResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield b"proxy"

    requested = []
    monkeypatch.setattr(
        "pikpak_api.get_proxy_url",
        lambda url: ("http://test/480p", "source.mkv"),
    )
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kwargs: requested.append(url) or MockResponse(),
    )

    from pikpak_api import download_proxy_video

    output = tmp_path / "proxy.bin"
    download_proxy_video("https://mypikpak.com/s/share123", output)

    assert requested == ["http://test/480p"]
    assert output.read_bytes() == b"proxy"

def test_get_origin_url_success(monkeypatch):
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
                    {'resolution_name': 'Original', 'is_origin': True, 'link': {'url': 'http://test/origin'}}
                ]
            })
        return MockResponse({})

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.get", mock_get)

    from pikpak_api import get_origin_url
    url = get_origin_url("https://mypikpak.com/s/share123")
    assert url == 'http://test/origin'

def test_get_origin_url_category_fallback(monkeypatch):
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
                    {'category': 'category_origin', 'link': {'url': 'http://test/origin_fallback'}}
                ]
            })
        return MockResponse({})

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.get", mock_get)

    from pikpak_api import get_origin_url
    url = get_origin_url("https://mypikpak.com/s/share123")
    assert url == 'http://test/origin_fallback'

def test_get_origin_url_not_found(monkeypatch):
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
                    {'resolution_name': '480P', 'link': {'url': 'http://test/480p'}}
                ]
            })
        return MockResponse({})

    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.get", mock_get)

    from pikpak_api import get_origin_url
    with pytest.raises(ValueError, match="Origin media not found"):
        get_origin_url("https://mypikpak.com/s/share123")

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
    data = download_range("http://test/url", "0-65535", 65536)
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
        download_range("http://test/url", "0-65535")

def test_download_range_wrong_start_end(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 206
            self.headers = {'Content-Range': 'bytes 0-100000/1048576'}
        def iter_content(self, chunk_size):
            raise RuntimeError("Body consumed for wrong range! Safety guard failed.")
        def close(self):
            pass

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    
    with pytest.raises(ValueError, match="Content-Range mismatch"):
        download_range("http://test/url", "0-65535")

def test_download_range_missing_header(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 206
            self.headers = {}
        def iter_content(self, chunk_size):
            raise RuntimeError("Body consumed for missing header! Safety guard failed.")
        def close(self):
            pass

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    
    with pytest.raises(ValueError, match="Missing Content-Range header"):
        download_range("http://test/url", "0-65535")

def test_download_range_malformed_header(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 206
            self.headers = {'Content-Range': 'bytes 0-65535'}
        def iter_content(self, chunk_size):
            raise RuntimeError("Body consumed for malformed header! Safety guard failed.")
        def close(self):
            pass

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    
    with pytest.raises(ValueError, match="Malformed Content-Range header"):
        download_range("http://test/url", "0-65535")

def test_download_range_short_body(monkeypatch):
    class MockResponse:
        def __init__(self):
            self.status_code = 206
            self.headers = {'Content-Range': 'bytes 0-65535/1048576'}
        def iter_content(self, chunk_size):
            yield b"a" * 10000  # Only yields 10,000 bytes instead of 65,536
        def close(self):
            pass

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)
    
    with pytest.raises(ValueError, match="Incomplete download"):
        download_range("http://test/url", "0-65535", 65536)
