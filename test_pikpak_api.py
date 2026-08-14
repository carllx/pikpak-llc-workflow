import pytest
from pikpak_api import (
    ShareMediaClient,
    download_range,
    get_media_variants,
    select_share_video,
)


class ApiResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def install_share_api(monkeypatch, share_data, variants_by_id):
    requested_file_ids = []
    monkeypatch.setattr("pikpak_api.get_captcha_token", lambda *args: "captcha")

    def fake_get(url, **kwargs):
        if "file_info" not in url:
            return ApiResponse(share_data)
        file_id = url.split("file_id=", 1)[1].split("&", 1)[0]
        requested_file_ids.append(file_id)
        return ApiResponse({"medias": variants_by_id[file_id]})

    monkeypatch.setattr("pikpak_api.requests.get", fake_get)
    return requested_file_ids

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


def test_folder_lists_two_videos_and_uses_each_stable_file_id(monkeypatch):
    share = {
        "files": [
            {"id": "video-a", "name": "a.mp4", "mime_type": "video/mp4"},
            {"id": "video-b", "name": "b.mkv", "mime_type": "video/x-matroska"},
        ]
    }
    requested = install_share_api(
        monkeypatch,
        share,
        {
            "video-a": [{"resolution_name": "480P", "link": {"url": "proxy-a"}}],
            "video-b": [{"resolution_name": "480P", "link": {"url": "proxy-b"}}],
        },
    )

    client = ShareMediaClient.open("https://mypikpak.com/s/folder")

    assert [item["file_id"] for item in client.files] == ["video-a", "video-b"]
    assert client.proxy_for_file("video-a") == "proxy-a"
    assert client.proxy_for_file("video-b") == "proxy-b"
    assert requested == ["video-a", "video-b"]


def test_folder_candidate_types_exclude_non_video(monkeypatch):
    install_share_api(
        monkeypatch,
        {
            "files": [
                {"id": "video", "name": "movie.mp4", "mime_type": "video/mp4"},
                {"id": "text", "name": "notes.txt", "mime_type": "text/plain"},
            ]
        },
        {},
    )

    files = ShareMediaClient.open("https://mypikpak.com/s/mixed").files

    assert [(item["file_id"], item["candidate_type"]) for item in files] == [
        ("video", "video"),
        ("text", "non_video"),
    ]


def test_folder_does_not_silently_use_files_zero_for_single_file_helper(monkeypatch):
    install_share_api(
        monkeypatch,
        {
            "files": [
                {"id": "first", "name": "first.mp4"},
                {"id": "second", "name": "second.mp4"},
            ]
        },
        {},
    )

    with pytest.raises(ValueError, match="exactly one Share file"):
        get_media_variants("https://mypikpak.com/s/folder")


def test_origin_is_loaded_for_selected_file_id(monkeypatch):
    requested = install_share_api(
        monkeypatch,
        {"files": [{"id": "selected", "name": "movie.mp4"}]},
        {
            "selected": [
                {"is_origin": True, "link": {"url": "origin-selected"}}
            ]
        },
    )

    client = ShareMediaClient.open("https://mypikpak.com/s/folder")

    assert client.origin_for_file("selected") == "origin-selected"
    assert requested == ["selected"]


def test_llc_filename_selects_unique_share_video_by_proxy_stem():
    files = [
        {"file_id": "a", "filename": "alpha.mp4", "candidate_type": "video"},
        {"file_id": "b", "filename": "beta.mkv", "candidate_type": "video"},
    ]

    assert select_share_video(files, "beta_h264.mp4")["file_id"] == "b"


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (
            [
                {"file_id": "a", "filename": "same.mp4", "candidate_type": "video"},
                {"file_id": "b", "filename": "same.mkv", "candidate_type": "video"},
            ],
            "multiple",
        ),
        (
            [{"file_id": "a", "filename": "other.mp4", "candidate_type": "video"}],
            "does not match",
        ),
    ],
)
def test_llc_filename_ambiguous_or_missing_match_fails(files, message):
    with pytest.raises(ValueError, match=message):
        select_share_video(files, "same_h264.mov")
