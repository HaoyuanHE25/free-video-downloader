import json
import socket

import pytest
from fastapi.testclient import TestClient

from app import downloader
from app.downloader import UserFacingError
from app.main import app
from app.mindmap import build_mindmap, build_tree_from_text, count_nodes, to_mermaid
from app.sse import encode
from app.subtitles import NO_SUBTITLE, parse_subtitle_text
from app.subtitles_proc import (
    build_document,
    build_segments,
    detect_format,
    normalize_cues,
    read_subtitles,
    split_sentences,
    to_srt,
    to_vtt,
)
from app.summary import StreamFields, build_qa_context, build_result

OUTLINE = "这条视频演示了公开视频的保存流程。"
POINTS = ["先粘贴公开链接", "再选择清晰度"]
CHAPTERS = [{"title": "开场", "start": 0, "summary": "先介绍整体流程"}]
MODEL_JSON = json.dumps(
    {"outline": OUTLINE, "points": POINTS, "chapters": CHAPTERS},
    ensure_ascii=False,
)
CUES = [
    {"start": 0.0, "end": 2.0, "text": "这条视频演示了公开视频的保存流程。"},
    {"start": 2.5, "end": 6.0, "text": "先粘贴公开链接，再选择清晰度。"},
]


def _public_dns(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(downloader.socket, "getaddrinfo", _public_dns)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    with TestClient(app) as test_client:
        yield test_client


def fake_stream(messages, json_mode=False):
    for index in range(0, len(MODEL_JSON), 12):
        yield MODEL_JSON[index : index + 12]


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name = None
        data = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


def test_sse_encode_keeps_payload_on_one_line():
    line = encode("delta", {"text": "你好\n世界"})
    assert line.startswith("event: delta\n")
    assert line.endswith("\n\n")
    assert line.count("\n") == 3
    payload = line.split("data: ", 1)[1].strip()
    assert json.loads(payload)["text"] == "你好\n世界"


def test_stream_fields_emit_outline_and_closed_points_incrementally():
    parser = StreamFields()
    events = []
    for piece in ['{"outline":"你', "好，世界", '"}', ',"points":["甲",', ' "乙","丙"]}']:
        events.extend(parser.feed(piece))
    outline = "".join(data["text"] for name, data in events if name == "delta")
    assert outline == "你好，世界"
    assert [data["text"] for name, data in events if name == "point"] == ["甲", "乙", "丙"]


def test_stream_fields_decode_json_escapes():
    parser = StreamFields()
    events = parser.feed('{"outline":"第一行\\n第二行 \\"引号\\"')
    assert "".join(data["text"] for _, data in events) == '第一行\n第二行 "引号"'


def test_all_supported_subtitle_formats_are_recognised():
    srt = "1\n00:00:01,000 --> 00:00:03,500\n你好\n\n2\n00:00:04,000 --> 00:00:06,000\n世界\n"
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\n你好\n"
    json3 = json.dumps(
        {"events": [{"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "你好"}]}]}
    )
    bilibili = json.dumps({"body": [{"from": 1.0, "to": 3.0, "content": "你好"}]})
    assert detect_format(srt) == "srt"
    assert detect_format(vtt) == "vtt"
    assert detect_format(json3) == "json3"
    assert detect_format(bilibili) == "bilibili"
    assert read_subtitles(srt)["chars"] == 4
    assert read_subtitles(vtt)["cues"][0]["text"] == "你好"
    assert read_subtitles(json3)["cues"][0]["start"] == 1.0


def test_document_merges_cues_into_semantic_segments():
    document = build_document(CUES)
    assert document["stats"]["cues"] == 2
    assert document["stats"]["segments"] == 1
    assert document["segments"][0]["text"] == "这条视频演示了公开视频的保存流程。先粘贴公开链接，再选择清晰度。"
    assert document["segments"][0]["sentences"] == [
        "这条视频演示了公开视频的保存流程。",
        "先粘贴公开链接，再选择清晰度。",
    ]


def test_segments_split_on_long_gaps():
    segments = build_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "甲"},
            {"start": 10.0, "end": 11.0, "text": "乙"},
        ]
    )
    assert [item["text"] for item in segments] == ["甲", "乙"]


def test_repeated_caption_lines_are_merged():
    cues = normalize_cues(
        [
            {"start": 0.0, "end": 1.0, "text": "同一句"},
            {"start": 1.0, "end": 2.0, "text": "同一句"},
            {"start": 2.0, "end": 3.0, "text": "<b>另一句</b>"},
        ]
    )
    assert cues == [
        {"start": 0.0, "end": 2.0, "text": "同一句"},
        {"start": 2.0, "end": 3.0, "text": "另一句"},
    ]


def test_sentence_split_keeps_chinese_punctuation():
    assert split_sentences("第一句。第二句！第三句没有标点") == ["第一句。", "第二句！", "第三句没有标点"]


def test_subtitle_export_round_trips():
    cues = [{"start": 1.0, "end": 2.5, "text": "你好"}]
    assert parse_subtitle_text(to_srt(cues)) == cues
    assert parse_subtitle_text(to_vtt(cues)) == cues


def test_mindmap_has_summary_points_and_chapters():
    result = build_result(
        json.dumps({"outline": OUTLINE, "points": POINTS, "chapters": CHAPTERS}, ensure_ascii=False),
        CUES,
        False,
    )
    tree = build_mindmap(result)
    assert tree["id"] == "root"
    assert [child["id"] for child in tree["children"]] == ["summary", "points", "chapters"]
    assert count_nodes(tree) >= 7


def test_chapter_start_is_snapped_to_nearby_cue():
    result = build_result(
        json.dumps(
            {"outline": OUTLINE, "points": POINTS, "chapters": [{"title": "开场", "start": 2.4, "summary": "讲流程"}]},
            ensure_ascii=False,
        ),
        CUES,
        False,
    )
    assert result["chapters"][0]["start"] == 2.5


def test_qa_context_includes_sections_and_clips():
    context = build_qa_context(
        {
            "outline": "大纲",
            "points": ["甲", "乙"],
            "chapters": [{"title": "开场", "start": 12, "summary": "开场内容"}],
            "transcript": [{"start": 12, "text": "第一句"}],
        }
    )
    assert "【摘要】" in context and "【要点】" in context and "【章节】" in context and "【字幕】" in context
    clipped = build_qa_context({"outline": "字" * 500}, limit=40)
    assert clipped.endswith("（资料较长，已截断）")
    assert len(clipped) <= 60


def test_stream_summary_emits_incremental_sse(client, monkeypatch):
    monkeypatch.setattr(
        "app.summary_stream.load_subtitles",
        lambda url, directory: {"cues": CUES, "truncated": False},
    )
    monkeypatch.setattr("app.summary._iter_completion", fake_stream)
    response = client.post("/api/summary/stream", json={"url": "https://example.com/watch"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "stats" in names
    assert "segment" in names
    assert "delta" in names
    assert "mindmap" in names
    assert names[-1] == "done"
    assert "digest_result" not in names
    done = events[-1][1]
    assert done["result"]["outline"] == OUTLINE
    assert done["result"]["mindmap"]["id"] == "root"
    assert done["result"]["segments"][0]["index"] == 0


def test_stream_summary_error_frame_terminates(client, monkeypatch):
    def no_subtitles(url, directory):
        raise UserFacingError(NO_SUBTITLE, 422)

    monkeypatch.setattr("app.summary_stream.load_subtitles", no_subtitles)
    response = client.post("/api/summary/stream", json={"url": "https://example.com/watch"})
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[-1] == "error"
    assert "done" not in names
    assert events[-1][1] == {"message": NO_SUBTITLE, "code": 422}


def test_stream_summary_refuses_invalid_url(client):
    response = client.post("/api/summary/stream", json={"url": "http://127.0.0.1/a"})
    assert response.status_code == 400
    assert response.json()["detail"] == "不支持本机或内网地址"


def test_stream_summary_needs_model_key(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    response = client.post("/api/summary/stream", json={"url": "https://example.com/watch"})
    assert response.status_code == 503
    assert response.json()["detail"] == "还没有配置总结服务"


def test_ask_stream_uses_context_and_history(client, monkeypatch):
    seen = []
    pieces = ["视频", "主要", "讲了", "保存", "方法。"]

    def fake(messages, json_mode=False):
        seen.append(messages)
        return iter(pieces)

    monkeypatch.setattr("app.summary._iter_completion", fake)
    response = client.post(
        "/api/summary/ask/stream",
        json={
            "question": "讲了什么",
            "history": [
                {"role": "user", "content": "先问一句"},
                {"role": "assistant", "content": "先答一句"},
            ],
            "context": {
                "outline": "大纲",
                "points": ["甲"],
                "chapters": [{"title": "开场", "start": 0, "summary": "开场"}],
                "transcript": [{"start": 0, "text": "第一句"}],
            },
        },
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "status" in names
    assert "delta" in names
    assert names[-1] == "done"
    assert events[-1][1]["answer"] == "视频主要讲了保存方法。"
    messages = seen[-1]
    assert [item["role"] for item in messages] == ["system", "user", "assistant", "user"]
    assert "大纲" in messages[-1]["content"]


def test_ask_stream_rejects_empty_context(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    response = client.post("/api/summary/ask/stream", json={"question": "讲了什么", "context": {}})
    assert response.status_code == 400
    assert response.json()["detail"] == "还没有可问答的内容，请提供视频链接或粘贴资料"


def test_ask_stream_rejects_blank_question(client):
    response = client.post("/api/summary/ask/stream", json={"question": "   ", "context": {"outline": "大纲"}})
    assert response.status_code == 400
    assert response.json()["detail"] == "问题不能为空"


def test_ask_stream_error_frame_terminates(client, monkeypatch):
    def broken(messages, json_mode=False):
        raise UserFacingError("总结服务繁忙，请稍后再试", 429)

    monkeypatch.setattr("app.summary._iter_completion", broken)
    response = client.post(
        "/api/summary/ask/stream",
        json={"question": "讲了什么", "context": {"outline": "大纲"}},
    )
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1] == {"message": "总结服务繁忙，请稍后再试", "code": 429}


def test_mermaid_source_keeps_valid_mindmap_syntax():
    result = build_result(
        json.dumps({"outline": "含 (括号) 的大纲", "points": POINTS, "chapters": CHAPTERS}, ensure_ascii=False),
        CUES,
        False,
    )
    code = to_mermaid(build_mindmap(result))
    lines = code.split("\n")
    assert lines[0] == "mindmap"
    assert lines[1] == "  root((视频内容))"
    assert all(line.startswith("  ") for line in lines[1:])
    assert "含 括号 的大纲" in code


def test_tree_from_text_reads_indentation_and_bullets():
    text = "# 视频提纲\n- 开场\n  - 背景介绍\n    - 早年经历\n  - 核心问题\n- 结论\n"
    tree = build_tree_from_text(text)
    assert tree["id"] == "root"
    assert tree["label"] == "视频提纲"
    assert [child["label"] for child in tree["children"]] == ["开场", "结论"]
    assert [child["label"] for child in tree["children"][0]["children"]] == ["背景介绍", "核心问题"]
    assert tree["children"][0]["children"][0]["children"][0]["label"] == "早年经历"


def test_tree_from_text_rejects_blank_input():
    with pytest.raises(UserFacingError) as error:
        build_tree_from_text("   \n\n")
    assert error.value.status == 400


def test_stream_subtitles_accepts_pasted_text(client):
    srt = "1\n00:00:01,000 --> 00:00:03,500\n你好\n\n2\n00:00:04,000 --> 00:00:06,000\n世界\n"
    response = client.post("/api/subtitles/stream", json={"text": srt})
    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "stats" in names
    assert "segment" in names
    assert names[-1] == "done"
    payload = events[-1][1]["result"]
    assert payload["stats"]["cues"] == 2
    assert payload["source"] == "srt"
    assert payload["exports"]["srt"].startswith("1\n00:00:01,000")
    assert payload["exports"]["timed"] == "[00:01] 你好\n[00:04] 世界"
    assert "你好" in payload["exports"]["plain"]


def test_stream_subtitles_requires_source(client):
    response = client.post("/api/subtitles/stream", json={"text": "  ", "url": ""})
    assert response.status_code == 400
    assert response.json()["detail"] == "请提供视频链接或字幕文本"


def test_stream_subtitles_reads_from_url(client, monkeypatch):
    monkeypatch.setattr(
        "app.summary_stream.load_subtitles",
        lambda url, directory: {"cues": CUES, "truncated": False},
    )
    response = client.post("/api/subtitles/stream", json={"url": "https://example.com/watch"})
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert "segment" in names
    payload = events[-1][1]["result"]
    assert payload["source"] == "url"
    assert payload["stats"]["segments"] == 1


def test_stream_mindmap_from_outline_text(client):
    response = client.post(
        "/api/mindmap/stream",
        json={"text": "# 视频提纲\n- 开场\n  - 背景介绍\n- 结论"},
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert "tree" in names
    assert "mermaid" in names
    assert names[-1] == "done"
    tree = events[names.index("tree")][1]["root"]
    assert tree["label"] == "视频提纲"
    assert count_nodes(tree) == 4
    code = events[names.index("mermaid")][1]["code"]
    assert code.startswith("mindmap\n  root((视频提纲))")


def test_stream_mindmap_from_url(client, monkeypatch):
    monkeypatch.setattr(
        "app.summary_stream.load_subtitles",
        lambda url, directory: {"cues": CUES, "truncated": False},
    )
    monkeypatch.setattr("app.summary._iter_completion", fake_stream)
    response = client.post("/api/mindmap/stream", json={"url": "https://example.com/watch"})
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert "tree" in names and "mermaid" in names
    assert names[-1] == "done"
    payload = events[-1][1]["result"]
    assert payload["root"]["children"][0]["id"] == "summary"
    assert payload["mermaid"].startswith("mindmap")


def test_ask_stream_uses_pasted_material(client, monkeypatch):
    seen = []

    def fake(messages, json_mode=False):
        seen.append(messages)
        return iter(["收到", "资料"])

    monkeypatch.setattr("app.summary._iter_completion", fake)
    response = client.post(
        "/api/summary/ask/stream",
        json={"question": "讲了什么", "text": "这是粘贴的笔记：重点在保存流程。"},
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1][1]["answer"] == "收到资料"
    assert "粘贴的笔记" in seen[-1][-1]["content"]


def test_ask_stream_fetches_subtitles_from_url(client, monkeypatch):
    monkeypatch.setattr(
        "app.summary_stream.load_subtitles",
        lambda url, directory: {"cues": CUES, "truncated": False},
    )
    monkeypatch.setattr("app.summary._iter_completion", lambda messages, json_mode=False: iter(["来自", "字幕"]))
    response = client.post(
        "/api/summary/ask/stream",
        json={"question": "讲了什么", "url": "https://example.com/watch"},
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    stages = [item["stage"] for name, item in events if name == "status"]
    assert "fetching_subtitles" in stages
    assert events[-1][0] == "done"
    assert events[-1][1]["answer"] == "来自字幕"

