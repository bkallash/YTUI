"""yt-dlp integration: search, metadata extraction, cookie diagnostics, and download options.

yt_dlp is imported inside functions because importing it costs ~0.4s; the app warms it up in the
background after the UI is visible.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import AppConfig, parse_rate_limit, sanitize_path, sanitize_sponsorblock_categories
from .ffmpeg_utils import find_ffmpeg
from .formats import (
    AUDIO_CONTAINERS,
    VIDEO_CONTAINERS,
    ExtractionResult,
    SearchResultItem,
    format_duration,
    parse_formats,
    playlist_preset_formats,
    requires_video_conversion,
)

# Verified YouTube player client fallback chains to avoid HTTP 403 Forbidden
YOUTUBE_CLIENT_FALLBACKS: List[List[str]] = [
    ["web_embedded", "android", "mweb"],
    ["android", "mweb"],
    ["tv_simply", "tv_downgraded", "android"],
    ["mweb", "android"],
    ["web", "android"],
]

LANG_CODE_RE = re.compile(r"[A-Za-z]{2,3}")
_AUTH_COOKIES = {"LOGIN_INFO", "SID", "__Secure-3PSID", "HSID", "SSID", "SAPISID", "APISID"}
_COOKIE_ERROR_HINTS = ("cookie", "dpapi", "decrypt", "keyring", "database is locked", "could not copy")
_CLIENT_ERROR_HINTS = ("403", "forbidden", "sign in", "requested format is not available", "not available on this app")


def is_cookie_error(err: BaseException) -> bool:
    return any(k in str(err).lower() for k in _COOKIE_ERROR_HINTS)


def is_client_error(err: BaseException) -> bool:
    """Errors that another YouTube player client may not hit."""
    return any(k in str(err).lower() for k in _CLIENT_ERROR_HINTS)


def _short_reason(err: BaseException) -> str:
    text = str(err)
    if "403" in text or "forbidden" in text.lower():
        return "HTTP 403 Forbidden"
    return text.replace("ERROR: ", "")[:100]


def _subtitle_language_patterns(raw_languages: str, include_auto_generated: bool) -> List[str]:
    """Build yt-dlp subtitle language patterns, including generated language variants."""
    languages = [lang.strip() for lang in (raw_languages or "").split(",") if lang.strip()]
    if not include_auto_generated:
        return languages
    return [
        rf"{re.escape(lang)}(?:[-_].*)?" if lang != "all" and LANG_CODE_RE.fullmatch(lang) else lang
        for lang in languages
    ]


def _cookie_result(success: bool, error_type: str, message: str, recommendation: str, count: int = 0, has_auth: bool = False) -> Dict[str, Any]:
    return {
        "success": success,
        "count": count,
        "has_youtube_auth": has_auth,
        "error_type": error_type,
        "message": message,
        "recommendation": recommendation,
    }


def _jar_summary(jar: Any) -> tuple:
    """Return (cookie_count, youtube_cookie_count, has_login_session) for a cookie jar."""
    yt_names = [c.name for c in jar if "youtube.com" in getattr(c, "domain", "") or "google.com" in getattr(c, "domain", "")]
    return len(jar), len(yt_names), any(n in _AUTH_COOKIES for n in yt_names)


class YtDlpEngine:
    """Namespace for yt-dlp operations."""

    YOUTUBE_CLIENT_FALLBACKS = YOUTUBE_CLIENT_FALLBACKS

    @staticmethod
    def base_options(config: Optional[AppConfig]) -> Dict[str, Any]:
        """Options shared by search, extraction, and downloads (auth, proxy, client selection)."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "remote_components": ["ejs:github"],
            "extractor_args": {"youtube": {"player_client": YOUTUBE_CLIENT_FALLBACKS[0]}},
        }
        if config:
            if config.cookies_file and Path(config.cookies_file).is_file():
                opts["cookiefile"] = config.cookies_file
            elif config.browser_cookies != "none":
                opts["cookiesfrombrowser"] = (config.browser_cookies,)
            if config.proxy:
                opts["proxy"] = config.proxy
            opts["geo_bypass"] = config.geo_bypass
        return opts

    @staticmethod
    def run_with_fallbacks(
        opts: Dict[str, Any],
        action: Callable[[Any], Any],
        should_stop: Callable[[], bool] = lambda: False,
        on_retry: Callable[[str], None] = lambda msg: None,
    ) -> Any:
        """Run action(ydl), retrying without cookies on cookie errors and with other YouTube clients
        on 403/sign-in errors. Re-raises the last error when every attempt fails."""
        import yt_dlp

        def attempt(attempt_opts: Dict[str, Any]) -> Any:
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                return action(ydl)

        try:
            return attempt(opts)
        except Exception as err:
            last_error = err

        if not should_stop() and ("cookiefile" in opts or "cookiesfrombrowser" in opts) and is_cookie_error(last_error):
            on_retry("Browser cookies are locked or unreadable. Retrying without cookies...")
            opts = {k: v for k, v in opts.items() if k not in ("cookiefile", "cookiesfrombrowser")}
            try:
                return attempt(opts)
            except Exception as err:
                last_error = err

        if is_client_error(last_error):
            for clients in YOUTUBE_CLIENT_FALLBACKS[1:]:
                if should_stop():
                    break
                on_retry(f"{_short_reason(last_error)}. Retrying with {', '.join(clients)} client fallback...")
                try:
                    return attempt({**opts, "extractor_args": {"youtube": {"player_client": clients}}})
                except Exception as err:
                    last_error = err
        raise last_error

    @staticmethod
    def search(query: str, max_results: int = 15, config: Optional[AppConfig] = None) -> List[SearchResultItem]:
        """YouTube keyword search. Raises on network/extractor errors."""
        opts = {**YtDlpEngine.base_options(config), "extract_flat": "in_playlist", "skip_download": True}
        info = YtDlpEngine.run_with_fallbacks(opts, lambda ydl: ydl.extract_info(f"ytsearch{max_results}:{query}", download=False))
        results: List[SearchResultItem] = []
        for entry in (info or {}).get("entries") or []:
            if not entry:
                continue
            dur = entry.get("duration")
            results.append(
                SearchResultItem(
                    id=str(entry.get("id", "")),
                    title=entry.get("title") or "Unknown Title",
                    url=entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
                    uploader=entry.get("uploader") or entry.get("channel") or "Unknown",
                    duration=dur,
                    duration_str=format_duration(dur),
                    view_count=entry.get("view_count"),
                    upload_date=str(entry.get("upload_date") or ""),
                    is_playlist=entry.get("_type") == "playlist",
                )
            )
        return results

    @staticmethod
    def test_cookie_setup(browser: str = "none", cookies_file: str = "") -> Dict[str, Any]:
        """Diagnose browser cookie extraction or cookies.txt loading.

        Returns a dict with success, count, has_youtube_auth, error_type ('none', 'file_not_found',
        'not_a_file', 'empty_file', 'file_parse_error', 'browser_locked', 'app_bound_encryption',
        'not_found', 'unknown'), message and recommendation.
        """
        import yt_dlp

        browser_clean = (browser or "none").strip().lower()
        file_clean = sanitize_path(cookies_file)

        if file_clean:
            p = Path(file_clean)
            if not p.exists():
                return _cookie_result(False, "file_not_found", f"Cookies file not found: {file_clean}", "Check the file path and verify that the file exists on disk.")
            if not p.is_file():
                return _cookie_result(False, "not_a_file", f"Path is not a regular file: {file_clean}", "Provide the full path to a valid cookies.txt file.")
            try:
                with yt_dlp.YoutubeDL({"cookiefile": str(p), "quiet": True, "no_warnings": True}) as ydl:
                    count, yt_count, has_auth = _jar_summary(ydl.cookiejar)
            except Exception as e:
                return _cookie_result(False, "file_parse_error", f"Failed to parse cookies file: {e}", "Ensure the file is in valid Netscape / curl cookies.txt format.")
            if count == 0:
                return _cookie_result(False, "empty_file", "Cookies file exists but contains 0 valid cookies.", "Make sure your browser extension exported cookies in Netscape format.")
            note = "Active YouTube login session detected!" if has_auth else "No active YouTube login cookies found in file."
            return _cookie_result(True, "none", f"Loaded {count} cookies from file ({yt_count} Google/YouTube cookies).", note, count, has_auth)

        if browser_clean in ("none", ""):
            return _cookie_result(
                True, "none", "No cookies configured (Anonymous public downloads).",
                "To download member-only, private, or age-gated videos, select a browser or provide a cookies.txt file.",
            )

        name = browser_clean.capitalize()
        try:
            with yt_dlp.YoutubeDL({"cookiesfrombrowser": (browser_clean,), "quiet": True, "no_warnings": True}) as ydl:
                count, yt_count, has_auth = _jar_summary(ydl.cookiejar)
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("could not copy", "permission denied", "database is locked", "errno 13")):
                return _cookie_result(
                    False, "browser_locked", f"{name} is open and locking its cookie database on Windows.",
                    f"1. Recommended: Use the 'Get cookies.txt LOCALLY' extension in {name} to export a cookies.txt file, and set the path below.\n"
                    f"2. Alternative: Close all {name} windows completely and try again.",
                )
            if any(k in err for k in ("dpapi", "app-bound", "decrypt")):
                return _cookie_result(
                    False, "app_bound_encryption", f"{name} uses Windows App-Bound Encryption, preventing direct database access.",
                    "Export your cookies to a cookies.txt file using 'Get cookies.txt LOCALLY' (Chrome Web Store) "
                    "and set the path in 'Custom Cookies.txt Path' below.",
                )
            if any(k in err for k in ("not find", "no such file", "not found")):
                return _cookie_result(
                    False, "not_found", f"Could not find {name} cookie database or profile.",
                    f"Ensure {name} is installed with a default user profile, or export cookies to cookies.txt.",
                )
            return _cookie_result(False, "unknown", f"Cookie extraction error: {str(e)[:140]}", "Try exporting cookies to a cookies.txt file instead.")
        note = "Active YouTube login session verified!" if has_auth else "Cookies extracted, but no active YouTube login session found."
        return _cookie_result(True, "none", f"Extracted {count} cookies from {name} ({yt_count} YouTube cookies).", note, count, has_auth)

    @staticmethod
    def extract_info(url: str, config: Optional[AppConfig] = None) -> ExtractionResult:
        """Extract metadata and selectable formats for a video or (flat) playlist URL."""
        opts = {**YtDlpEngine.base_options(config), "skip_download": True, "extract_flat": "in_playlist"}
        info = YtDlpEngine.run_with_fallbacks(opts, lambda ydl: ydl.extract_info(url, download=False))
        if not info:
            raise ValueError("Could not extract media metadata from URL")

        is_playlist = info.get("_type") == "playlist" or "entries" in info
        playlist_items: List[SearchResultItem] = []
        if is_playlist:
            for entry in info.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                raw_url = entry.get("url") or entry.get("webpage_url") or ""
                vid_id = str(entry.get("id") or "")
                if not raw_url.startswith(("http://", "https://")) and vid_id and "youtube" in str(entry.get("ie_key") or info.get("extractor") or "").lower():
                    raw_url = f"https://www.youtube.com/watch?v={vid_id}"
                index = len(playlist_items) + 1
                dur = entry.get("duration")
                playlist_items.append(
                    SearchResultItem(
                        id=vid_id,
                        title=entry.get("title") or f"Track {index}",
                        url=raw_url,
                        uploader=entry.get("uploader") or entry.get("channel") or info.get("uploader") or info.get("channel") or "Unknown",
                        duration=dur,
                        duration_str=format_duration(dur),
                        view_count=entry.get("view_count"),
                        playlist_index=index,
                    )
                )
            # Flat extraction has no per-video formats, so offer curated presets.
            video_formats, audio_formats = playlist_preset_formats()
        else:
            raw_formats = info.get("formats") or [
                {  # Single-format extractors (direct links) describe the stream on the info dict itself.
                    "format_id": info.get("format_id") or "direct",
                    "ext": info.get("ext") or "mp4",
                    **{k: info.get(k) for k in ("vcodec", "acodec", "height", "width", "fps", "tbr", "abr")},
                    "filesize": info.get("filesize") or info.get("filesize_approx"),
                    "format_note": info.get("format_note") or "Direct Stream",
                }
            ]
            video_formats, audio_formats = parse_formats(raw_formats)

        duration = info.get("duration")
        if is_playlist and duration is None:
            duration = sum(it.duration for it in playlist_items if it.duration and it.duration > 0) or None

        return ExtractionResult(
            url=url,
            title=info.get("title") or "Untitled Media",
            uploader=info.get("uploader") or info.get("channel") or "Unknown",
            duration_str=format_duration(duration),
            thumbnail=info.get("thumbnail") or "",
            is_playlist=is_playlist,
            playlist_entries=playlist_items,
            video_formats=video_formats,
            audio_formats=audio_formats,
            duration=duration,
        )

    @staticmethod
    def resolve_output_filepath(base_filename: str, container: str = "mp4", is_audio_only: bool = False) -> str:
        """Find the real output file after postprocessors may have changed its extension."""
        p = Path(base_filename)
        if p.is_file():
            return str(p)
        exts = (["mp3", "m4a", "flac", "opus", "wav", "aac", "ogg"] if is_audio_only else ["mp4", "mkv", "webm", "mov", "m4v"])
        candidates = ([container.lower()] if container else []) + exts
        clean_stem = p.stem.split(".tmp")[0].split(".temp")[0]
        for ext in candidates:
            # with_suffix keeps dots inside titles intact
            for cand in (p.with_suffix(f".{ext}"), p.parent / f"{clean_stem}.{ext}"):
                if cand.is_file():
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
        video_codec: str = "",
        audio_codec: str = "",
    ) -> Dict[str, Any]:
        """Build the full yt-dlp option dict for one download."""
        is_audio_only = video_format_id == "none"
        container = (target_container or "").lower()
        no_audio = audio_format_id in ("none", "")

        # Format spec with fallbacks for muxed/single-stream sites (Vimeo, Twitter, TikTok, ...)
        if is_audio_only:
            format_spec = "bestaudio/best" if audio_format_id in ("bestaudio", "none", "") else f"{audio_format_id}/bestaudio/best"
        elif no_audio:
            format_spec = "bestvideo/best" if video_format_id == "bestvideo" else f"{video_format_id}/best"
        elif video_format_id == "bestvideo" and audio_format_id == "bestaudio":
            if container == "mp4":
                format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best"
            elif container == "webm":
                format_spec = "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/bestvideo+bestaudio/best"
            else:
                format_spec = "bestvideo+bestaudio/best"
        elif video_format_id == "bestvideo":
            format_spec = f"bestvideo+{audio_format_id}/best"
        elif audio_format_id == "bestaudio":
            format_spec = f"{video_format_id}+bestaudio/{video_format_id}/best"
        else:
            format_spec = f"{video_format_id}+{audio_format_id}/best"

        download_path = Path(config.download_dir).expanduser()
        download_path.mkdir(parents=True, exist_ok=True)

        ydl_opts: Dict[str, Any] = {
            **YtDlpEngine.base_options(config),
            "format": format_spec,
            "outtmpl": str(download_path / config.filename_template),
            "windowsfilenames": True,
            "continuedl": config.continuedl,
            "retries": config.retries,
            "fragment_retries": config.fragment_retries,
            "socket_timeout": 30,
            "ignoreerrors": False,  # fatal stream errors must raise so they can be reported
            "no_color": True,
        }
        rate = parse_rate_limit(config.rate_limit)
        if rate:
            ydl_opts["ratelimit"] = rate  # yt-dlp expects bytes/s as a number, not '2M'

        ffmpeg_bin = find_ffmpeg(config.ffmpeg_location or None)
        if ffmpeg_bin:
            ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)

        requires_conversion = False
        if not is_audio_only:
            container = container if container in VIDEO_CONTAINERS else "mp4"
            requires_conversion = requires_video_conversion(container, video_codec, audio_codec)
            ydl_opts["merge_output_format"] = "mkv" if requires_conversion else container

        # Postprocessor order mirrors yt-dlp's own CLI ordering.
        pps: List[Dict[str, Any]] = []
        sponsor_categories: List[str] = []
        if config.remove_sponsor_segments:
            sponsor_categories = sanitize_sponsorblock_categories(config.sponsorblock_categories).split(",")
            pps.append({"key": "SponsorBlock", "categories": sponsor_categories, "api": "https://sponsor.ajay.app", "when": "after_filter"})

        if is_audio_only:
            pps.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": container if container in AUDIO_CONTAINERS + ["aac"] else "mp3",
                "preferredquality": "0" if audio_quality.lower() in ("v0", "0") else (audio_quality or "256"),
            })
        else:
            # Remux is fast; convert only when the codecs cannot live in the chosen container.
            pps.append({"key": "FFmpegVideoConvertor" if requires_conversion else "FFmpegVideoRemuxer", "preferedformat": container})

        if config.download_subtitles and not is_audio_only:
            embed = config.subtitle_mode in ("embed", "both")
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = config.auto_generated_subtitles
            ydl_opts["subtitleslangs"] = _subtitle_language_patterns(config.subtitle_langs, config.auto_generated_subtitles)
            if container != "mkv" or not embed:
                # webm can only embed WebVTT; everything else (and external files) gets SRT.
                pps.append({"key": "FFmpegSubtitlesConvertor", "format": "vtt" if embed and container == "webm" else "srt", "when": "before_dl"})
            if embed:
                pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": config.subtitle_mode == "both"})

        if sponsor_categories:
            pps.append({
                "key": "ModifyChapters",
                "remove_chapters_patterns": [],
                "remove_sponsor_segments": sponsor_categories,
                "remove_ranges": [],
                "sponsorblock_chapter_title": "[SponsorBlock]: %(category_names)l",
                "force_keyframes": False,
            })

        # Runs after extraction/conversion so the final container is known.
        if config.embed_metadata or config.embed_chapters:
            pps.append({"key": "FFmpegMetadata", "add_metadata": config.embed_metadata, "add_chapters": config.embed_chapters})

        if config.download_thumbnail:
            ydl_opts["writethumbnail"] = True
            pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            if config.thumbnail_mode == "embed" and container in ("mp3", "m4a", "flac", "opus", "mp4", "mkv"):
                pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        if config.split_chapters and not is_audio_only:
            pps.append({"key": "FFmpegSplitChapters"})

        ydl_opts["postprocessors"] = pps
        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]
        if postprocessor_hook:
            ydl_opts["postprocessor_hooks"] = [postprocessor_hook]
        if logger:
            ydl_opts["logger"] = logger
        return ydl_opts
