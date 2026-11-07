"""字幕文本处理：格式识别、清洗、断句、分段和导出。

输入统一成 cue 列表（start/end/text），输出是可直接流式下发的段落。
模型只看清洗后的 cue，前端和问答使用同一份分段结果。
"""

from __future__ import annotations

import json
import re

from app.subtitles import parse_subtitle_text

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_TIMED = re.compile(r"\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}\s+-->|\d{1,2}:\d{2}[.,]\d{1,3}\s+-->")
_SENTENCE = re.compile(r"[^。！？!?…]+[。！？!?…]+|[^。！？!?…]+$")
_ASCII_WORD = re.compile(r"[0-9A-Za-z]")

DEFAULT_MAX_CHARS = 200
DEFAULT_MAX_GAP = 1.5
DEFAULT_MAX_SENTENCE = 120


def detect_format(text: str) -> str:
    """认出来源格式，方便前端提示和排障。"""
    stripped = (text or "").lstrip("\ufeff").strip()
    if not stripped:
        return "empty"
    if stripped.upper().startswith("WEBVTT"):
        return "vtt"
    if stripped[0] in "[{":
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return "timed"
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            return "json3"
        if isinstance(payload, dict) and isinstance(payload.get("body"), list):
            return "bilibili"
        return "json"
    if _TIMED.search(stripped[:4000]):
        return "srt"
    return "timed"


def read_subtitles(text: str) -> dict:
    """解析任意受支持格式的字幕文本，返回格式、清洗后的 cue 与统计。"""
    fmt = detect_format(text)
    cues = normalize_cues(parse_subtitle_text(text))
    return {"format": fmt, "cues": cues, "chars": sum(len(cue["text"]) for cue in cues)}


def normalize_cues(cues: list[dict]) -> list[dict]:
    """去标签、压空白、丢掉空行，并合并相邻的重复字幕（自动字幕常见）。"""
    cleaned: list[dict] = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        text = _SPACE.sub(" ", _TAG.sub("", str(cue.get("text") or ""))).strip()
        if not text:
            continue
        try:
            start = max(0.0, float(cue.get("start") or 0))
            end = max(start, float(cue.get("end") or start))
        except (TypeError, ValueError):
            continue
        if cleaned and text == cleaned[-1]["text"] and start - cleaned[-1]["end"] <= 1.0:
            cleaned[-1]["end"] = max(cleaned[-1]["end"], end)
            continue
        cleaned.append({"start": start, "end": end, "text": text})
    return cleaned


def split_sentences(text: str, max_chars: int = DEFAULT_MAX_SENTENCE) -> list[str]:
    """按中英文句末标点断句；过长的句子再按长度切开，避免一段吞掉整屏。"""
    parts = [part.strip() for part in _SENTENCE.findall(text or "") if part.strip()]
    sentences: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            cut = _soft_cut(part, max_chars)
            sentences.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            sentences.append(part)
    return sentences


def build_segments(
    cues: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
    max_gap: float = DEFAULT_MAX_GAP,
) -> list[dict]:
    """按时间空档和长度把 cue 合并成语义段落。"""
    segments: list[dict] = []
    current: dict | None = None
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        if current is not None:
            too_far = cue["start"] - current["end"] > max_gap
            too_long = len(current["text"]) + len(text) > max_chars
            if too_far or too_long:
                segments.append(_finish_segment(current, len(segments)))
                current = None
        if current is None:
            current = {"start": cue["start"], "end": cue["end"], "text": text}
        else:
            current["text"] = _join_text(current["text"], text)
            current["end"] = max(current["end"], cue["end"])
    if current is not None:
        segments.append(_finish_segment(current, len(segments)))
    return segments


def build_document(
    cues: list[dict],
    truncated: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_gap: float = DEFAULT_MAX_GAP,
) -> dict:
    """字幕处理总入口：清洗 → 分段 → 统计。"""
    normalized = normalize_cues(cues)
    segments = build_segments(normalized, max_chars=max_chars, max_gap=max_gap)
    sentences = sum(len(segment["sentences"]) for segment in segments)
    stats = {
        "cues": len(normalized),
        "characters": sum(len(cue["text"]) for cue in normalized),
        "segments": len(segments),
        "sentences": sentences,
        "duration": round(normalized[-1]["end"], 1) if normalized else 0.0,
        "truncated": truncated,
    }
    return {"cues": normalized, "segments": segments, "stats": stats, "truncated": truncated}


def clock(seconds) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def to_srt(cues: list[dict]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_stamp(cue['start'])} --> {_stamp(cue['end'])}\n{cue['text']}"
        )
    return "\n\n".join(blocks)


def to_vtt(cues: list[dict]) -> str:
    blocks = ["WEBVTT", ""]
    for cue in cues:
        blocks.append(f"{_stamp(cue['start'])} --> {_stamp(cue['end'])}\n{cue['text']}\n")
    return "\n".join(blocks)


def to_plain(cues: list[dict], with_time: bool = False) -> str:
    lines = []
    for cue in cues:
        prefix = f"[{clock(cue['start'])}] " if with_time else ""
        lines.append(prefix + cue["text"])
    return "\n".join(lines)


def _finish_segment(segment: dict, index: int) -> dict:
    text = segment["text"].strip()
    return {
        "index": index,
        "start": round(segment["start"], 3),
        "end": round(segment["end"], 3),
        "text": text,
        "sentences": split_sentences(text),
    }


def _join_text(left: str, right: str) -> str:
    if left and right and _ASCII_WORD.match(left[-1]) and _ASCII_WORD.match(right[0]):
        return f"{left} {right}"
    return left + right


def _soft_cut(text: str, limit: int) -> int:
    """长度切分时优先落在逗号或空格上。"""
    window = text[:limit]
    for mark in ("，", ",", "、", " "):
        index = window.rfind(mark)
        if index >= limit // 2:
            return index + 1
    return limit


def _stamp(seconds) -> str:
    total = float(seconds or 0)
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
