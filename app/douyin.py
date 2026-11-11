"""抖音公开视频。不接收用户 Cookie，只使用服务自己注册的匿名 ttwid。"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from app.downloader import (
    DOWNLOAD_TIMEOUT_SECONDS,
    MAX_FILE_BYTES,
    UserFacingError,
    safe_filename,
    size_label,
    validate_public_url,
)

_AID = 6383
_SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_REFERER = "https://www.douyin.com/"
_ID = re.compile(r"(?:(?:modal_id|aweme_id|item_id|item_ids)=|/video/|/note/|/share/video/)(\d{15,22})")
_MEDIA_HOSTS = (
    "douyinvod.com",
    "douyincdn.com",
    "bytevod.com",
    "bytecdn.cn",
    "ibytedtos.com",
    "snssdk.com",
    "amemv.com",
)
_IMAGE_HOSTS = ("douyinpic.com", "byteimg.com", "ibyteimg.com", "pstatp.com", "douyin.com")


def matches(url: str) -> bool:
    host = _host(url)
    return host == "douyin.com" or host.endswith(".douyin.com") or host == "iesdouyin.com" or host.endswith(
        ".iesdouyin.com"
    )


def extract(url: str) -> dict:
    aweme = _aweme(_video_id(url))
    video = aweme.get("video") or {}
    if not video.get("bit_rate") and not (video.get("play_addr") or {}).get("url_list"):
        raise UserFacingError("这条是图文，暂时只能保存视频", 422)
    formats = _formats(video)
    if not formats:
        raise UserFacingError("没有可保存的公开清晰度", 422)
    duration = video.get("duration")
    seconds = None
    if isinstance(duration, (int, float)) and duration > 0:
        seconds = int(round(duration / 1000))
    title = (aweme.get("desc") or "").strip() or "抖音视频"
    return {
        "title": title[:200],
        "thumbnail": _thumbnail(video),
        "duration": seconds,
        "extractor_key": "抖音",
        "formats": formats,
    }


def download(
    url: str,
    format_id: str,
    directory: Path,
    on_progress,
    *,
    max_bytes: int | None = None,
    timeout_seconds: float | None = None,
) -> tuple[Path, str]:
    limit_bytes = MAX_FILE_BYTES if max_bytes is None else max_bytes
    limit_seconds = DOWNLOAD_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    directory.mkdir(parents=True, exist_ok=True)
    info = extract(url)
    chosen = next((item for item in info["formats"] if item["format_id"] == format_id), None)
    if chosen is None:
        raise UserFacingError("清晰度选项无效")
    expected = chosen.get("filesize") or 0
    if expected > limit_bytes:
        raise UserFacingError(f"文件超过约 {size_label(limit_bytes)}，请换较低清晰度")
    started = time.monotonic()
    last_error = UserFacingError("下载没有完成，请重试")
    for media in chosen.get("urls") or []:
        try:
            path = _save(
                media,
                directory / "media.mp4",
                on_progress,
                started,
                expected,
                limit_bytes=limit_bytes,
                limit_seconds=limit_seconds,
            )
            return path, safe_filename(info["title"], "mp4")
        except UserFacingError as exc:
            last_error = exc
    raise last_error


def _formats(video: dict) -> list[dict]:
    chosen: list[dict] = []
    seen: set[str] = set()
    for rate in video.get("bit_rate") or []:
        if str(rate.get("format") or "").lower() == "dash":
            continue
        addr = rate.get("play_addr") or {}
        url_key = str(addr.get("url_key") or "")
        if "bytevc2" in url_key:
            continue
        urls = [item for item in addr.get("url_list") or [] if _media_url(item)]
        if not urls:
            continue
        height = int(addr.get("height") or 0)
        width = int(addr.get("width") or 0)
        bitrate = rate.get("bit_rate") or 0
        format_id = _format_id(url_key, height, bitrate, seen)
        h265 = bool(rate.get("is_h265") or rate.get("is_bytevc1") or "bytevc1" in url_key)
        chosen.append(
            {
                "format_id": format_id,
                "ext": "mp4",
                "height": height or None,
                "width": width or None,
                "vcodec": "h265" if h265 else "h264",
                "acodec": "aac",
                "filesize": int(addr.get("data_size") or 0) or None,
                "tbr": (bitrate / 1000) if bitrate else 0,
                "urls": urls,
            }
        )
    return chosen


def _format_id(url_key: str, height: int, bitrate, seen: set[str]) -> str:
    raw = re.sub(r"[^A-Za-z0-9._+-]", "", url_key)[:80]
    if not raw or not raw[0].isalnum():
        raw = f"h{height}p{int(bitrate or 0)}"
    candidate = raw
    suffix = 2
    while candidate in seen:
        candidate = f"{raw[:76]}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _video_id(url: str) -> str:
    found = _ID.search(url)
    if found:
        return found.group(1)
    if _host(url) != "v.douyin.com":
        raise UserFacingError("这条链接里没有视频", 422)
    current = url
    with httpx.Client(timeout=15.0, follow_redirects=False, headers={"User-Agent": _UA}) as client:
        for _ in range(5):
            response = client.get(current, headers={"Referer": _REFERER})
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("location")
            if not location:
                break
            current = validate_public_url(urljoin(current, location))
            found = _ID.search(current)
            if found:
                return found.group(1)
    raise UserFacingError("这条链接里没有视频", 422)


def _aweme(video_id: str) -> dict:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False, headers={"User-Agent": _UA}) as client:
            registered = client.post(
                "https://www.douyin.com/ttwid/register",
                json={"aid": _AID, "service": "www.douyin.com"},
                headers={"Referer": _REFERER, "Content-Type": "application/json"},
            )
            if registered.status_code != 200 or not client.cookies.get("ttwid"):
                raise UserFacingError("暂时无法解析这条链接", 502)
            home = client.get(_REFERER, headers={"Referer": _REFERER})
            uifid = ""
            for name in ("uifid", "uifid_temp", "UIFID", "UIFID_TEMP"):
                value = client.cookies.get(name)
                if value:
                    uifid = value
                    break
            if not uifid:
                uifid = home.headers.get("x-tt-trace-host") or ""
            client.cookies.set("passport_csrf_token", "0" * 32, domain=".douyin.com")
            detail_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?" + urlencode(
                _signed_query({"aweme_id": video_id, "aid": str(_AID)}, uifid)
            )
            detail = client.get(detail_url, headers={"Referer": f"https://www.douyin.com/video/{video_id}"})
    except UserFacingError:
        raise
    except httpx.TimeoutException as exc:
        raise UserFacingError("解析超时，请稍后再试", 504) from exc
    except httpx.HTTPError as exc:
        raise UserFacingError("暂时无法解析这条链接", 502) from exc
    if detail.status_code != 200:
        raise UserFacingError("暂时无法解析这条链接", 502)
    try:
        payload = detail.json()
    except ValueError as exc:
        raise UserFacingError("暂时无法解析这条链接", 502) from exc
    aweme = payload.get("aweme_detail") if isinstance(payload, dict) else None
    if not isinstance(aweme, dict):
        raise UserFacingError("这条视频暂时取不到，可能不是公开视频", 422)
    return aweme


def _signed_query(query: dict, uifid: str) -> dict:
    timestamp = str(int(time.time()))
    signed = {**query, "uifid": uifid, "timestamp": timestamp}
    encoded = urlencode(signed)
    signature = hashlib.md5(f"{uifid}_{timestamp}_{_SALT}_{encoded}".encode()).hexdigest()
    return {**signed, "x-secsdk-web-signature": signature}


def _thumbnail(video: dict) -> str | None:
    covers = (video.get("cover") or {}).get("url_list") or []
    for url in covers:
        if isinstance(url, str) and url.startswith("https://") and _under_hosts(url, _IMAGE_HOSTS):
            return url
    return None


def _save(
    url: str,
    dest: Path,
    on_progress,
    started: float,
    expected: int,
    *,
    limit_bytes: int = MAX_FILE_BYTES,
    limit_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> Path:
    headers = {"User-Agent": _UA, "Referer": _REFERER}
    current = validate_public_url(url)
    if not _under_hosts(current, _MEDIA_HOSTS):
        raise UserFacingError("下载没有完成，请重试")
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for _ in range(4):
            _check_time(started, limit_seconds)
            with client.stream("GET", current, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        break
                    current = validate_public_url(urljoin(current, location))
                    if not _under_hosts(current, _MEDIA_HOSTS):
                        raise UserFacingError("下载没有完成，请重试")
                    continue
                if response.status_code != 200:
                    raise UserFacingError("下载没有完成，请重试")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media_type and not (media_type.startswith("video/") or media_type == "application/octet-stream"):
                    raise UserFacingError("下载没有完成，请重试")
                total = _content_length(response.headers.get("content-length")) or expected
                if total > limit_bytes:
                    raise UserFacingError(f"文件超过约 {size_label(limit_bytes)}，请换较低清晰度")
                received = 0
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes(256 * 1024):
                        _check_time(started, limit_seconds)
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > limit_bytes:
                            raise UserFacingError(f"文件超过约 {size_label(limit_bytes)}，请换较低清晰度")
                        handle.write(chunk)
                        if total:
                            on_progress(min(received / total, 0.99))
                if received < 1024:
                    dest.unlink(missing_ok=True)
                    raise UserFacingError("下载没有完成，请重试")
                on_progress(1)
                return dest
    raise UserFacingError("下载没有完成，请重试")


def _content_length(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _check_time(started: float, limit_seconds: float = DOWNLOAD_TIMEOUT_SECONDS) -> None:
    if time.monotonic() - started > limit_seconds:
        raise UserFacingError("下载超时，请换一条较短的公开视频")


def _media_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://") and _under_hosts(url, _MEDIA_HOSTS)


def _under_hosts(url: str, roots: tuple[str, ...]) -> bool:
    host = _host(url)
    return any(host == root or host.endswith("." + root) for root in roots)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")
