"""取公开字幕。不下载视频，也不接收平台 Cookie。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

import httpx

from app.downloader import (
    BILIBILI_REFERER,
    UserFacingError,
    _base_opts,
    _ydl,
    validate_public_url,
)

CHAR_LIMIT = 60_000
NO_SUBTITLE = "这条公开视频没有可用字幕，暂时无法总结"
CACHE_TTL_SECONDS = 10 * 60
CACHE_LIMIT = 40
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_BV = re.compile(r"(BV[0-9A-Za-z]{10})")
_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s+-->\s+"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
_CAPTION_LISTS = {"caption_infos", "subtitle_infos", "subtitles"}
_WBI_MIXIN = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
)
# 播放器用来把 subtitle.bilibili.com 上的伪装地址还原成 aisubtitle.hdslb.com。
_SUBTITLE_MASKS = (
    ('nP](wOFRvU.+<fjS{jn-!$D|Dz&",zT`', "=CFxYRn{.y|uVyO$uh&sikph?N.ilF/`"),
    ('Bn"q~|albg@]Go~ACgyDvKnd+)_D}^&J?', "Cu~L!xs~f^&r@'vh=q]q{eeng*sEg^kp#J"),
)
_MASKED_SUBTITLE = re.compile(r"//subtitle\.bilibili\.com/([^?]+)")


def load_subtitles(url: str, directory: Path) -> dict:
    """读取字幕。成功结果做短 TTL 缓存，重复总结同一条视频不用再抓一次。"""
    cached = _cache_get(url)
    if cached is not None:
        return cached
    directory.mkdir(parents=True, exist_ok=True)
    cues = _collect(url, directory)
    kept, truncated = limit_cues(cues)
    if not kept:
        raise UserFacingError(NO_SUBTITLE, 422)
    payload = {"cues": kept, "truncated": truncated}
    _cache_put(url, payload)
    return payload


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_get(url: str) -> dict | None:
    now = time.monotonic()
    with _cache_lock:
        item = _cache.get(url)
        if item is None:
            return None
        stamp, payload = item
        if now - stamp > CACHE_TTL_SECONDS:
            _cache.pop(url, None)
            return None
        return {
            "cues": [dict(cue) for cue in payload["cues"]],
            "truncated": payload["truncated"],
        }


def _cache_put(url: str, payload: dict) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_LIMIT:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)
        _cache[url] = (time.monotonic(), payload)


def limit_cues(cues: list[dict]) -> tuple[list[dict], bool]:
    kept: list[dict] = []
    total = 0
    truncated = False
    for cue in cues:
        text = " ".join(str(cue.get("text") or "").split())
        if not text:
            continue
        room = CHAR_LIMIT - total
        if room <= 0:
            truncated = True
            break
        if len(text) > room:
            text = text[:room]
            truncated = True
        start = float(cue.get("start") or 0)
        end = float(cue.get("end") or start)
        kept.append({"start": start, "end": max(end, start), "text": text})
        total += len(text)
        if truncated:
            break
    return kept, truncated


def pick_subtitle(tracks: list[dict]) -> dict | None:
    ranked: list[tuple[int, dict]] = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        rank = language_rank(str(track.get("lan") or track.get("lang") or track.get("language") or ""))
        if rank is None:
            continue
        ranked.append((rank, track))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def language_rank(code: str) -> int | None:
    norm = code.strip().lower().replace("_", "-")
    if not norm:
        return None
    if norm == "zh-cn":
        return 0
    if norm.startswith("ai-zh"):
        return 1
    if norm == "zh" or norm.startswith("zh-"):
        return 2
    if norm == "en" or norm.startswith("en-"):
        return 3
    return None


def parse_subtitle_text(text: str) -> list[dict]:
    stripped = text.lstrip("\ufeff").strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            body = payload.get("body")
            if isinstance(body, list):
                return _bilibili_body(body)
            if isinstance(payload.get("events"), list):
                return _json3(payload)
        if isinstance(payload, list):
            return _bilibili_body(payload)
    return _timed_text(stripped)


def _collect(url: str, directory: Path) -> list[dict]:
    from app import douyin

    if douyin.matches(url):
        return _douyin_cues(url)
    if _is_bilibili(url):
        cues = _bilibili_cues(url)
        if cues:
            return cues
    return _ytdlp_cues(url, directory)


def _is_bilibili(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "bilibili.com" or host.endswith(".bilibili.com")


def _bilibili_cues(url: str) -> list[dict]:
    found = _BV.search(url)
    if not found:
        return []
    bvid = found.group(1)
    page = _page_number(url)
    headers = {
        "Referer": BILIBILI_REFERER,
        "Origin": "https://www.bilibili.com",
        "User-Agent": _UA,
    }
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False, headers=headers) as client:
            view = client.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
            if view.status_code != 200:
                return []
            cid = _cid(view.json(), page)
            if cid is None:
                return []
            player = client.get(f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}")
            if player.status_code != 200:
                return []
            cues = _cues_from_tracks(client, headers, _subtitle_tracks(player.json()))
            if cues:
                return cues
            return _cues_from_tracks(client, headers, _signed_subtitle_tracks(client, view.json(), page))
    except UserFacingError:
        return []
    except (httpx.HTTPError, ValueError):
        return []


def _page_number(url: str) -> int:
    raw = parse_qs(urlparse(url).query).get("p", ["1"])[0]
    try:
        page = int(raw)
    except ValueError:
        return 1
    return page if page > 0 else 1


def _cid(payload: dict, page: int) -> int | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("code") not in {0, None}:
        return None
    pages = data.get("pages") or []
    if isinstance(pages, list) and 1 <= page <= len(pages) and isinstance(pages[page - 1], dict):
        cid = pages[page - 1].get("cid")
        if isinstance(cid, int):
            return cid
    cid = data.get("cid")
    return cid if isinstance(cid, int) else None


def _subtitle_tracks(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("code") not in {0, None}:
        return []
    data = payload.get("data") or {}
    tracks = (data.get("subtitle") or {}).get("subtitles") if isinstance(data, dict) else None
    if not isinstance(tracks, list):
        return []
    return [item for item in tracks if isinstance(item, dict)]


def _douyin_cues(url: str) -> list[dict]:
    from app import douyin

    aweme = douyin._aweme(douyin._video_id(url))
    found: list[tuple[str, str]] = []
    _caption_urls(aweme.get("video") or {}, found)
    if not found:
        raise UserFacingError(NO_SUBTITLE, 422)
    ranked = [(rank, link) for lang, link in found if (rank := language_rank(lang)) is not None]
    if not ranked:
        raise UserFacingError(NO_SUBTITLE, 422)
    ranked.sort(key=lambda item: item[0])
    target = validate_public_url(ranked[0][1])
    headers = {"Referer": "https://www.douyin.com/", "User-Agent": _UA}
    try:
        response = httpx.get(target, headers=headers, timeout=20.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise UserFacingError("暂时无法读取字幕，请稍后再试", 502) from exc
    if response.status_code != 200:
        raise UserFacingError(NO_SUBTITLE, 422)
    cues = parse_subtitle_text(response.text)
    if not cues:
        raise UserFacingError(NO_SUBTITLE, 422)
    return cues


def _caption_urls(node, found: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _CAPTION_LISTS and isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    link = item.get("url") or item.get("Url") or item.get("subtitle_url")
                    lang = item.get("lang") or item.get("language") or item.get("lan") or "zh-CN"
                    if isinstance(link, str) and link.startswith("http"):
                        found.append((str(lang), link))
            elif isinstance(value, (dict, list)):
                _caption_urls(value, found)
    elif isinstance(node, list):
        for item in node:
            _caption_urls(item, found)


def _ytdlp_cues(url: str, directory: Path) -> list[dict]:
    opts = _base_opts(
        {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-CN", "zh-Hans", "zh", "ai-zh", "en", "en-US"],
            "subtitlesformat": "json3/vtt/srt",
            "outtmpl": str(directory / "%(id)s"),
            "overwrites": True,
        },
        page_url=url,
    )
    try:
        with _ydl(opts) as ydl:
            ydl.extract_info(url, download=True)
    except UserFacingError:
        raise
    except Exception as exc:
        raise UserFacingError("暂时无法读取字幕，请稍后再试", 502) from exc
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".vtt", ".srt", ".json", ".json3"}
    ]
    chosen = _pick_file(files)
    if chosen is None:
        raise UserFacingError(NO_SUBTITLE, 422)
    return parse_subtitle_text(chosen.read_text(encoding="utf-8", errors="replace"))


def _pick_file(paths: list[Path]) -> Path | None:
    ranked: list[tuple[int, Path]] = []
    for path in paths:
        parts = path.name.split(".")
        code = parts[-2] if len(parts) >= 3 else ""
        rank = language_rank(code)
        if rank is None:
            continue
        ranked.append((rank, path))
    if ranked:
        ranked.sort(key=lambda item: item[0])
        return ranked[0][1]
    return paths[0] if len(paths) == 1 else None


def _bilibili_body(body: list) -> list[dict]:
    cues = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("content") or "").split())
        if not text:
            continue
        start = float(item.get("from") or 0)
        end = float(item.get("to") or start)
        cues.append({"start": start, "end": max(end, start), "text": text})
    return cues


def _json3(payload: dict) -> list[dict]:
    cues = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs") or []
        text = "".join(str(seg.get("utf8") or "") for seg in segs if isinstance(seg, dict))
        text = " ".join(text.split())
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000
        duration = float(event.get("dDurationMs") or 0) / 1000
        cues.append({"start": start, "end": start + duration, "text": text})
    return cues


def _timed_text(text: str) -> list[dict]:
    cues = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        match = _TIME.search(lines[index])
        if not match:
            index += 1
            continue
        start = _stamp(match, 1)
        end = _stamp(match, 5)
        index += 1
        parts = []
        while index < len(lines) and lines[index].strip():
            parts.append(re.sub(r"<[^>]+>", "", lines[index]))
            index += 1
        spoken = " ".join(part.strip() for part in parts).strip()
        if spoken:
            cues.append({"start": start, "end": max(end, start), "text": spoken})
    return cues


def _stamp(match: re.Match, group: int) -> float:
    hours = int(match.group(group) or 0)
    minutes = int(match.group(group + 1))
    seconds = int(match.group(group + 2))
    fraction = match.group(group + 3)
    millis = int(fraction.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def unmask_bilibili_subtitle(url: str) -> str:
    """把播放器返回的伪装字幕地址还原成可下载的公开地址。"""
    matched = _MASKED_SUBTITLE.search(url or "")
    if not matched:
        return ""
    try:
        hidden = unquote(matched.group(1))
    except ValueError:
        return ""
    query = urlparse(url).query
    for prefix, mask in _SUBTITLE_MASKS:
        key = f"{mask}bilibili"
        revealed = "".join(chr(ord(char) ^ ord(key[index % len(key)])) for index, char in enumerate(hidden))
        if not revealed.startswith(prefix):
            continue
        path = revealed[len(prefix) :]
        if not path.startswith("/"):
            continue
        target = f"https://aisubtitle.hdslb.com{path}"
        return f"{target}?{query}" if query else target
    return ""


def _cues_from_tracks(client: httpx.Client, headers: dict, tracks: list[dict]) -> list[dict]:
    chosen = pick_subtitle(tracks)
    if chosen is None:
        return []
    raw = chosen.get("subtitle_url") or ""
    if not isinstance(raw, str) or not raw:
        return []
    revealed = unmask_bilibili_subtitle(raw) or absolute_subtitle_url(raw, "https://api.bilibili.com/")
    current = validate_public_url(revealed)
    response = client.get(current, headers=headers)
    if response.status_code != 200:
        return []
    return parse_subtitle_text(response.text)


def _signed_subtitle_tracks(client: httpx.Client, view: dict, page: int) -> list[dict]:
    data = view.get("data") if isinstance(view, dict) else None
    cid = _cid(view, page)
    aid = data.get("aid") if isinstance(data, dict) else None
    if not isinstance(cid, int) or not isinstance(aid, int):
        return []
    pages = data.get("pages") if isinstance(data, dict) else None
    language = ""
    if isinstance(pages, list) and 1 <= page <= len(pages) and isinstance(pages[page - 1], dict):
        language = str(pages[page - 1].get("asr_language") or "")
    params = {
        "oid": cid,
        "pid": aid,
        "context_ext": '{"video_type":1}',
        "type": 1,
        "cur_production_type": 0,
        "playlist_switch": 0,
        "arc_video_language": language,
        "web_location": "1315873",
        "x-bili-device-req-json": '{"platform":"web","device":"pc","mobi_app":"web_cn"}',
        "x-bili-locale-json": '{"c_locale":{"language":"zh","script":"Hans"},"always_translate":false}',
    }
    signed = _sign_wbi(params, _wbi_key(client))
    payload = client.get("https://api.bilibili.com/x/v2/subtitle/web/view?" + urlencode(signed)).content
    return _tracks_from_protobuf(payload)


def _wbi_key(client: httpx.Client) -> str:
    nav = client.get("https://api.bilibili.com/x/web-interface/nav").json()
    images = ((nav.get("data") or {}).get("wbi_img") or {}) if isinstance(nav, dict) else {}
    lookup = "".join(
        str(images.get(name) or "").rpartition("/")[2].partition(".")[0] for name in ("img_url", "sub_url")
    )
    if len(lookup) <= max(_WBI_MIXIN):
        return ""
    return "".join(lookup[index] for index in _WBI_MIXIN)[:32]


def _sign_wbi(params: dict, key: str) -> dict:
    signed = {name: "".join(char for char in str(value) if char not in "!'()*") for name, value in params.items()}
    signed["wts"] = str(round(time.time()))
    ordered = dict(sorted(signed.items()))
    digest = hashlib.md5(f"{urlencode(ordered)}{key}".encode()).hexdigest()
    ordered["w_rid"] = digest
    return ordered


def _tracks_from_protobuf(payload: bytes) -> list[dict]:
    tracks = []
    language = ""
    for item in _protobuf_strings(payload):
        if item.startswith("//") or item.startswith("http"):
            if language:
                tracks.append({"lan": language, "subtitle_url": item})
            language = ""
        elif language_rank(item) is not None:
            language = item
    return tracks


def _protobuf_strings(payload: bytes) -> list[str]:
    found: list[str] = []

    def walk(buf: bytes) -> None:
        index = 0
        while index < len(buf):
            try:
                key, index = _varint(buf, index)
                wire = key & 7
                if wire == 0:
                    _, index = _varint(buf, index)
                elif wire == 1:
                    index += 8
                elif wire == 5:
                    index += 4
                elif wire == 2:
                    length, index = _varint(buf, index)
                    chunk = buf[index : index + length]
                    index += length
                    try:
                        found.append(chunk.decode("utf-8"))
                    except UnicodeDecodeError:
                        walk(chunk)
                else:
                    return
            except (IndexError, ValueError):
                return

    walk(payload)
    return found


def _varint(buf: bytes, index: int) -> tuple[int, int]:
    number = shift = 0
    while shift < 70:
        byte = buf[index]
        index += 1
        number |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return number, index
        shift += 7
    raise ValueError("varint too long")


def absolute_subtitle_url(url: str, base: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base, url)
