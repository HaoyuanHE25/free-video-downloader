"""把字幕交给 DeepSeek，收成大纲、要点和章节；同时提供流式摘要和多轮问答。"""

from __future__ import annotations

import json
import os
import re

from app.downloader import UserFacingError

DEFAULT_MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
MODEL_TIMEOUT = 120
MAX_POINTS = 8
MAX_CHAPTERS = 12
QA_CONTEXT_LIMIT = 12_000
_START_TOLERANCE = 0.05
_SNAP_SECONDS = 1.0

_SYSTEM = """你只根据用户给出的字幕写中文 JSON，不补充字幕里没有的事实。
严格按 outline、points、chapters 的顺序输出。
outline 和 chapters[].summary 使用 Markdown 组织内容：需要分段时用换行（JSON 里写成 \\n），
可用 **加粗** 强调关键词、用 - 列表罗列并列信息、用 ### 小标题划分层次。
points 每条保持一句话，可用 **加粗** 强调关键词。
章节的 start 必须等于某条字幕开头的秒数。
points 最多 8 条，chapters 最多 12 条。

EXAMPLE JSON OUTPUT:
{
  "outline": "这段视频讲了 **保存公开视频** 的流程。\\n\\n- 先解析链接\\n- 再选择清晰度",
  "points": ["先粘贴公开链接", "再选择清晰度"],
  "chapters": [{"title": "章节名", "start": 12.0, "summary": "这一段在讲什么"}]
}
"""

_QA_SYSTEM = """你是一名视频内容问答助手。只依据用户提供的视频资料回答，不要编造资料之外的事实。
如果资料里没有相关信息，就直说“字幕里没有提到”。用中文简洁作答。
回答使用 Markdown：需要分点时用 - 列表，关键结论用 **加粗**，引用字幕时带上时间点。
"""


def ensure_configured() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise UserFacingError("还没有配置总结服务", 503)


def summarize(cues: list[dict], truncated: bool) -> dict:
    ensure_configured()
    content = call_model(_prompt(cues))
    return build_result(content, cues, truncated)


def build_result(content: str, cues: list[dict], truncated: bool) -> dict:
    try:
        payload = json.loads(content or "")
    except json.JSONDecodeError as exc:
        raise UserFacingError("总结没有生成，请重试", 502) from exc
    if not isinstance(payload, dict):
        raise UserFacingError("总结没有生成，请重试", 502)
    outline = payload.get("outline")
    points = payload.get("points")
    chapters = payload.get("chapters")
    if not isinstance(outline, str) or not outline.strip():
        raise UserFacingError("总结没有生成，请重试", 502)
    if not isinstance(points, list) or not isinstance(chapters, list):
        raise UserFacingError("总结没有生成，请重试", 502)
    clean_points = [str(item).strip() for item in points if str(item).strip()][:MAX_POINTS]
    if not clean_points:
        raise UserFacingError("总结没有生成，请重试", 502)
    return {
        "outline": outline.strip(),
        "points": clean_points,
        "chapters": _chapters(chapters, cues),
        "transcript": [
            {"start": float(cue["start"]), "end": float(cue["end"]), "text": cue["text"]} for cue in cues
        ],
        "truncated": truncated,
    }


def call_model(prompt: str) -> str:
    """非流式入口保留给旧接口；内部同样走流式请求，避免长输出卡住读超时。"""
    chunks = list(
        _iter_completion(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
        )
    )
    content = "".join(chunks)
    if not content.strip():
        raise UserFacingError("总结没有生成，请重试", 502)
    return content


def stream_digest(cues: list[dict], truncated: bool, stop=None):
    """流式生成摘要事件：outline 边生成边下发，要点完成一条发一条。

    最后额外抛出一条 digest_result（由上层截获，不下发给前端）。
    """
    ensure_configured()
    parser = StreamFields()
    content = ""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _prompt(cues)},
    ]
    for piece in _iter_completion(messages, json_mode=True):
        if stop is not None and stop.is_set():
            return
        content += piece
        for name, data in parser.feed(piece):
            yield {"event": name, "data": data}
    result = build_result(content, cues, truncated)
    yield {"event": "outline", "data": {"text": result["outline"]}}
    for index, point in enumerate(result["points"]):
        if index >= len(parser.points):
            yield {"event": "point", "data": {"index": index, "text": point}}
    for index, chapter in enumerate(result["chapters"]):
        yield {"event": "chapter", "data": {"index": index, **chapter}}
    yield {"event": "digest_result", "data": {"result": result}}


def stream_answer(question: str, context: str, history: list[dict], stop=None):
    """多轮问答。历史由前端下发，服务端不保存状态。"""
    ensure_configured()
    messages: list[dict] = [{"role": "system", "content": _QA_SYSTEM}]
    for turn in history:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append(
        {
            "role": "user",
            "content": f"视频资料：\n{context}\n\n问题：{question}",
        }
    )
    collected: list[str] = []
    for piece in _iter_completion(messages):
        if stop is not None and stop.is_set():
            return
        collected.append(piece)
        yield {"event": "delta", "data": {"target": "answer", "text": piece}}
    answer = "".join(collected).strip()
    if not answer:
        raise UserFacingError("回答没有生成，请重试", 502)
    yield {"event": "done", "data": {"answer": answer}}


def build_qa_context(payload: dict, limit: int = QA_CONTEXT_LIMIT) -> str:
    """把前端回传的摘要结构拼成问答资料，并做长度上限。"""
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    outline = str(payload.get("outline") or "").strip()
    if outline:
        parts.append("【摘要】\n" + outline)
    points = [str(item).strip() for item in payload.get("points") or [] if str(item).strip()]
    if points:
        parts.append("【要点】\n" + "\n".join(f"{index + 1}. {item}" for index, item in enumerate(points)))
    chapters = [item for item in payload.get("chapters") or [] if isinstance(item, dict)]
    if chapters:
        lines = []
        for item in chapters:
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if title:
                lines.append(f"[{_clock(_as_seconds(item.get('start')) or 0)}] {title}：{summary}")
        if lines:
            parts.append("【章节】\n" + "\n".join(lines))
    cues = [item for item in payload.get("transcript") or [] if isinstance(item, dict)]
    if cues:
        lines = []
        for item in cues:
            text = str(item.get("text") or "").strip()
            if text:
                lines.append(f"[{_clock(_as_seconds(item.get('start')) or 0)}] {text}")
        if lines:
            parts.append("【字幕】\n" + "\n".join(lines))
    text = "\n\n".join(parts).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n（资料较长，已截断）"
    return text


class StreamFields:
    """从半截 JSON 里增量抠出 outline 和已经闭合的 points。

    模型按 `{"outline": "...", "points": ["..."]}` 输出，这里每次拿到新片段就
    重扫当前缓冲区，只把新增的可读文本抛给前端。
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.outline = ""
        self.points: list[str] = []

    def feed(self, piece: str) -> list[tuple[str, dict]]:
        self.buffer += piece or ""
        events: list[tuple[str, dict]] = []
        outline, _, closed = _partial_string_value(self.buffer, "outline")
        if len(outline) > len(self.outline):
            events.append(("delta", {"target": "outline", "text": outline[len(self.outline) :]}))
            self.outline = outline
        if closed:
            self.outline = outline
        points = _string_array(self.buffer, "points", MAX_POINTS)
        for index in range(len(self.points), len(points)):
            events.append(("point", {"index": index, "text": points[index]}))
        self.points = points
        return events


def _iter_completion(messages: list[dict], json_mode: bool = False):
    from openai import OpenAI

    ensure_configured()
    model = os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"].strip(),
        base_url=BASE_URL,
        timeout=MODEL_TIMEOUT,
    )
    kwargs = {
        "model": model,
        "messages": messages,
        "stream": True,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
    except UserFacingError:
        raise
    except Exception as exc:
        raise _model_error(exc) from exc


def _partial_string_value(text: str, key: str) -> tuple[str, int, bool]:
    start = _find_value_start(text, key)
    if start is None or start >= len(text) or text[start] != '"':
        return "", start or 0, False
    return _decode_string(text, start)


def _string_array(text: str, key: str, limit: int) -> list[str]:
    start = _find_value_start(text, key)
    if start is None or start >= len(text) or text[start] != "[":
        return []
    found: list[str] = []
    index = start + 1
    while index < len(text) and len(found) < limit:
        char = text[index]
        if char == '"':
            value, index, closed = _decode_string(text, index)
            if not closed:
                break
            if value.strip():
                found.append(value)
        elif char == "]":
            break
        else:
            index += 1
    return found


def _decode_string(text: str, quote: int) -> tuple[str, int, bool]:
    """从引号开始解一个 JSON 字符串；没闭合时返回当前能读到的部分。"""
    escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    out: list[str] = []
    index = quote + 1
    while index < len(text):
        char = text[index]
        if char == '"':
            return "".join(out), index + 1, True
        if char == "\\":
            if index + 1 >= len(text):
                break
            mark = text[index + 1]
            if mark == "u":
                code = text[index + 2 : index + 6]
                if len(code) < 4 or not all(ch in "0123456789abcdefABCDEF" for ch in code):
                    break
                try:
                    out.append(chr(int(code, 16)))
                except ValueError:
                    break
                index += 6
                continue
            out.append(escapes.get(mark, mark))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out), index, False


def _find_value_start(text: str, key: str) -> int | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
    return match.end() if match else None


def _prompt(cues: list[dict]) -> str:
    return "\n".join(f"[{_clock(float(cue['start']))}] {cue['text']}" for cue in cues)


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _chapters(chapters: list, cues: list[dict]) -> list[dict]:
    starts = [float(cue["start"]) for cue in cues]
    kept = []
    for item in chapters:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        start = _as_seconds(item.get("start"))
        if not title or not summary or start is None:
            continue
        snapped = _snap_start(start, starts)
        if snapped is None:
            continue
        kept.append({"title": title, "start": snapped, "summary": summary})
        if len(kept) >= MAX_CHAPTERS:
            break
    return kept


def _as_seconds(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return None
        if len(numbers) == 2:
            return numbers[0] * 60 + numbers[1]
        if len(numbers) == 3:
            return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None


def _snap_start(start: float, starts: list[float]) -> float | None:
    """章节时间只要落在字幕附近就吸附到最近的 cue，避免模型差几毫秒被丢掉。"""
    if not starts:
        return None
    nearest = min(starts, key=lambda cue: abs(cue - start))
    if abs(nearest - start) <= _SNAP_SECONDS:
        return nearest
    if _on_cue(start, starts):
        return start
    return None


def _on_cue(start: float, starts: list[float]) -> bool:
    return any(abs(start - cue) <= _START_TOLERANCE for cue in starts)


def _model_error(exc: Exception) -> UserFacingError:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return UserFacingError("总结服务的密钥无效", 502)
    if status == 429:
        return UserFacingError("总结服务繁忙，请稍后再试", 429)
    return UserFacingError("总结失败，请重试", 502)
