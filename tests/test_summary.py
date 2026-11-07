import socket
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import downloader
from app.downloader import UserFacingError
from app.main import app
from app.subtitles import (
    NO_SUBTITLE,
    _SUBTITLE_MASKS,
    limit_cues,
    parse_subtitle_text,
    pick_subtitle,
    unmask_bilibili_subtitle,
)
from app.summary import build_result
from app.summary_jobs import store


def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    store.reset()
    with TestClient(app) as test_client:
        yield test_client
    store.reset()


def test_masked_bilibili_subtitle_url_becomes_a_public_file():
    prefix, mask = _SUBTITLE_MASKS[0]
    key = f"{mask}bilibili"
    hidden = "".join(
        chr(ord(char) ^ ord(key[index % len(key)]))
        for index, char in enumerate(prefix + "/bfs/ai_subtitle/prod/example.json")
    )
    masked = "//subtitle.bilibili.com/" + quote(hidden, safe="") + "?auth_key=1"
    assert (
        unmask_bilibili_subtitle(masked)
        == "https://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/example.json?auth_key=1"
    )


def test_bilibili_track_prefers_zh_cn_and_parses_body():
    chosen = pick_subtitle(
        [
            {"lan": "en", "subtitle_url": "https://example.com/en.json"},
            {"lan": "ai-zh", "subtitle_url": "https://example.com/ai.json"},
            {"lan": "zh-CN", "subtitle_url": "https://example.com/zh.json"},
        ]
    )
    assert chosen["lan"] == "zh-CN"
    cues = parse_subtitle_text('{"body":[{"from":1.5,"to":3.2,"content":"你好"}]}')
    assert cues == [{"start": 1.5, "end": 3.2, "text": "你好"}]


def test_missing_subtitles_do_not_call_the_model(client, monkeypatch):
    called = []

    def no_subtitle(url, directory):
        raise UserFacingError(NO_SUBTITLE, 422)

    monkeypatch.setattr("app.summary_routes.load_subtitles", no_subtitle)
    monkeypatch.setattr("app.summary_jobs.summarize", lambda *args: called.append(args))
    response = client.post("/api/summary", json={"url": "https://www.bilibili.com/video/BV1pix16iECa"})
    assert response.status_code == 422
    assert response.json()["detail"] == NO_SUBTITLE
    assert called == []


def test_missing_key_is_refused(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    response = client.post("/api/summary", json={"url": "https://example.com/watch"})
    assert response.status_code == 503
    assert response.json()["detail"] == "还没有配置总结服务"


def test_chapter_time_that_misses_a_cue_is_dropped():
    cues = [{"start": 12.0, "end": 18.0, "text": "从这里开始"}]
    result = build_result(
        '{"outline":"大纲","points":["要点"],"chapters":['
        '{"title":"对得上","start":12,"summary":"这一段"},'
        '{"title":"对不上","start":99,"summary":"没有这句"}'
        "]}",
        cues,
        False,
    )
    assert result["chapters"] == [{"title": "对得上", "start": 12.0, "summary": "这一段"}]


def test_model_text_that_is_not_json_is_refused():
    with pytest.raises(UserFacingError) as caught:
        build_result("不是 JSON", [{"start": 0, "end": 1, "text": "甲"}], False)
    assert caught.value.message == "总结没有生成，请重试"


def test_long_transcript_is_truncated():
    cues = [{"start": index, "end": index + 1, "text": "字" * 1000} for index in range(80)]
    kept, truncated = limit_cues(cues)
    assert truncated is True
    assert sum(len(item["text"]) for item in kept) == 60_000


def test_summary_job_returns_outline_without_touching_download(client, monkeypatch):
    monkeypatch.setattr(
        "app.summary_routes.load_subtitles",
        lambda url, directory: {"cues": [{"start": 0.0, "end": 1.0, "text": "甲"}], "truncated": False},
    )

    def fake_summarize(cues, truncated):
        return build_result(
            '{"outline":"大纲","points":["要点"],"chapters":[{"title":"开场","start":0,"summary":"第一句"}]}',
            cues,
            truncated,
        )

    monkeypatch.setattr("app.summary_jobs.summarize", fake_summarize)
    created = client.post("/api/summary", json={"url": "https://example.com/watch"})
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    body = {}
    for _ in range(50):
        body = client.get(f"/api/summary/{job_id}").json()
        if body["status"] in {"finished", "error"}:
            break
        time.sleep(0.02)
    assert body["status"] == "finished"
    assert body["result"]["outline"] == "大纲"
    assert body["result"]["transcript"][0]["text"] == "甲"
