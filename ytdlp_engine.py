"""Core yt-dlp wrapper and formats extractor."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yt_dlp

from config import AppConfig, sanitize_path, sanitize_sponsorblock_categories
from ffmpeg_utils import ensure_ffmpeg_in_path, find_ffmpeg

# Initialize FFmpeg in PATH if available
ensure_ffmpeg_in_path()


def format_bytes(size: Optional[int]) -> str:
    """Format bytes into human-readable string."""
    if size is None or size <= 0:
        return "N/A"
    f_size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if f_size < 1024.0 or unit == "TB":
            return f"{f_size:.1f} {unit}"
        f_size /= 1024.0
    return f"{size} B"


def format_duration(seconds: Optional[int]) -> str:
    """Convert integer seconds to MM:SS or HH:MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


@dataclass
class SearchResultItem:
    """A search result item or playlist entry."""

    id: str
    title: str
    url: str
    uploader: str
    duration: Optional[int]
    duration_str: str
    view_count: Optional[int] = None
    upload_date: str = ""
    is_playlist: bool = False
    playlist_count: int = 0
    playlist_index: int = 0

    @property
    def formatted_views(self) -> str:
        if not self.view_count:
            return ""
        if self.view_count >= 1_000_000:
            return f"{self.view_count / 1_000_000:.1f}M views"
        if self.view_count >= 1_000:
            return f"{self.view_count / 1_000:.1f}K views"
        return f"{self.view_count} views"


@dataclass
class FormatOption:
    """A normalized format option for UI display."""

    format_id: str
    format_type: str  # 'video' or 'audio'
    label: str  # e.g., '1080p60 (FHD)', '320 kbps (Best)'
    resolution: str  # e.g., '1920x1080' or '1080p'
    height: int = 0
    fps: Optional[int] = None
    ext: str = ""
    vcodec: str = ""
    acodec: str = ""
    filesize: Optional[int] = None
    filesize_str: str = ""
    tbr: Optional[float] = None
    note: str = ""
    is_special: bool = False  # For "No Video" or "No Audio" options


@dataclass
class ExtractionResult:
    """The result of an extraction operation."""

    url: str
    title: str
    uploader: str
    duration_str: str
    thumbnail: str
    is_playlist: bool = False
    playlist_entries: List[SearchResultItem] = field(default_factory=list)
    video_formats: List[FormatOption] = field(default_factory=list)
    audio_formats: List[FormatOption] = field(default_factory=list)
    raw_info: Dict[str, Any] = field(default_factory=dict)


def is_url(text: str) -> bool:
    """Check if input text is a valid web URL."""
    text = text.strip()
    return bool(re.match(r"^(https?://|www\.|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/)", text))


def is_shorts(url: str, duration: Optional[int] = None, info: Optional[Dict[str, Any]] = None) -> bool:
    """Check if a video URL or metadata corresponds to a YouTube Shorts video."""
    if not url:
        return False
    if bool(re.search(r"(youtube\.com|youtu\.be)/shorts/", url, re.IGNORECASE)):
        return True
    if info:
        if info.get("is_shorts"):
            return True
        webpage_url = info.get("webpage_url") or ""
        if "/shorts/" in webpage_url:
            return True
    return False


def compatible_audio_containers(config: Optional[AppConfig] = None) -> List[str]:
    """Return every audio container the export pipeline can produce."""
    return ["mp3", "m4a", "flac", "opus", "wav"]


def compatible_video_containers(
    config: Optional[AppConfig] = None,
    video_format: Optional[FormatOption] = None,
    audio_format: Optional[FormatOption] = None,
) -> List[str]:
    """Return every video container; incompatible streams are converted when needed."""
    return ["mp4", "mkv", "webm"]


def extract_audio_quality_from_option(option: Optional[FormatOption]) -> str:
    """Extract appropriate audio quality string (e.g. '128', '192', '256', '320') from a FormatOption."""
    if not option or option.format_id in ("none", ""):
        return "256"

    if option.tbr and option.tbr > 0:
        bitrate = int(round(option.tbr))
        if bitrate >= 290:
            return "320"
        elif bitrate >= 220:
            return "256"
        elif bitrate >= 150:
            return "192"
        elif bitrate >= 110:
            return "128"
        elif bitrate > 0:
            return str(bitrate)

    text = f"{option.resolution} {option.label}"
    m = re.search(r"(\d+)\s*(?:k|kbps)", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if val >= 290:
            return "320"
        elif val >= 220:
            return "256"
        elif val >= 150:
            return "192"
        elif val >= 110:
            return "128"
        elif val > 0:
            return str(val)

    return "256"


def extract_audio_container_from_option(option: Optional[FormatOption]) -> str:
    """Extract default audio container (e.g. 'm4a', 'opus', 'mp3', 'flac') from a FormatOption."""
    if not option or option.format_id in ("none", ""):
        return "mp3"

    ext = (option.ext or "").lower().strip()
    acodec = (option.acodec or "").lower().strip()
    label = (option.label or "").lower()

    if ext in ("m4a", "opus", "mp3", "flac", "wav"):
        return ext
    elif ext == "aac":
        return "m4a"
    elif ext in ("webm", "ogg") or "opus" in acodec or "opus" in label:
        return "opus"
    elif "m4a" in label or "aac" in acodec or "aac" in label:
        return "m4a"
    elif "mp3" in label:
        return "mp3"
    elif "flac" in label:
        return "flac"
    elif "wav" in label:
        return "wav"
    return "mp3"


def extract_video_container_from_option(option: Optional[FormatOption]) -> str:
    """Extract default video container (e.g. 'mp4', 'webm', 'mkv') from a FormatOption."""
    if not option or option.format_id in ("none", ""):
        return "mp4"
    ext = (option.ext or "").lower().strip()
    if ext in ("mp4", "webm", "mkv"):
        return ext
    elif ext in ("mov", "flv", "avi", "ts", "m4v"):
        return "mp4"
    return "mp4"


def _codec_matches(codec: str, prefixes: Tuple[str, ...]) -> bool:
    normalized = (codec or "").strip().lower()
    return not normalized or normalized == "none" or normalized.startswith(prefixes)


def _requires_video_conversion(target: str, video_codec: str, audio_codec: str) -> bool:
    """Return whether a selected stream pair must be transcoded for the target container."""
    if target == "mkv":
        return False
    if target == "webm":
        return not (
            _codec_matches(video_codec, ("vp8", "vp9", "av1", "av01"))
            and _codec_matches(audio_codec, ("opus", "vorbis"))
        )
    if target == "mp4":
        return not (
            _codec_matches(video_codec, ("avc", "h264", "hev", "hvc", "h265", "av1", "av01", "vp9"))
            and _codec_matches(audio_codec, ("aac", "mp4a", "mp3", "ac3", "eac3", "alac", "opus"))
        )
    return False


def _subtitle_language_patterns(raw_languages: str, include_auto_generated: bool) -> List[str]:
    """Build yt-dlp subtitle language patterns, including generated language variants."""
    languages = [lang.strip() for lang in (raw_languages or "").split(",") if lang.strip()]
    if not include_auto_generated:
        return languages

    patterns: List[str] = []
    for language in languages:
        if language != "all" and re.fullmatch(r"[A-Za-z]{2,3}", language):
            patterns.append(rf"{re.escape(language)}(?:[-_].*)?")
        else:
            patterns.append(language)
    return patterns


class YtDlpEngine:
    """High-level abstraction over yt-dlp API."""

    @staticmethod
    def search(query: str, max_results: int = 15, config: Optional[AppConfig] = None) -> List[SearchResultItem]:
        """Perform a YouTube keyword search using ytsearch."""
        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        search_query = f"ytsearch{max_results}:{query}"
        results: List[SearchResultItem] = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info or "entries" not in info:
                    return results

                for entry in info["entries"]:
                    if not entry:
                        continue
                    url = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    dur = entry.get("duration")

                    results.append(
                        SearchResultItem(
                            id=str(entry.get("id", "")),
                            title=entry.get("title", "Unknown Title"),
                            url=url,
                            uploader=entry.get("uploader") or entry.get("channel") or "Unknown",
                            duration=dur,
                            duration_str=format_duration(dur),
                            view_count=entry.get("view_count"),
                            upload_date=str(entry.get("upload_date") or ""),
                            is_playlist=entry.get("_type") == "playlist",
                        )
                    )
        except Exception as e:
            print(f"Search error: {e}")
        return results

    @staticmethod
    def test_cookie_setup(browser: str = "none", cookies_file: str = "") -> Dict[str, Any]:
        """Test and diagnose browser cookie extraction or cookies.txt file loading.

        Returns a dict containing:
        - success: bool
        - count: int (number of cookies loaded)
        - has_youtube_auth: bool (whether YouTube/Google session cookies are present)
        - error_type: str ('none', 'file_not_found', 'not_a_file', 'empty_file', 'file_parse_error',
                           'browser_locked', 'app_bound_encryption', 'not_found', 'unknown')
        - message: str (Summary status)
        - recommendation: str (Actionable steps for the user)
        """
        browser_clean = (browser or "none").strip().lower()
        file_clean = sanitize_path(cookies_file)

        # 1. Test cookies file if provided
        if file_clean:
            p = Path(file_clean)
            if not p.exists():
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "file_not_found",
                    "message": f"Cookies file not found: {file_clean}",
                    "recommendation": "Check the file path and verify that the file exists on disk.",
                }
            if not p.is_file():
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "not_a_file",
                    "message": f"Path is not a regular file: {file_clean}",
                    "recommendation": "Provide the full path to a valid cookies.txt file.",
                }
            try:
                ydl_opts = {"cookiefile": str(p), "quiet": True, "no_warnings": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    jar = ydl.cookiejar
                    count = len(jar)
                    yt_cookies = [c.name for c in jar if "youtube.com" in getattr(c, "domain", "") or "google.com" in getattr(c, "domain", "")]
                    has_auth = any(n in ["LOGIN_INFO", "SID", "__Secure-3PSID", "HSID", "SSID", "SAPISID", "APISID"] for n in yt_cookies)
                    if count == 0:
                        return {
                            "success": False,
                            "count": 0,
                            "has_youtube_auth": False,
                            "error_type": "empty_file",
                            "message": "Cookies file exists but contains 0 valid cookies.",
                            "recommendation": "Make sure your browser extension exported cookies in Netscape format.",
                        }
                    auth_note = "Active YouTube login session detected!" if has_auth else "No active YouTube login cookies found in file."
                    return {
                        "success": True,
                        "count": count,
                        "has_youtube_auth": has_auth,
                        "error_type": "none",
                        "message": f"Loaded {count} cookies from file ({len(yt_cookies)} Google/YouTube cookies).",
                        "recommendation": auth_note,
                    }
            except Exception as e:
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "file_parse_error",
                    "message": f"Failed to parse cookies file: {e}",
                    "recommendation": "Ensure the file is in valid Netscape / curl cookies.txt format.",
                }

        # 2. No cookies configured
        if browser_clean == "none" or not browser_clean:
            return {
                "success": True,
                "count": 0,
                "has_youtube_auth": False,
                "error_type": "none",
                "message": "No cookies configured (Anonymous public downloads).",
                "recommendation": "To download member-only, private, or age-gated videos, select a browser or provide a cookies.txt file.",
            }

        # 3. Test browser cookies extraction
        try:
            ydl_opts = {"cookiesfrombrowser": (browser_clean,), "quiet": True, "no_warnings": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                jar = ydl.cookiejar
                count = len(jar)
                yt_cookies = [c.name for c in jar if "youtube.com" in getattr(c, "domain", "") or "google.com" in getattr(c, "domain", "")]
                has_auth = any(n in ["LOGIN_INFO", "SID", "__Secure-3PSID", "HSID", "SSID", "SAPISID", "APISID"] for n in yt_cookies)
                auth_note = "Active YouTube login session verified!" if has_auth else "Cookies extracted, but no active YouTube login session found."
                return {
                    "success": True,
                    "count": count,
                    "has_youtube_auth": has_auth,
                    "error_type": "none",
                    "message": f"Extracted {count} cookies from {browser_clean.capitalize()} ({len(yt_cookies)} YouTube cookies).",
                    "recommendation": auth_note,
                }
        except Exception as e:
            err_str = str(e)
            err_lower = err_str.lower()
            b_name = browser_clean.capitalize()

            if any(k in err_lower for k in ["could not copy", "permission denied", "database is locked", "errno 13"]):
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "browser_locked",
                    "message": f"{b_name} is open and locking its cookie database on Windows.",
                    "recommendation": (
                        f"1. Recommended: Use the 'Get cookies.txt LOCALLY' extension in {b_name} to export a cookies.txt file, and set the path below.\n"
                        f"2. Alternative: Close all {b_name} windows completely and try again."
                    ),
                }
            elif any(k in err_lower for k in ["dpapi", "app-bound", "decrypt", "could not decrypt"]):
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "app_bound_encryption",
                    "message": f"{b_name} uses Windows App-Bound Encryption, preventing direct database access.",
                    "recommendation": (
                        f"Export your cookies to a cookies.txt file using 'Get cookies.txt LOCALLY' (Chrome Web Store) "
                        f"and set the path in 'Custom Cookies.txt Path' below."
                    ),
                }
            elif any(k in err_lower for k in ["not find", "no such file", "not found"]):
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "not_found",
                    "message": f"Could not find {b_name} cookie database or profile.",
                    "recommendation": f"Ensure {b_name} is installed with a default user profile, or export cookies to cookies.txt.",
                }
            else:
                return {
                    "success": False,
                    "count": 0,
                    "has_youtube_auth": False,
                    "error_type": "unknown",
                    "message": f"Cookie extraction error: {err_str[:140]}",
                    "recommendation": "Try exporting cookies to a cookies.txt file instead.",
                }

    @staticmethod
    def extract_info(url: str, config: Optional[AppConfig] = None) -> ExtractionResult:
        """Extract full metadata and available video/audio formats for a URL."""
        ydl_opts: Dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
            "remote_components": ["ejs:github"],
            "extractor_args": {
                "youtube": {
                    "player_client": ["web_embedded", "default", "mweb"],
                    "player_skip": ["configs"],
                }
            },
        }
        if config:
            clean_cookie_file = sanitize_path(config.cookies_file)
            if clean_cookie_file and Path(clean_cookie_file).exists():
                ydl_opts["cookiefile"] = clean_cookie_file
            elif config.browser_cookies and config.browser_cookies != "none":
                ydl_opts["cookiesfrombrowser"] = (config.browser_cookies,)
            if config.proxy:
                ydl_opts["proxy"] = config.proxy
            if config.geo_bypass:
                ydl_opts["geo_bypass"] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            # If cookies failed (e.g. Chrome/Edge is open and locks SQLite database on Windows), retry without cookies
            if "cookiesfrombrowser" in ydl_opts or "cookiefile" in ydl_opts:
                opts_no_cookies = dict(ydl_opts)
                opts_no_cookies.pop("cookiesfrombrowser", None)
                opts_no_cookies.pop("cookiefile", None)
                try:
                    with yt_dlp.YoutubeDL(opts_no_cookies) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception as retry_err:
                    raise retry_err
            else:
                raise e

        if not info:
            raise ValueError("Could not extract media metadata from URL")

        # Check if it's a playlist
        is_playlist = info.get("_type") == "playlist" or "entries" in info
        playlist_items: List[SearchResultItem] = []

        if is_playlist:
            raw_entries = info.get("entries") or []
            if not isinstance(raw_entries, list):
                try:
                    raw_entries = list(raw_entries)
                except Exception:
                    raw_entries = []

            for idx, entry in enumerate(raw_entries):
                if not entry or not isinstance(entry, dict):
                    continue
                dur = entry.get("duration")
                raw_url = entry.get("url") or entry.get("webpage_url") or ""
                vid_id = str(entry.get("id") or "")
                if raw_url and (raw_url.startswith("http://") or raw_url.startswith("https://")):
                    e_url = raw_url
                elif vid_id:
                    e_url = f"https://www.youtube.com/watch?v={vid_id}"
                else:
                    e_url = raw_url

                title = entry.get("title") or f"Track {len(playlist_items) + 1}"
                uploader = entry.get("uploader") or entry.get("channel") or info.get("uploader") or info.get("channel") or "Unknown"

                playlist_items.append(
                    SearchResultItem(
                        id=vid_id,
                        title=title,
                        url=e_url,
                        uploader=uploader,
                        duration=dur,
                        duration_str=format_duration(dur),
                        view_count=entry.get("view_count"),
                        playlist_index=len(playlist_items) + 1,
                    )
                )

            # Use first video for format extraction template
            formats_source = raw_entries[0] if (raw_entries and isinstance(raw_entries[0], dict)) else info
        else:
            formats_source = info

        if is_playlist:
            # For playlists (extracted flatly for responsive UX), provide full curated video & audio formats
            video_formats, audio_formats = YtDlpEngine._get_playlist_fallback_formats()
        else:
            raw_formats = formats_source.get("formats")
            if not raw_formats:
                # If formats list is empty (direct URL or single format extractor), use info as single format
                raw_formats = [
                    {
                        "format_id": formats_source.get("format_id") or "direct",
                        "url": formats_source.get("url"),
                        "ext": formats_source.get("ext") or "mp4",
                        "vcodec": formats_source.get("vcodec"),
                        "acodec": formats_source.get("acodec"),
                        "height": formats_source.get("height"),
                        "width": formats_source.get("width"),
                        "fps": formats_source.get("fps"),
                        "tbr": formats_source.get("tbr"),
                        "abr": formats_source.get("abr"),
                        "filesize": formats_source.get("filesize") or formats_source.get("filesize_approx"),
                        "format_note": formats_source.get("format_note") or "Direct Stream",
                    }
                ]
            video_formats, audio_formats = YtDlpEngine._parse_formats(raw_formats)

        dur_int = info.get("duration")
        if is_playlist and dur_int is None and playlist_items:
            known_durs = [it.duration for it in playlist_items if it.duration and it.duration > 0]
            dur_int = sum(known_durs) if known_durs else None

        return ExtractionResult(
            url=url,
            title=info.get("title", "Untitled Media"),
            uploader=info.get("uploader") or info.get("channel") or "Unknown",
            duration_str=format_duration(dur_int),
            thumbnail=info.get("thumbnail", ""),
            is_playlist=is_playlist,
            playlist_entries=playlist_items,
            video_formats=video_formats,
            audio_formats=audio_formats,
            raw_info=info,
        )

    @staticmethod
    def _get_playlist_fallback_formats() -> Tuple[List[FormatOption], List[FormatOption]]:
        """Return standard curated video and audio formats for playlist batch operations."""
        video_opts = [
            FormatOption(format_id="none", format_type="video", label="[No Video - Audio Only]", resolution="Audio Only", note="Extract only selected audio stream", is_special=True),
            FormatOption(format_id="bestvideo", format_type="video", label="[Best Video Quality] (Auto)", resolution="Best Available", note="Highest resolution available", is_special=True, height=2160, tbr=8000),
            FormatOption(format_id="bestvideo[height<=2160]", format_type="video", label="2160p (4K UHD)", resolution="2160p", height=2160, ext="mp4", tbr=20000, note="4K Ultra HD, ~20 Mbps"),
            FormatOption(format_id="bestvideo[height<=1440]", format_type="video", label="1440p (2K QHD)", resolution="1440p", height=1440, ext="mp4", tbr=10000, note="2K Quad HD, ~10 Mbps"),
            FormatOption(format_id="bestvideo[height<=1080]", format_type="video", label="1080p (FHD)", resolution="1080p", height=1080, ext="mp4", tbr=5000, note="Full HD, ~5 Mbps"),
            FormatOption(format_id="bestvideo[height<=720]", format_type="video", label="720p (HD)", resolution="720p", height=720, ext="mp4", tbr=2500, note="High Definition, ~2.5 Mbps"),
            FormatOption(format_id="bestvideo[height<=480]", format_type="video", label="480p (SD)", resolution="480p", height=480, ext="mp4", tbr=1000, note="Standard Def, ~1 Mbps"),
            FormatOption(format_id="bestvideo[height<=360]", format_type="video", label="360p (Small)", resolution="360p", height=360, ext="mp4", tbr=500, note="Small size, ~500 kbps"),
        ]
        audio_opts = [
            FormatOption(format_id="none", format_type="audio", label="[No Audio - Video Only]", resolution="Muted", note="Download video without audio", is_special=True),
            FormatOption(format_id="bestaudio", format_type="audio", label="[Best Audio Quality] (Auto)", resolution="Best Available", note="Highest bitrate available", is_special=True, tbr=160),
            FormatOption(format_id="bestaudio", format_type="audio", label="320 kbps [MP3/AAC] (Best)", resolution="320k", ext="mp3", tbr=320, note="High Fidelity 320k"),
            FormatOption(format_id="bestaudio", format_type="audio", label="256 kbps [MP3/AAC] (High)", resolution="256k", ext="mp3", tbr=256, note="Standard High 256k"),
            FormatOption(format_id="bestaudio", format_type="audio", label="192 kbps [MP3/AAC] (Medium)", resolution="192k", ext="mp3", tbr=192, note="Medium 192k"),
            FormatOption(format_id="bestaudio", format_type="audio", label="128 kbps [MP3/AAC] (Normal)", resolution="128k", ext="mp3", tbr=128, note="Standard 128k"),
        ]
        return video_opts, audio_opts

    @staticmethod
    def estimate_format_bitrates(
        video_fmt: Optional[FormatOption],
        audio_fmt: Optional[FormatOption],
        audio_quality: str = "256",
    ) -> Tuple[float, float, float]:
        """Return estimated (video_kbps, audio_kbps, total_kbps)."""
        video_kbps = 0.0
        audio_kbps = 0.0

        # Video bitrate estimation
        if video_fmt and video_fmt.format_id != "none":
            if video_fmt.tbr and video_fmt.tbr > 0:
                video_kbps = float(video_fmt.tbr)
            elif video_fmt.height:
                h = video_fmt.height
                if h >= 2160:
                    video_kbps = 20000.0
                elif h >= 1440:
                    video_kbps = 10000.0
                elif h >= 1080:
                    video_kbps = 5500.0
                elif h >= 720:
                    video_kbps = 2500.0
                elif h >= 480:
                    video_kbps = 1000.0
                elif h >= 360:
                    video_kbps = 500.0
                else:
                    video_kbps = 350.0
            elif video_fmt.format_id == "bestvideo":
                video_kbps = 5000.0
            else:
                video_kbps = 2500.0

        # Audio bitrate estimation
        if audio_fmt and audio_fmt.format_id != "none":
            if video_fmt and video_fmt.format_id == "none":
                # Audio only mode: use audio quality setting
                if audio_quality == "V0":
                    audio_kbps = 245.0
                elif audio_quality and audio_quality.isdigit():
                    audio_kbps = float(audio_quality)
                elif audio_fmt.tbr and audio_fmt.tbr > 0:
                    audio_kbps = float(audio_fmt.tbr)
                else:
                    audio_kbps = 256.0
            else:
                if audio_fmt.tbr and audio_fmt.tbr > 0:
                    audio_kbps = float(audio_fmt.tbr)
                elif audio_fmt.format_id == "bestaudio":
                    audio_kbps = 160.0
                else:
                    m = re.search(r"(\d+)\s*k", str(audio_fmt.label or ""), re.IGNORECASE)
                    if m:
                        audio_kbps = float(m.group(1))
                    else:
                        audio_kbps = 128.0

        total_kbps = video_kbps + audio_kbps
        return video_kbps, audio_kbps, total_kbps

    @staticmethod
    def estimate_item_size(
        duration_sec: Optional[int],
        video_fmt: Optional[FormatOption],
        audio_fmt: Optional[FormatOption],
        audio_quality: str = "256",
        fallback_duration: int = 210,
    ) -> int:
        """Estimate byte size for a single media item based on duration and selected stream bitrates."""
        dur = duration_sec if (duration_sec is not None and duration_sec > 0) else fallback_duration
        _, _, total_kbps = YtDlpEngine.estimate_format_bitrates(video_fmt, audio_fmt, audio_quality)
        # (kbps * 1000 / 8) * seconds = bytes
        estimated_bytes = int((total_kbps * 125.0) * dur)
        return max(1024, estimated_bytes)

    @staticmethod
    def estimate_playlist_size(
        items: List[SearchResultItem],
        video_fmt: Optional[FormatOption],
        audio_fmt: Optional[FormatOption],
        audio_quality: str = "256",
    ) -> Tuple[int, int]:
        """Estimate total download size (bytes) and total duration (seconds) for a list of playlist items."""
        if not items:
            return 0, 0

        # Calculate average duration of items with known duration
        known_durs = [it.duration for it in items if it.duration and it.duration > 0]
        avg_dur = int(sum(known_durs) / len(known_durs)) if known_durs else 210

        total_bytes = 0
        total_seconds = 0
        for item in items:
            dur = item.duration if (item.duration and item.duration > 0) else avg_dur
            total_seconds += dur
            total_bytes += YtDlpEngine.estimate_item_size(
                item.duration,
                video_fmt,
                audio_fmt,
                audio_quality=audio_quality,
                fallback_duration=avg_dur,
            )

        return total_bytes, total_seconds

    @staticmethod
    def _extract_height(f: Dict[str, Any]) -> int:
        """Robustly extract video height integer from format metadata dictionary."""
        h = f.get("height")
        if h and isinstance(h, int) and h > 0:
            return h
        res = str(f.get("resolution") or "")
        m = re.search(r"(\d+)\s*[xX]\s*(\d+)", res)
        if m:
            w_val, h_val = int(m.group(1)), int(m.group(2))
            return min(w_val, h_val)
        for key in ["resolution", "format_note", "format", "format_id"]:
            val = str(f.get(key) or "")
            m2 = re.search(r"(\d{3,4})p", val, re.IGNORECASE)
            if m2:
                return int(m2.group(1))
            if re.search(r"\b4k\b", val, re.IGNORECASE):
                return 2160
            if re.search(r"\b2k\b", val, re.IGNORECASE):
                return 1440
        return 0

    @staticmethod
    def _parse_formats(formats: List[Dict[str, Any]]) -> Tuple[List[FormatOption], List[FormatOption]]:
        """Parse raw yt-dlp format dictionaries into curated video & audio options supporting all sites."""
        video_opts: List[FormatOption] = []
        audio_opts: List[FormatOption] = []

        # 1. Special "No Video" option for video column
        video_opts.append(
            FormatOption(
                format_id="none",
                format_type="video",
                label="[No Video - Audio Only]",
                resolution="Audio Only",
                note="Extract only selected audio stream",
                is_special=True,
            )
        )

        # 2. Special "Best Video" preset
        video_opts.append(
            FormatOption(
                format_id="bestvideo",
                format_type="video",
                label="[Best Video Quality] (Auto)",
                resolution="Best Available",
                note="Highest resolution & framerate available",
                is_special=True,
            )
        )

        # 3. Special "No Audio" option for audio column
        audio_opts.append(
            FormatOption(
                format_id="none",
                format_type="audio",
                label="[No Audio - Video Only]",
                resolution="Muted",
                note="Download video stream without audio",
                is_special=True,
            )
        )

        # 4. Special "Best Audio" preset
        audio_opts.append(
            FormatOption(
                format_id="bestaudio",
                format_type="audio",
                label="[Best Audio Quality] (Auto)",
                resolution="Best Available",
                note="Highest bitrate audio available",
                is_special=True,
            )
        )

        if not formats:
            return video_opts, audio_opts

        seen_video_res: set = set()
        seen_audio_abr: set = set()
        seen_format_ids: set = set()

        # Sort raw formats by height desc, tbr desc, abr desc
        sorted_formats = sorted(
            formats,
            key=lambda f: (
                YtDlpEngine._extract_height(f),
                f.get("tbr") or 0,
                f.get("abr") or 0,
                f.get("filesize") or f.get("filesize_approx") or 0,
            ),
            reverse=True,
        )

        for f in sorted_formats:
            fid = str(f.get("format_id", "")).strip()
            if not fid or fid in seen_format_ids:
                continue

            vcodec = str(f.get("vcodec") or "none").lower()
            acodec = str(f.get("acodec") or "none").lower()
            height = YtDlpEngine._extract_height(f)
            fps = f.get("fps")
            ext = str(f.get("ext") or "").lower()
            tbr = f.get("tbr")
            abr = f.get("abr")
            size = f.get("filesize") or f.get("filesize_approx")

            # Determine audio/video flags
            is_audio_ext = ext in ["mp3", "m4a", "flac", "opus", "wav", "aac", "ogg"]
            is_video_ext = ext in ["mp4", "mkv", "webm", "mov", "flv", "avi", "ts", "m4v"]

            is_video = (vcodec != "none" and vcodec != "") or (height > 0) or (is_video_ext and not is_audio_ext)
            is_audio = (acodec != "none" and acodec != "") or is_audio_ext or ("audio" in fid.lower())

            # 1. Video format candidate
            if is_video and not (is_audio_ext and vcodec == "none"):
                seen_format_ids.add(fid)
                fps_str = f"{fps}fps" if fps and fps > 30 else ""
                codec_short = vcodec.split(".")[0] if vcodec != "none" else (ext.upper() if ext else "Video")

                # Avoid excessive duplicates of exact same resolution
                if (height, fps if fps and fps > 30 else 30, ext) in seen_video_res and len(seen_video_res) > 8:
                    continue
                seen_video_res.add((height, fps if fps and fps > 30 else 30, ext))

                quality_tag = ""
                if height >= 2160:
                    quality_tag = " (4K)"
                elif height >= 1440:
                    quality_tag = " (2K)"
                elif height >= 1080:
                    quality_tag = " (FHD)"
                elif height >= 720:
                    quality_tag = " (HD)"
                elif height > 0:
                    quality_tag = f" ({height}p)"

                fps_badge = f" {fps_str}" if fps_str else ""
                res_label = f"{height}p" if height > 0 else (f.get("format_note") or f.get("resolution") or fid)
                ext_badge = f" [{ext.upper()}]" if ext else ""
                muxed_badge = " (Video+Audio)" if is_audio and acodec != "none" else ""
                label = f"{res_label}{fps_badge}{quality_tag}{ext_badge}{muxed_badge}"

                video_opts.append(
                    FormatOption(
                        format_id=fid,
                        format_type="video",
                        label=label,
                        resolution=f"{height}p" if height > 0 else res_label,
                        height=height,
                        fps=fps,
                        ext=ext,
                        vcodec=codec_short,
                        acodec=acodec if acodec != "none" else "none",
                        filesize=size,
                        filesize_str=format_bytes(size),
                        tbr=tbr,
                        note=f"{codec_short}, ~{format_bytes(size)}",
                    )
                )

            # 2. Audio format candidate (audio-only streams or distinct audio tracks)
            if is_audio and (vcodec == "none" or is_audio_ext or not is_video):
                seen_format_ids.add(fid)
                bitrate_val = int(abr) if abr else (int(tbr) if tbr else 0)
                abr_key = (round(bitrate_val / 16) * 16 if bitrate_val > 0 else 0, ext)
                if abr_key in seen_audio_abr and len(seen_audio_abr) > 6:
                    continue
                seen_audio_abr.add(abr_key)

                codec_short = acodec.split(".")[0] if acodec != "none" else (ext.upper() if ext else "Audio")
                bitrate_str = f"{bitrate_val} kbps" if bitrate_val > 0 else (f.get("format_note") or "Audio")
                ext_str = f" [{ext.upper()}]" if ext else ""
                label = f"{bitrate_str}{ext_str} ({codec_short})"

                audio_opts.append(
                    FormatOption(
                        format_id=fid,
                        format_type="audio",
                        label=label,
                        resolution=f"{bitrate_val}k" if bitrate_val > 0 else "audio",
                        ext=ext,
                        vcodec="none",
                        acodec=codec_short,
                        filesize=size,
                        filesize_str=format_bytes(size),
                        tbr=tbr,
                        note=f"{codec_short}, ~{format_bytes(size)}",
                    )
                )

        return video_opts, audio_opts

    @staticmethod
    def resolve_output_filepath(base_filename: str, container: str = "mp4", is_audio_only: bool = False) -> str:
        """Resolve actual output filepath on disk handling container and postprocessor renamings."""
        p = Path(base_filename)
        if p.exists() and p.is_file():
            return str(p)

        stem = p.parent / p.stem
        # Check explicit container target
        if container:
            cand = stem.with_suffix(f".{container.lower()}")
            if cand.exists():
                return str(cand)

        # Check standard video/audio extensions
        exts = ["mp3", "m4a", "flac", "opus", "wav", "aac"] if is_audio_only else ["mp4", "mkv", "webm", "mov"]
        for ext in exts:
            cand = stem.with_suffix(f".{ext}")
            if cand.exists():
                return str(cand)

        return base_filename

    @staticmethod
    def build_download_options(
        config: AppConfig,
        video_format_id: str,
        audio_format_id: str,
        target_container: str = "mp4",
        audio_quality: str = "256",
        progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
        postprocessor_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
        logger: Optional[Any] = None,
        video_ext: str = "",
        video_codec: str = "",
        audio_ext: str = "",
        audio_codec: str = "",
    ) -> Dict[str, Any]:
        """Construct full yt-dlp configuration dictionary with network resiliency and error safety."""

        is_audio_only = (video_format_id == "none")

        # Format string builder supporting both separated (YouTube) and muxed/single-stream (Vimeo, Twitter, TikTok, etc.)
        if is_audio_only:
            # Audio only
            if audio_format_id in ("bestaudio", "none", ""):
                format_spec = "bestaudio/best"
            else:
                format_spec = audio_format_id
        elif audio_format_id in ("none", ""):
            # Video only requested
            if video_format_id == "bestvideo":
                format_spec = "bestvideo/best"
            else:
                format_spec = f"{video_format_id}/best"
        else:
            # Video + Audio requested
            if video_format_id == "bestvideo" and audio_format_id == "bestaudio":
                if target_container.lower() == "mp4":
                    format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best"
                elif target_container.lower() == "webm":
                    format_spec = "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/bestvideo+bestaudio/best"
                else:
                    format_spec = "bestvideo+bestaudio/best"
            elif video_format_id == "bestvideo":
                format_spec = f"bestvideo+{audio_format_id}/best"
            elif audio_format_id == "bestaudio":
                format_spec = f"{video_format_id}+bestaudio/{video_format_id}/best"
            else:
                format_spec = f"{video_format_id}+{audio_format_id}/best"

        # Outtmpl
        download_path = Path(config.download_dir).expanduser()
        download_path.mkdir(parents=True, exist_ok=True)
        outtmpl = str(download_path / config.filename_template)

        ydl_opts: Dict[str, Any] = {
            "format": format_spec,
            "outtmpl": outtmpl,
            "windowsfilenames": True,
            # Network resiliency & auto-resume on interruption
            "continuedl": config.continuedl,
            "retries": config.retries,
            "fragment_retries": config.fragment_retries,
            "socket_timeout": 30,
            # Disable ignoreerrors so fatal stream errors are raised and handled properly
            "ignoreerrors": False,
            "no_color": True,
            "quiet": True,
            "no_warnings": True,
            "remote_components": ["ejs:github"],
            "extractor_args": {
                "youtube": {
                    "player_client": ["web_embedded", "default", "mweb"],
                    "player_skip": ["configs"],
                }
            },
        }

        # Rate limit
        if config.rate_limit and config.rate_limit != "0":
            ydl_opts["ratelimit"] = config.rate_limit

        # Cookies & Auth: prioritize custom cookies_file if it exists on disk
        clean_cookie_file = sanitize_path(config.cookies_file)
        if clean_cookie_file and Path(clean_cookie_file).exists():
            ydl_opts["cookiefile"] = clean_cookie_file
        elif config.browser_cookies and config.browser_cookies != "none":
            ydl_opts["cookiesfrombrowser"] = (config.browser_cookies,)

        # FFmpeg binary location
        ffmpeg_bin = find_ffmpeg(getattr(config, "ffmpeg_location", None))
        if ffmpeg_bin:
            ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)

        chosen_container = target_container.lower()
        requires_conversion = False

        # Target container merging for video
        if not is_audio_only and target_container:
            valid_video_containers = ["mp4", "mkv", "webm"]
            chosen_container = chosen_container if chosen_container in valid_video_containers else "mp4"
            requires_conversion = _requires_video_conversion(chosen_container, video_codec, audio_codec)
            ydl_opts["merge_output_format"] = "mkv" if requires_conversion else chosen_container

        # Post processors list
        postprocessors: List[Dict[str, Any]] = []

        sponsorblock_categories: List[str] = []
        if config.remove_sponsor_segments:
            sponsorblock_categories = sanitize_sponsorblock_categories(config.sponsorblock_categories).split(",")
            postprocessors.append(
                {
                    "key": "SponsorBlock",
                    "categories": sponsorblock_categories,
                    "api": "https://sponsor.ajay.app",
                    "when": "after_filter",
                }
            )

        # If audio only, extract audio to container
        if is_audio_only:
            audio_ext = target_container.lower() if target_container.lower() in ["mp3", "m4a", "flac", "opus", "wav", "aac"] else "mp3"
            quality_val = "0" if audio_quality in ("V0", "0", "v0") else (audio_quality or "256")
            postprocessors.append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_ext,
                    "preferredquality": quality_val,
                }
            )

        # Always honor the selected video container. Remux is fast; conversion is only
        # used when the selected codecs cannot be stored in that container.
        if not is_audio_only:
            if requires_conversion:
                postprocessors.append({"key": "FFmpegVideoConvertor", "preferedformat": chosen_container})
            else:
                postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": chosen_container})

        # Subtitles (skip entirely for audio-only downloads)
        if config.download_subtitles and not is_audio_only:
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = config.auto_generated_subtitles
            ydl_opts["subtitleslangs"] = _subtitle_language_patterns(
                config.subtitle_langs,
                config.auto_generated_subtitles,
            )
            if config.subtitle_mode in ("embed", "both") and not is_audio_only:
                if chosen_container in ("mp4", "webm"):
                    postprocessors.append(
                        {
                            "key": "FFmpegSubtitlesConvertor",
                            "format": "vtt" if chosen_container == "webm" else "srt",
                            "when": "before_dl",
                        }
                    )
                postprocessors.append(
                    {
                        "key": "FFmpegEmbedSubtitle",
                        "already_have_subtitle": config.subtitle_mode == "both",
                    }
                )

        if sponsorblock_categories:
            postprocessors.append(
                {
                    "key": "ModifyChapters",
                    "remove_chapters_patterns": [],
                    "remove_sponsor_segments": sponsorblock_categories,
                    "remove_ranges": [],
                    "sponsorblock_chapter_title": "[SponsorBlock]: %(category_names)l",
                    "force_keyframes": False,
                }
            )

        # Metadata must run after extraction/conversion, when the final container is known.
        if config.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_chapters": config.embed_chapters})

        # Thumbnails
        if config.download_thumbnail:
            ydl_opts["writethumbnail"] = True
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            thumbnail_container = chosen_container if not is_audio_only else target_container.lower()
            thumbnail_embed_supported = thumbnail_container in ("mp3", "m4a", "flac", "opus", "mp4", "mkv")
            if config.thumbnail_mode == "embed" and thumbnail_embed_supported:
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        # Split chapters
        if config.split_chapters and not is_audio_only:
            postprocessors.append({"key": "FFmpegSplitChapters"})

        if postprocessors:
            ydl_opts["postprocessors"] = postprocessors

        # Proxy & Geo-bypass
        if config.proxy:
            ydl_opts["proxy"] = config.proxy
        if config.geo_bypass:
            ydl_opts["geo_bypass"] = True

        # Hooks
        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]
        if postprocessor_hook:
            ydl_opts["postprocessor_hooks"] = [postprocessor_hook]
        if logger:
            ydl_opts["logger"] = logger

        return ydl_opts
