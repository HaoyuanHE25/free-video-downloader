import socket
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import downloader
from app import douyin
from app.downloader import collapse_formats
from app.jobs import store
from app.main import app

SAMPLE_FORMATS = [
    {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "mp4a", "filesize": 1_000_000, "tbr": 400},
    {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a", "filesize": 5_000_000, "tbr": 800},
    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none", "filesize": 8_000_000, "tbr": 2000},
    {"format_id": "136", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "none", "filesize": 4_000_000, "tbr": 1200},
    {"format_id": "135", "ext": "mp4", "height": 480, "vcodec": "avc1", "acodec": "none", "filesize": 2_000_000, "tbr": 700},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 500_000, "abr": 128},
    {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "filesize": 400_000, "abr": 160},
    {"format_id": "399", "ext": "mp4", "height": 2160, "vcodec": "avc1", "acodec": "none", "filesize": 20_000_000, "tbr": 8000},
]


def sample_info():
    return {
        "title": "示例短片",
        "thumbnail": "https://example.com/cover.jpg",
        "duration": 65,
        "extractor_key": "YouTube",
        "formats": SAMPLE_FORMATS,
    }


class FakeYDL:
    created = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.created.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    urls = []

    def extract_info(self, url, download=False):
        FakeYDL.urls.append(url)
        if not download:
            return sample_info()
        directory = Path(self.opts["outtmpl"]).parent
        path = directory / "media.mp4"
        path.write_bytes(b"fake-video-bytes")
        for hook in self.opts.get("progress_hooks") or []:
            hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10, "filename": str(path)})
            hook({"status": "finished", "filename": str(path)})
        return {"title": "示例短片", "ext": "mp4"}


def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture
def client(monkeypatch):
    FakeYDL.created = []
    FakeYDL.urls = []
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)
    store.reset()
    with TestClient(app) as test_client:
        yield test_client
    store.reset()


def test_collapse_keeps_one_option_per_tier():
    options = collapse_formats(SAMPLE_FORMATS, ffmpeg=True)
    assert [item["label"] for item in options] == ["1080p", "720p", "480p", "仅音频"]
    assert options[0]["format_id"] == "137+251"
    assert options[0]["needs_merge"] is True
    assert options[0]["filesize"] == 8_400_000
    assert options[1]["format_id"] == "136+251"
    assert options[2]["format_id"] == "135+251"
    assert options[3]["format_id"] == "251"
    assert options[3]["audio_only"] is True
    assert all("2160" not in item["format_id"] for item in options)


def test_direct_file_without_codec_metadata_is_kept():
    options = collapse_formats(
        [{"format_id": "mp4", "ext": "mp4", "vcodec": None, "acodec": None, "protocol": "https"}],
        ffmpeg=False,
    )
    assert options == [
        {
            "format_id": "mp4",
            "label": "原文件",
            "ext": "mp4",
            "filesize": None,
            "height": None,
            "audio_only": False,
            "needs_merge": False,
        }
    ]


def test_collapse_without_ffmpeg_uses_single_files():
    options = collapse_formats(SAMPLE_FORMATS, ffmpeg=False)
    assert [item["label"] for item in options] == ["1080p", "720p", "480p", "仅音频"]
    assert [item["format_id"] for item in options] == ["137+251", "22", "18", "251"]
    assert options[0]["needs_merge"] is True
    assert options[1]["needs_merge"] is False
    assert options[2]["needs_merge"] is False


def test_bilibili_separate_streams_stay_visible_without_ffmpeg():
    options = collapse_formats(
        [
            {"format_id": "30032", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "none", "tbr": 800},
            {"format_id": "30064", "ext": "mp4", "height": 540, "vcodec": "avc1", "acodec": "none", "tbr": 1700},
            {"format_id": "30080", "ext": "mp4", "height": 810, "vcodec": "avc1", "acodec": "none", "tbr": 4000},
            {"format_id": "30280", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 177},
        ],
        ffmpeg=False,
    )
    assert [item["label"] for item in options] == ["720p", "480p", "360p", "仅音频"]
    assert [item["format_id"] for item in options] == ["30080+30280", "30064+30280", "30032+30280", "30280"]


@pytest.mark.parametrize(
    "url",
    [
        "notaurl",
        "ftp://example.com/a",
        "file:///tmp/a.mp4",
        "http://127.0.0.1/a",
        "http://localhost/a",
        "http://10.1.2.3/a",
        "http://192.168.1.5/a",
        "http://169.254.169.254/latest",
        "http://[::1]/a",
        "http://2130706433/a",
        "https://user:pass@example.com/a",
        "   ",
    ],
)
def test_rejects_unsafe_urls(client, url):
    response = client.post("/api/parse", json={"url": url})
    assert response.status_code == 400
    assert response.json()["detail"] in {"链接无效", "不支持本机或内网地址"}
    assert FakeYDL.created == []


def test_allows_public_address_when_dns_also_returns_a_nonpublic_one(client, monkeypatch):
    def mixed(host, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001::1", 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        ]

    monkeypatch.setattr(downloader.socket, "getaddrinfo", mixed)
    response = client.post("/api/parse", json={"url": "https://example.com/watch?v=demo"})
    assert response.status_code == 200
    assert response.json()["title"] == "示例短片"


def test_rejects_hostname_that_resolves_to_private_ip(client, monkeypatch):
    def private_dns(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

    monkeypatch.setattr(downloader.socket, "getaddrinfo", private_dns)
    response = client.post("/api/parse", json={"url": "https://internal.example/watch"})
    assert response.status_code == 400
    assert response.json()["detail"] == "不支持本机或内网地址"
    assert FakeYDL.created == []


def test_parse_returns_few_qualities_without_credentials(client):
    response = client.post("/api/parse", json={"url": "https://example.com/watch?v=demo"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "示例短片"
    assert body["platform"] == "YouTube"
    assert body["thumbnail"] == "https://example.com/cover.jpg"
    assert [item["label"] for item in body["formats"]] == ["1080p", "720p", "480p", "仅音频"]
    opts = FakeYDL.created[-1]
    assert "Referer" not in (opts.get("http_headers") or {})
    assert opts["noplaylist"] is True
    assert "cookiefile" not in opts
    assert "username" not in opts
    assert "password" not in opts


def test_download_job_returns_file_once(client):
    parsed = client.post("/api/parse", json={"url": "https://example.com/watch?v=demo"})
    format_id = parsed.json()["formats"][0]["format_id"]
    created = client.post(
        "/api/download",
        json={"url": "https://example.com/watch?v=demo", "format_id": format_id},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    snapshot = {}
    for _ in range(50):
        snapshot = client.get(f"/api/jobs/{job_id}").json()
        if snapshot["status"] in {"finished", "error"}:
            break
        time.sleep(0.02)
    assert snapshot["status"] == "finished"
    assert snapshot["filename"] == "示例短片.mp4"
    assert snapshot["progress"] == 1
    download_opts = FakeYDL.created[-1]
    assert download_opts["noplaylist"] is True
    assert "cookiefile" not in download_opts

    downloaded = client.get(f"/api/jobs/{job_id}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"fake-video-bytes"
    assert "attachment" in downloaded.headers["content-disposition"].lower()
    downloaded.close()

    missing = client.get(f"/api/jobs/{job_id}/file")
    assert missing.status_code == 404


def test_hdslb_thumbnail_is_served_from_our_origin():
    presented = downloader.present_info(
        {
            "title": "封面",
            "thumbnail": "https://i0.hdslb.com/bfs/archive/abc.jpg",
            "extractor_key": "BiliBili",
            "formats": [
                {
                    "format_id": "80",
                    "ext": "mp4",
                    "height": 720,
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                    "filesize": 1000,
                    "tbr": 800,
                }
            ],
        },
        ffmpeg=False,
    )
    assert presented["thumbnail"] == "/api/cover?url=https%3A%2F%2Fi0.hdslb.com%2Fbfs%2Farchive%2Fabc.jpg"
    http_cover = downloader.present_info(
        {
            "title": "封面",
            "thumbnail": "http://i0.hdslb.com/bfs/archive/abc.jpg",
            "extractor_key": "BiliBili",
            "formats": [
                {
                    "format_id": "80",
                    "ext": "mp4",
                    "height": 720,
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                    "filesize": 1000,
                    "tbr": 800,
                }
            ],
        },
        ffmpeg=False,
    )
    assert http_cover["thumbnail"] == presented["thumbnail"]


def test_cover_rejects_unrelated_hosts(client):
    response = client.get("/api/cover", params={"url": "https://example.com/a.jpg"})
    assert response.status_code == 400
    assert response.json()["detail"] == "这个封面不能转发"


def test_cover_fetches_hdslb_with_bilibili_referer(client, monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        content = b"\xff\xd8\xff\xd9"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            FakeClient.seen = (url, headers)
            return FakeResponse()

    monkeypatch.setattr(downloader.httpx, "Client", FakeClient)
    response = client.get("/api/cover", params={"url": "https://i0.hdslb.com/bfs/archive/abc.jpg"})
    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xd9"
    seen_url, seen_headers = FakeClient.seen
    assert seen_url == "https://i0.hdslb.com/bfs/archive/abc.jpg"
    assert seen_headers["Referer"] == "https://www.bilibili.com/"
    assert seen_headers["Origin"] == "https://www.bilibili.com"


def test_youtube_hls_uses_sized_stream_in_the_same_tier():
    formats = [
        {
            "format_id": "96",
            "ext": "mp4",
            "protocol": "m3u8_native",
            "height": 1080,
            "vcodec": "avc1",
            "acodec": "mp4a",
            "tbr": 4689,
            "manifest_url": "https://example.test/hls.m3u8",
        },
        {
            "format_id": "137",
            "ext": "mp4",
            "protocol": "https",
            "height": 1080,
            "vcodec": "avc1",
            "acodec": "none",
            "filesize": 164_000_000,
            "tbr": 1820,
        },
        {
            "format_id": "140",
            "ext": "m4a",
            "vcodec": "none",
            "acodec": "mp4a",
            "filesize": 11_000_000,
            "abr": 128,
        },
    ]
    options = collapse_formats(formats, ffmpeg=True, duration=723)
    video = options[0]
    assert video["format_id"] == "137+140"
    assert video["filesize"] == 175_000_000


def test_manifest_only_size_is_estimated_from_bitrate():
    options = collapse_formats(
        [
            {
                "format_id": "96",
                "ext": "mp4",
                "protocol": "m3u8_native",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "tbr": 800,
            }
        ],
        ffmpeg=True,
        duration=10,
    )
    assert options[0]["filesize"] == 1_000_000


def test_youtube_parse_uses_embedded_player(client):
    response = client.post("/api/parse", json={"url": "https://www.youtube.com/watch?v=anOPqj-49MI"})
    assert response.status_code == 200
    clients = FakeYDL.created[-1]["extractor_args"]["youtube"]["player_client"]
    assert clients[0] == "web_embedded"
    assert "mweb" in clients and "android" in clients


def test_bilibili_link_without_scheme_is_parsed(client):
    raw = (
        "bilibili.com/video/BV1pix16iECa/?trackid=web_pegasus_0.router-web-pegasus-2479516-sm4rx.1793782227417.100"
        "&spm_id_from=333.1007.tianma.3-3-9.click"
    )
    response = client.post("/api/parse", json={"url": raw})
    assert response.status_code == 200
    assert FakeYDL.urls[-1] == "https://" + raw
    assert FakeYDL.created[-1]["http_headers"]["Referer"] == "https://www.bilibili.com/"


def test_merge_download_without_ffmpeg_is_refused(client, monkeypatch):
    monkeypatch.setattr(downloader, "ffmpeg_available", lambda: False)
    response = client.post(
        "/api/download",
        json={"url": "https://www.bilibili.com/video/BV1pix16iECa/", "format_id": "30080+30280"},
    )
    assert response.status_code == 400
    assert "ffmpeg" in response.json()["detail"]


def test_bilibili_parse_and_download_send_referer(client):
    parsed = client.post("/api/parse", json={"url": "https://www.bilibili.com/video/BV1test"})
    assert parsed.status_code == 200
    assert FakeYDL.created[-1]["http_headers"]["Referer"] == "https://www.bilibili.com/"
    created = client.post(
        "/api/download",
        json={"url": "https://b23.tv/abc", "format_id": "18"},
    )
    assert created.status_code == 200
    download_opts = {}
    for _ in range(50):
        download_opts = next((item for item in FakeYDL.created if item.get("format") == "18"), {})
        if download_opts:
            break
        time.sleep(0.02)
    assert download_opts["http_headers"]["Referer"] == "https://www.bilibili.com/"
    assert download_opts["http_headers"]["Origin"] == "https://www.bilibili.com"


def test_rejects_format_id_that_is_not_a_quality_token(client):
    response = client.post(
        "/api/download",
        json={"url": "https://example.com/watch?v=demo", "format_id": "../secret"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "清晰度选项无效"


DOUYIN_AWEME = {
    "desc": "我家的包子，吃了不烧心",
    "video": {
        "duration": 262619,
        "cover": {"url_list": ["https://p3-pc-sign.douyinpic.com/cover.jpg"]},
        "bit_rate": [
            {
                "format": "mp4",
                "is_h265": 1,
                "bit_rate": 1486391,
                "play_addr": {
                    "height": 2160,
                    "width": 3840,
                    "data_size": 48794343,
                    "url_key": "v0_bytevc1_4k_1486391",
                    "url_list": ["https://v26-web.douyinvod.com/4k.mp4"],
                },
            },
            {
                "format": "dash",
                "bit_rate": 2000000,
                "play_addr": {
                    "height": 1080,
                    "width": 1920,
                    "data_size": 999,
                    "url_key": "v0_h264_1080p_dash",
                    "url_list": ["https://v26-web.douyinvod.com/dash.mp4"],
                },
            },
            {
                "format": "mp4",
                "bit_rate": 1396204,
                "play_addr": {
                    "height": 1080,
                    "width": 1920,
                    "data_size": 45833737,
                    "url_key": "v0_h264_1080p_1396204",
                    "url_list": ["https://v26-web.douyinvod.com/1080.mp4"],
                },
            },
            {
                "format": "mp4",
                "is_h265": 1,
                "bit_rate": 926672,
                "play_addr": {
                    "height": 1080,
                    "width": 1920,
                    "data_size": 30420220,
                    "url_key": "v0_bytevc1_1080p_926672",
                    "url_list": ["https://v26-web.douyinvod.com/1080h.mp4"],
                },
            },
            {
                "format": "mp4",
                "bit_rate": 1090439,
                "play_addr": {
                    "height": 720,
                    "width": 1280,
                    "data_size": 35796270,
                    "url_key": "v0_h264_720p_1090439",
                    "url_list": [
                        "https://evil.example/no.mp4",
                        "https://v26-web.douyinvod.com/720.mp4",
                    ],
                },
            },
        ],
    },
}


def test_douyin_jingxuan_parse_needs_no_user_cookie(client, monkeypatch):
    monkeypatch.setattr(douyin, "_aweme", lambda video_id: DOUYIN_AWEME)
    response = client.post(
        "/api/parse",
        json={"url": "https://www.douyin.com/jingxuan?modal_id=7695490636421680394"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "抖音"
    assert body["title"].startswith("我家的包子")
    assert body["duration"] == 263
    assert body["thumbnail"].startswith("https://p3-pc-sign.douyinpic.com/")
    assert [item["label"] for item in body["formats"]] == ["1080p", "720p"]
    assert body["formats"][0]["format_id"] == "v0_h264_1080p_1396204"
    assert body["formats"][0]["filesize"] == 45833737
    assert body["formats"][0]["needs_merge"] is False
    assert all("urls" not in item for item in body["formats"])
    assert FakeYDL.urls == []


def test_douyin_note_without_video_is_rejected(client, monkeypatch):
    monkeypatch.setattr(douyin, "_aweme", lambda video_id: {"desc": "图文", "video": {}})
    response = client.post("/api/parse", json={"url": "https://www.douyin.com/note/7695490636421680394"})
    assert response.status_code == 422
    assert "图文" in response.json()["detail"]


def test_douyin_download_uses_referer_and_not_a_user_cookie(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "_aweme", lambda video_id: DOUYIN_AWEME)
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)
    seen = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "video/mp4", "content-length": "2048"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self, size):
            yield b"f" * 2048

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, headers=None):
            seen["url"] = url
            seen["headers"] = dict(headers or {})
            return FakeResponse()

    monkeypatch.setattr(douyin.httpx, "Client", FakeClient)
    path, name = douyin.download(
        "https://www.douyin.com/video/7695490636421680394",
        "v0_h264_720p_1090439",
        tmp_path,
        lambda progress: None,
    )
    assert seen["url"] == "https://v26-web.douyinvod.com/720.mp4"
    assert seen["headers"]["Referer"] == "https://www.douyin.com/"
    assert "Cookie" not in seen["headers"]
    assert path.read_bytes() == b"f" * 2048
    assert name.endswith(".mp4")
