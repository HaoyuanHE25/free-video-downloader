"""薄封装：校验公开链接，调用 yt-dlp，把格式收成少数清晰度。"""

from __future__ import annotations

import ipaddress
import logging
import re
import shutil
import socket
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx

log = logging.getLogger("suixia")

MAX_FILE_BYTES = 500 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 10 * 60
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,80}$")
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 测试会替换这个类。保持为 None 时才真正导入 yt-dlp。
YoutubeDL = None

BANDS = (
    ("1080p", 721, 1080),
    ("720p", 481, 720),
    ("480p", 1, 480),
)
VIDEO_EXTS = {"mp4", "webm", "mkv", "mov", "m4v", "flv"}
AUDIO_EXTS = {"m4a", "mp3", "aac", "opus", "ogg", "wav", "flac"}
BILIBILI_REFERER = "https://www.bilibili.com/"
_COVER_BYTES = 2 * 1024 * 1024


class UserFacingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


_HOST_PATH = re.compile(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:[/:?#]|$)")


def validate_public_url(url: str) -> str:
    raw = _with_scheme((url or "").strip())
    if not raw or len(raw) > 2048 or any(ch.isspace() for ch in raw):
        raise UserFacingError("链接无效")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserFacingError("链接无效")
    if parsed.username or parsed.password:
        raise UserFacingError("链接无效")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UserFacingError("链接无效")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise UserFacingError("不支持本机或内网地址")
    literal = _literal_ip(host)
    if literal is not None:
        if not _is_public(literal):
            raise UserFacingError("不支持本机或内网地址")
        return raw
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UserFacingError("链接无效") from exc
    addresses = []
    for info in infos:
        address = _literal_ip(str(info[4][0]).split("%", 1)[0])
        if address is not None:
            addresses.append(address)
    # 有的网络会给公网域名多回一条不可用的 IPv6。只要还有公网地址，就不当成内网。
    if not addresses or not any(_is_public(address) for address in addresses):
        raise UserFacingError("不支持本机或内网地址")
    return raw


def validate_format_id(format_id: str) -> str:
    if not format_id or not FORMAT_ID_RE.fullmatch(format_id):
        raise UserFacingError("清晰度选项无效")
    return format_id


def parse(url: str) -> dict:
    from app import douyin

    if douyin.matches(url):
        info = douyin.extract(url)
        presented = present_info(info, ffmpeg=ffmpeg_available())
        if not presented["formats"]:
            raise UserFacingError("没有可保存的公开清晰度", 422)
        return presented
    opts = _base_opts(page_url=url)
    try:
        with _ydl(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except UserFacingError:
        raise
    except Exception as exc:
        log.warning("parse failed: %s", exc)
        raise UserFacingError(_humanize_parse(exc), _status_for_parse(exc)) from exc
    info = _single_info(info)
    presented = present_info(info, ffmpeg=ffmpeg_available())
    if not presented["formats"]:
        raise UserFacingError("没有可保存的公开清晰度", 422)
    return presented


def download_media(url: str, format_id: str, directory: Path, on_progress) -> tuple[Path, str]:
    from app import douyin

    if douyin.matches(url):
        return douyin.download(url, format_id, directory, on_progress)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def hook(event: dict) -> None:
        if time.monotonic() - started > DOWNLOAD_TIMEOUT_SECONDS:
            raise UserFacingError("下载超时，请换一条较短的公开视频")
        if event.get("status") != "downloading":
            return
        total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
        done = event.get("downloaded_bytes") or 0
        if total:
            on_progress(min(done / total, 0.99))

    opts = _base_opts(
        {
            "format": format_id,
            "outtmpl": str(directory / "media.%(ext)s"),
            "max_filesize": MAX_FILE_BYTES,
            "progress_hooks": [hook],
            "overwrites": True,
            "fragment_retries": 1,
        },
        page_url=url,
    )
    if "+" in format_id:
        opts["merge_output_format"] = "mp4"
    try:
        with _ydl(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except UserFacingError:
        raise
    except Exception as exc:
        log.warning("download failed: %s", exc)
        raise UserFacingError(_humanize_download(exc)) from exc
    info = _single_info(info) or {}
    files = _output_files(directory)
    if not files:
        raise UserFacingError("下载没有完成，请重试")
    path = max(files, key=lambda item: item.stat().st_size)
    if path.stat().st_size > MAX_FILE_BYTES:
        path.unlink(missing_ok=True)
        raise UserFacingError("文件超过约 500MB，请换较低清晰度")
    on_progress(1)
    title = info.get("title") or "video"
    return path, safe_filename(str(title), path.suffix.lstrip("."))


def present_info(info: dict, *, ffmpeg: bool) -> dict:
    duration = info.get("duration")
    duration = duration if isinstance(duration, (int, float)) and duration > 0 else None
    formats = collapse_formats(info.get("formats") or [], ffmpeg=ffmpeg, duration=duration)
    thumbnail = _public_thumbnail(info.get("thumbnail"))
    hint = None
    if not ffmpeg and any(item["needs_merge"] for item in formats):
        hint = "本机未检测到 ffmpeg。画面和声音是分开的清晰度需要它才能合成一个文件，仅音频可以先保存。"
    elif not ffmpeg:
        hint = "本机未检测到 ffmpeg，暂时只能保存已经包含声音的单文件。"
    return {
        "title": info.get("title") or "未命名视频",
        "thumbnail": thumbnail,
        "duration": int(duration) if isinstance(duration, (int, float)) else None,
        "platform": info.get("extractor_key") or info.get("extractor") or "视频",
        "ffmpeg": ffmpeg,
        "hint": hint,
        "formats": formats,
    }


def collapse_formats(formats: list[dict], *, ffmpeg: bool, duration: float | None = None) -> list[dict]:
    usable = [item for item in formats if _usable(item)]
    audio = _best([item for item in usable if _audio_only(item)], _audio_score)
    chosen: list[dict] = []
    for label, low, high in BANDS:
        in_band = [
            item
            for item in usable
            if _has_video(item) and low <= int(item.get("height") or 0) <= high
        ]
        if not in_band:
            continue
        best = _best(in_band, _video_score)
        if best is None:
            continue
        label = _quality_label(int(best.get("height") or 0))
        if _has_audio(best):
            chosen.append(_option(best, label=label, needs_merge=False, duration=duration))
            continue
        if audio is not None and (ffmpeg or not any(_has_audio(item) for item in in_band)):
            chosen.append(_merged_option(best, audio, label, duration=duration))
            continue
        combined = _best([item for item in in_band if _has_audio(item)], _video_score)
        if combined is not None:
            chosen.append(_option(combined, label=label, needs_merge=False, duration=duration))
            continue
        if audio is not None:
            chosen.append(_merged_option(best, audio, label, duration=duration))
    if not any(not item["audio_only"] for item in chosen):
        unknown = [
            item for item in usable if _has_video(item) and int(item.get("height") or 0) <= 0
        ]
        fallback = _best(unknown, _video_score)
        if fallback is not None and _has_audio(fallback):
            chosen.append(_option(fallback, label="原文件", needs_merge=False, duration=duration))
        elif fallback is not None and ffmpeg and audio is not None:
            chosen.append(
                {
                    "format_id": f"{fallback.get('format_id')}+{audio.get('format_id')}",
                    "label": "原文件",
                    "ext": "mp4",
                    "filesize": _add_size(fallback, audio, duration=duration),
                    "height": None,
                    "audio_only": False,
                    "needs_merge": True,
                }
            )
    if audio is not None:
        option = _option(audio, label="仅音频", needs_merge=False, duration=duration)
        option["audio_only"] = True
        option["height"] = None
        chosen.append(option)
    return chosen


def safe_filename(title: str, ext: str) -> str:
    cleaned = _INVALID_FILENAME.sub("", title or "").strip().rstrip(". ")
    if not cleaned:
        cleaned = "video"
    cleaned = cleaned[:80]
    suffix = _INVALID_FILENAME.sub("", ext or "mp4").lower().lstrip(".") or "mp4"
    if len(suffix) > 8 or not suffix.isalnum():
        suffix = "mp4"
    return f"{cleaned}.{suffix}"


def _ydl(opts: dict):
    cls = YoutubeDL
    if cls is None:
        try:
            from yt_dlp import YoutubeDL as imported
        except ImportError as exc:
            raise UserFacingError("服务器还没有安装 yt-dlp", 500) from exc
        globals()["YoutubeDL"] = imported
        cls = imported
    return cls(opts)


def fetch_cover(url: str) -> tuple[bytes, str]:
    """用 B 站认可的 Referer 取回封面。只允许 hdslb 的图片地址。"""
    current = validate_public_url(url)
    if not _cover_needs_proxy(current):
        raise UserFacingError("这个封面不能转发")
    headers = {
        "Referer": BILIBILI_REFERER,
        "Origin": "https://www.bilibili.com",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        for _ in range(3):
            response = client.get(current, headers=headers)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                current = validate_public_url(urljoin(current, location))
                if not _cover_needs_proxy(current):
                    raise UserFacingError("这个封面不能转发")
                continue
            if response.status_code != 200:
                raise UserFacingError("封面暂时取不到", 502)
            media_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip().lower()
            if not media_type.startswith("image/"):
                raise UserFacingError("封面暂时取不到", 502)
            body = response.content
            if not body or len(body) > _COVER_BYTES:
                raise UserFacingError("封面暂时取不到", 502)
            return body, media_type
    raise UserFacingError("封面暂时取不到", 502)


def _base_opts(extra: dict | None = None, page_url: str | None = None) -> dict:
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 1,
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    headers = _bilibili_headers(page_url or "")
    if headers:
        opts["http_headers"] = headers
    youtube_args = _youtube_extractor_args(page_url or "")
    if youtube_args:
        opts.update(youtube_args)
    node = shutil.which("node")
    if node:
        # 2026 年的 YouTube 提取需要 JS 运行时和官方挑战脚本，否则清晰度列表是残缺的。
        opts["js_runtimes"] = {"node": {"path": node}}
        opts["remote_components"] = ["ejs:github"]
    if extra:
        opts.update(extra)
    return opts


def _with_scheme(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if urlparse(url).scheme or not _HOST_PATH.match(url):
        return url
    return "https://" + url


def _merged_option(video: dict, audio: dict, label: str, duration: float | None = None) -> dict:
    video_size = _size(video, duration)
    audio_size = _size(audio, duration)
    return {
        "format_id": f"{video.get('format_id')}+{audio.get('format_id')}",
        "label": label,
        "ext": "mp4",
        "filesize": None if video_size is None or audio_size is None else video_size + audio_size,
        "height": int(video.get("height") or 0) or None,
        "audio_only": False,
        "needs_merge": True,
    }


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _under_host(host: str, root: str) -> bool:
    return host == root or host.endswith("." + root)


def _youtube_extractor_args(url: str) -> dict:
    host = _hostname(url)
    if not (
        _under_host(host, "youtube.com")
        or _under_host(host, "youtu.be")
        or _under_host(host, "youtube-nocookie.com")
    ):
        return {}
    # 默认的网页客户端在部分网络上会要求「确认不是机器人」。
    # 内嵌播放器仍能读取公开视频，不使用用户的 YouTube Cookie。
    return {
        "extractor_args": {
            "youtube": {
                "player_client": ["web_embedded", "mweb", "android"],
            }
        }
    }


def _bilibili_headers(url: str) -> dict:
    host = _hostname(url)
    if not (_under_host(host, "bilibili.com") or _under_host(host, "b23.tv")):
        return {}
    return {
        "Referer": BILIBILI_REFERER,
        "Origin": "https://www.bilibili.com",
    }


def _cover_needs_proxy(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and _under_host(_hostname(url), "hdslb.com")


def _https_cover(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _public_thumbnail(url) -> str | None:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    if _cover_needs_proxy(url):
        return "/api/cover?url=" + quote(_https_cover(url), safe="")
    return url


def _quality_label(height: int) -> str:
    if height >= 1000:
        return "1080p"
    if height >= 700:
        return "720p"
    if height >= 480:
        return "480p"
    if height > 0:
        return f"{height}p"
    return "原文件"


def _single_info(info):
    if not isinstance(info, dict):
        raise UserFacingError("暂时无法解析这条链接", 502)
    if info.get("_type") == "playlist" or "entries" in info and not info.get("formats"):
        entries = [item for item in info.get("entries") or [] if item]
        if not entries:
            raise UserFacingError("没有可保存的公开清晰度", 422)
        return entries[0]
    return info


def _literal_ip(host: str):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host.isdigit():
            try:
                return ipaddress.ip_address(int(host))
            except ValueError:
                return None
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def _is_public(ip) -> bool:
    return bool(ip.is_global)


def _usable(fmt: dict) -> bool:
    if not fmt.get("format_id"):
        return False
    note = str(fmt.get("format_note") or "").lower()
    protocol = str(fmt.get("protocol") or "")
    if "storyboard" in note or protocol.startswith("mhtml"):
        return False
    return _has_video(fmt) or _audio_only(fmt)


def _direct_container(fmt: dict) -> bool:
    return (fmt.get("ext") or "").lower() in VIDEO_EXTS and fmt.get("vcodec") in (None, "none") and fmt.get(
        "acodec"
    ) in (None, "none")


def _has_video(fmt: dict) -> bool:
    if fmt.get("vcodec") not in (None, "none"):
        return True
    return _direct_container(fmt)


def _has_audio(fmt: dict) -> bool:
    if fmt.get("acodec") not in (None, "none"):
        return True
    return _direct_container(fmt)


def _audio_only(fmt: dict) -> bool:
    if _direct_container(fmt):
        return False
    if (fmt.get("ext") or "").lower() in AUDIO_EXTS and fmt.get("vcodec") in (None, "none"):
        return True
    return fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")


def _add_size(video: dict, audio: dict, duration: float | None = None):
    video_size = _size(video, duration)
    audio_size = _size(audio, duration)
    if video_size is None or audio_size is None:
        return None
    return video_size + audio_size


def _exact_size(fmt: dict):
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    if not value:
        return None
    return int(value)


def _size(fmt: dict, duration: float | None = None):
    exact = _exact_size(fmt)
    if exact:
        return exact
    tbr = fmt.get("tbr")
    if not tbr or not duration:
        return None
    try:
        return int(float(duration) * float(tbr) * (1000 / 8))
    except (TypeError, ValueError):
        return None


def _video_score(fmt: dict):
    # 同一清晰度里，带 Content-Length 的直链优先于码率更高但没有大小的 HLS。
    return (
        int(fmt.get("height") or 0),
        1 if _exact_size(fmt) else 0,
        fmt.get("tbr") or 0,
        1 if fmt.get("ext") == "mp4" else 0,
        _exact_size(fmt) or 0,
    )


def _audio_score(fmt: dict):
    return (
        fmt.get("abr") or fmt.get("tbr") or 0,
        1 if fmt.get("ext") in {"m4a", "mp3"} else 0,
        _size(fmt) or 0,
    )


def _best(items: list[dict], score):
    if not items:
        return None
    return max(items, key=score)


def _option(fmt: dict, *, label: str, needs_merge: bool, duration: float | None = None) -> dict:
    height = fmt.get("height")
    return {
        "format_id": str(fmt.get("format_id")),
        "label": label,
        "ext": fmt.get("ext") or ("m4a" if label == "仅音频" else "mp4"),
        "filesize": _size(fmt, duration),
        "height": int(height) if height else None,
        "audio_only": False,
        "needs_merge": needs_merge,
    }


def _humanize_parse(exc: Exception) -> str:
    text = str(exc).lower()
    name = exc.__class__.__name__.lower()
    if "unsupported" in name or "unsupported url" in text:
        return "平台暂不支持"
    if "not a bot" in text:
        return "YouTube 暂时把这次访问当成了机器人，请稍后再试"
    if "timed out" in text or "timeout" in text or "time out" in text:
        return "解析超时，请稍后再试"
    if any(word in text for word in ("sign in", "login", "cookie", "private video", "members only")):
        return "这个内容需要登录，本站只保存公开视频"
    if "not a valid url" in text or "invalid url" in text:
        return "链接无效"
    return "暂时无法解析这条链接"


def _status_for_parse(exc: Exception) -> int:
    message = _humanize_parse(exc)
    if message in {"平台暂不支持", "链接无效", "这个内容需要登录，本站只保存公开视频"}:
        return 400
    if message == "解析超时，请稍后再试":
        return 504
    return 502


def _humanize_download(exc: Exception) -> str:
    text = str(exc).lower()
    if "max_filesize" in text or "larger than max" in text or "file is larger" in text:
        return "文件超过约 500MB，请换较低清晰度"
    if "timed out" in text or "timeout" in text:
        return "下载超时，请换一条较短的公开视频"
    if "unsupported url" in text:
        return "平台暂不支持"
    return "下载没有完成，请重试"


def _prefer_public_addresses(host, port, family=0, type=0, proto=0, flags=0):
    infos = _original_getaddrinfo(host, port, family, type, proto, flags)
    public = []
    for info in infos:
        address = _literal_ip(str(info[4][0]).split("%", 1)[0])
        if address is not None and _is_public(address):
            public.append(info)
    return public or infos


_original_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = _prefer_public_addresses


def _output_files(directory: Path) -> list[Path]:
    files = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix in {".part", ".ytdl", ".temp"} or path.name.endswith(".part"):
            continue
        files.append(path)
    return files
