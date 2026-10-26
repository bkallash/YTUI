"""Pure format data model, parsing, container rules, and size estimation (no yt-dlp import)."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

AUDIO_CONTAINERS = ["mp3", "m4a", "flac", "opus", "wav"]
VIDEO_CONTAINERS = ["mp4", "mkv", "webm"]
AUDIO_QUALITIES = ["256", "320", "192", "128", "V0"]
LOSSLESS_CONTAINERS = ("flac", "wav")
DEFAULT_ITEM_DURATION = 210  # seconds, used when a playlist entry has no known duration

URL_RE = re.compile(r"^(https?://|www\.|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/)")
BITRATE_RE = re.compile(r"(\d+)\s*(?:k|kbps)", re.IGNORECASE)
RES_X_RE = re.compile(r"(\d+)\s*[xX]\s*(\d+)")
RES_P_RE = re.compile(r"(\d{3,4})p", re.IGNORECASE)
RES_4K_RE = re.compile(r"\b4k\b", re.IGNORECASE)
RES_2K_RE = re.compile(r"\b2k\b", re.IGNORECASE)

_AUDIO_EXTS = {"mp3", "m4a", "flac", "opus", "wav", "aac", "ogg", "weba"}
_NO_CODEC = ("none", "")


def format_bytes(size: Optional[float]) -> str:
    """Format bytes into a human-readable string."""
    if size is None or size <= 0:
        return "N/A"
    f_size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if f_size < 1024.0:
            return f"{f_size:.1f} {unit}"
        f_size /= 1024.0
    return f"{f_size:.1f} TB"


def format_duration(seconds: Optional[float]) -> str:
    """Convert seconds to MM:SS or H:MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def is_url(text: str) -> bool:
    """Check whether input text looks like a web URL rather than search keywords."""
    return bool(URL_RE.match(text.strip()))


@dataclass
class SearchResultItem:
    """A search result or playlist entry."""

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
    label: str  # e.g. '1080p60 (FHD)', '320 kbps (Best)'
    resolution: str  # e.g. '1080p' or '160k'
    height: int = 0
    fps: Optional[int] = None
    ext: str = ""
    vcodec: str = ""
    acodec: str = ""
    filesize: Optional[int] = None
    filesize_str: str = ""
    tbr: Optional[float] = None
    note: str = ""
    is_special: bool = False  # "No Video" / "Best" presets

    @property
    def is_none(self) -> bool:
        return self.format_id in ("none", "")


@dataclass
class ExtractionResult:
    """Metadata and selectable formats for a URL."""

    url: str
    title: str
    uploader: str
    duration_str: str
    thumbnail: str
    is_playlist: bool = False
    playlist_entries: List[SearchResultItem] = field(default_factory=list)
    video_formats: List[FormatOption] = field(default_factory=list)
    audio_formats: List[FormatOption] = field(default_factory=list)
    duration: Optional[int] = None


# ---------------------------------------------------------------------------
# Special options & playlist presets
# ---------------------------------------------------------------------------

def _no_video() -> FormatOption:
    return FormatOption("none", "video", "[No Video - Audio Only]", "Audio Only", note="Extract only selected audio stream", is_special=True)


def _no_audio() -> FormatOption:
    return FormatOption("none", "audio", "[No Audio - Video Only]", "Muted", note="Download video stream without audio", is_special=True)


def playlist_preset_formats() -> Tuple[List[FormatOption], List[FormatOption]]:
    """Curated video/audio choices for playlists, which are extracted flat (no per-video formats)."""
    video = [
        _no_video(),
        FormatOption("bestvideo", "video", "[Best Video Quality] (Auto)", "Best Available", note="Highest resolution available", is_special=True, height=2160, tbr=8000),
    ]
    for height, tag, tbr, note in (
        (2160, "4K UHD", 20000, "4K Ultra HD, ~20 Mbps"),
        (1440, "2K QHD", 10000, "2K Quad HD, ~10 Mbps"),
        (1080, "FHD", 5000, "Full HD, ~5 Mbps"),
        (720, "HD", 2500, "High Definition, ~2.5 Mbps"),
        (480, "SD", 1000, "Standard Def, ~1 Mbps"),
        (360, "Small", 500, "Small size, ~500 kbps"),
    ):
        video.append(FormatOption(f"bestvideo[height<={height}]", "video", f"{height}p ({tag})", f"{height}p", height=height, ext="mp4", tbr=tbr, note=note))

    audio = [
        _no_audio(),
        FormatOption("bestaudio", "audio", "[Best Audio Quality] (Auto)", "Best Available", note="Highest bitrate available", is_special=True, tbr=160),
    ]
    for kbps, tag in ((320, "Best"), (256, "High"), (192, "Medium"), (128, "Normal")):
        audio.append(FormatOption("bestaudio", "audio", f"{kbps} kbps [MP3/AAC] ({tag})", f"{kbps}k", ext="mp3", tbr=kbps, note=f"{tag} {kbps}k"))
    return video, audio


# ---------------------------------------------------------------------------
# Raw yt-dlp format parsing
# ---------------------------------------------------------------------------

def _codec(value: Any) -> str:
    return str(value or "none").lower().strip()


def extract_height(f: Dict[str, Any]) -> int:
    """Robustly extract the video height from a yt-dlp format dict."""
    h = f.get("height")
    if isinstance(h, int) and h > 0:
        return h
    m = RES_X_RE.search(str(f.get("resolution") or ""))
    if m:
        return min(int(m.group(1)), int(m.group(2)))
    for key in ("resolution", "format_note", "format", "format_id"):
        val = str(f.get(key) or "")
        m = RES_P_RE.search(val)
        if m:
            return int(m.group(1))
        if RES_4K_RE.search(val):
            return 2160
        if RES_2K_RE.search(val):
            return 1440
    return 0


def _audio_bitrate(f: Dict[str, Any], has_video: bool) -> int:
    abr = f.get("abr")
    if abr and abr > 0:
        return int(round(float(abr)))
    tbr = f.get("tbr")
    if tbr and tbr > 0 and not has_video:
        return int(round(float(tbr)))
    m = BITRATE_RE.search(str(f.get("format_note") or ""))
    return int(m.group(1)) if m else 0


def _quality_tag(height: int) -> str:
    for minimum, tag in ((2160, "4K"), (1440, "2K"), (1080, "FHD"), (720, "HD")):
        if height >= minimum:
            return f" ({tag})"
    return f" ({height}p)" if height > 0 else ""


def _video_option(f: Dict[str, Any], fid: str, vcodec: str, acodec: str, height: int) -> FormatOption:
    fps = f.get("fps")
    ext = str(f.get("ext") or "").lower().strip()
    size = f.get("filesize") or f.get("filesize_approx")
    has_video_codec = vcodec not in _NO_CODEC
    has_audio_codec = acodec not in _NO_CODEC
    codec_short = vcodec.split(".")[0] if has_video_codec else (ext.upper() or "Video")
    res_label = f"{height}p" if height > 0 else (str(f.get("format_note") or "").strip() or f.get("resolution") or fid)
    label = (
        f"{res_label}"
        + (f" {fps}fps" if fps and fps > 30 else "")
        + _quality_tag(height)
        + (f" [{ext.upper()}]" if ext else "")
        + (" (Video+Audio)" if has_audio_codec else "")
    )
    return FormatOption(
        format_id=fid,
        format_type="video",
        label=label,
        resolution=res_label,
        height=height,
        fps=fps,
        ext=ext,
        vcodec=codec_short,
        acodec=acodec if has_audio_codec else "none",
        filesize=size,
        filesize_str=format_bytes(size),
        tbr=f.get("tbr"),
        note=f"{codec_short}, ~{format_bytes(size)}",
    )


def _audio_option(f: Dict[str, Any], fid: str, acodec: str, bitrate: int) -> FormatOption:
    ext = str(f.get("ext") or "").lower().strip()
    size = f.get("filesize") or f.get("filesize_approx")
    format_note = str(f.get("format_note") or "").strip()
    lang = str(f.get("language") or f.get("language_preference") or "").strip()
    channels = f.get("audio_channels")
    codec_short = acodec.split(".")[0] if acodec not in _NO_CODEC else (ext.upper() or "Audio")

    lang_tag = ""
    if lang and lang.lower() not in ("und", "none"):
        lang_tag = f" [{lang.upper()}]"
    elif format_note and not any(k in format_note.lower() for k in ("tiny", "small", "medium", "audio only")):
        lang_tag = f" ({format_note})"
    bitrate_str = f"{bitrate} kbps" if bitrate > 0 else (format_note or "Audio")
    label = " ".join(
        f"{bitrate_str}{f' [{ext.upper()}]' if ext else ''} ({codec_short}){' (5.1)' if channels and channels >= 6 else ''}{lang_tag}".split()
    )

    note_parts = [codec_short]
    if size and size > 0:
        note_parts.append(f"~{format_bytes(size)}")
    if channels and channels >= 6:
        note_parts.append("5.1 Surround")
    if lang:
        note_parts.append(lang.upper())

    return FormatOption(
        format_id=fid,
        format_type="audio",
        label=label,
        resolution=f"{bitrate}k" if bitrate > 0 else "audio",
        ext=ext,
        vcodec="none",
        acodec=codec_short,
        filesize=size,
        filesize_str=format_bytes(size),
        tbr=f.get("tbr") or (float(bitrate) if bitrate > 0 else None),
        note=", ".join(note_parts),
    )


def parse_formats(formats: List[Dict[str, Any]]) -> Tuple[List[FormatOption], List[FormatOption]]:
    """Turn raw yt-dlp format dicts into sorted, de-duplicated video and audio options.

    Muxed (video+audio) formats appear in both columns. Near-duplicates are only dropped once a
    column already offers plenty of choices, so sparse sites still show every format.
    """
    video_opts = [_no_video(), FormatOption("bestvideo", "video", "[Best Video Quality] (Auto)", "Best Available", note="Highest resolution & framerate available", is_special=True)]
    audio_opts = [_no_audio(), FormatOption("bestaudio", "audio", "[Best Audio Quality] (Auto)", "Best Available", note="Highest bitrate audio available", is_special=True)]

    videos: List[Tuple[tuple, Dict[str, Any], str, str, str, int]] = []
    audios: List[Tuple[tuple, Dict[str, Any], str, str, int]] = []
    for f in formats or ():
        fid = str(f.get("format_id", "")).strip()
        if not fid:
            continue
        vcodec, acodec = _codec(f.get("vcodec")), _codec(f.get("acodec"))
        height = extract_height(f)
        has_video = vcodec not in _NO_CODEC or height > 0
        ext = str(f.get("ext") or "").lower().strip()
        size = f.get("filesize") or f.get("filesize_approx") or 0
        if has_video:
            videos.append(((height, f.get("tbr") or 0, f.get("fps") or 0, size), f, fid, vcodec, acodec, height))
        is_audio = acodec not in _NO_CODEC or ext in _AUDIO_EXTS or "audio" in fid.lower() or "audio" in str(f.get("format_note") or "").lower()
        if is_audio:
            bitrate = _audio_bitrate(f, has_video)
            audios.append(((bitrate, size), f, fid, acodec, bitrate))

    seen_ids: set = set()
    seen_keys: set = set()
    for _, f, fid, vcodec, acodec, height in sorted(videos, key=lambda v: v[0], reverse=True):
        if fid in seen_ids:
            continue
        seen_ids.add(fid)
        fps = f.get("fps")
        key = (height, fps if fps and fps > 30 else 30, str(f.get("ext") or "").lower())
        if key in seen_keys and len(seen_keys) > 8:
            continue
        seen_keys.add(key)
        video_opts.append(_video_option(f, fid, vcodec, acodec, height))

    seen_ids, seen_keys = set(), set()
    for _, f, fid, acodec, bitrate in sorted(audios, key=lambda a: a[0], reverse=True):
        if fid in seen_ids:
            continue
        option = _audio_option(f, fid, acodec, bitrate)
        key = (round(bitrate / 16) * 16 if bitrate > 0 else 0, option.ext, option.acodec, str(f.get("language") or f.get("language_preference") or "").lower(), f.get("audio_channels") or 2)
        if key in seen_keys and len(seen_keys) > 12:
            continue
        seen_keys.add(key)
        seen_ids.add(fid)
        audio_opts.append(option)

    return video_opts, audio_opts


# ---------------------------------------------------------------------------
# Container & quality defaults
# ---------------------------------------------------------------------------

def _snap_bitrate(kbps: int) -> str:
    for minimum, preset in ((290, "320"), (220, "256"), (150, "192"), (110, "128")):
        if kbps >= minimum:
            return preset
    return str(kbps)


def extract_audio_quality_from_option(option: Optional[FormatOption]) -> str:
    """Pick an export bitrate preset ('128'...'320') matching the source audio option."""
    if not option or option.is_none:
        return "256"
    if option.tbr and round(option.tbr) > 0:
        return _snap_bitrate(int(round(option.tbr)))
    m = BITRATE_RE.search(f"{option.resolution} {option.label}")
    if m and int(m.group(1)) > 0:
        return _snap_bitrate(int(m.group(1)))
    return "256"


def extract_audio_container_from_option(option: Optional[FormatOption]) -> str:
    """Default audio export container for an audio option."""
    if not option or option.is_none:
        return "mp3"
    ext = (option.ext or "").lower().strip()
    acodec = (option.acodec or "").lower()
    label = (option.label or "").lower()
    if ext in AUDIO_CONTAINERS:
        return ext
    if ext == "aac":
        return "m4a"
    if ext in ("webm", "ogg") or "opus" in acodec or "opus" in label:
        return "opus"
    if "m4a" in label or "aac" in acodec or "aac" in label:
        return "m4a"
    for container in ("mp3", "flac", "wav"):
        if container in label:
            return container
    return "mp3"


def extract_video_container_from_option(option: Optional[FormatOption]) -> str:
    """Default video container for a video option."""
    ext = (option.ext or "").lower().strip() if option and not option.is_none else ""
    return ext if ext in VIDEO_CONTAINERS else "mp4"


def _codec_matches(codec: str, prefixes: Tuple[str, ...]) -> bool:
    normalized = (codec or "").strip().lower()
    return normalized in _NO_CODEC or normalized.startswith(prefixes)


def requires_video_conversion(target: str, video_codec: str, audio_codec: str) -> bool:
    """Whether the selected stream pair must be transcoded (not just remuxed) for the target container."""
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


# ---------------------------------------------------------------------------
# Size estimation
# ---------------------------------------------------------------------------

def _video_kbps(fmt: Optional[FormatOption]) -> float:
    if not fmt or fmt.is_none:
        return 0.0
    if fmt.tbr and fmt.tbr > 0:
        return float(fmt.tbr)
    if fmt.height:
        for minimum, kbps in ((2160, 20000.0), (1440, 10000.0), (1080, 5500.0), (720, 2500.0), (480, 1000.0), (360, 500.0)):
            if fmt.height >= minimum:
                return kbps
        return 350.0
    return 5000.0 if fmt.format_id == "bestvideo" else 2500.0


def _audio_kbps(fmt: Optional[FormatOption], audio_only: bool, audio_quality: str) -> float:
    if not fmt or fmt.is_none:
        return 0.0
    if audio_only:
        # Audio-only exports are re-encoded at the chosen quality.
        if audio_quality == "V0":
            return 245.0
        if audio_quality and audio_quality.isdigit():
            return float(audio_quality)
    if fmt.tbr and fmt.tbr > 0:
        return float(fmt.tbr)
    if audio_only:
        return 256.0
    if fmt.format_id == "bestaudio":
        return 160.0
    m = BITRATE_RE.search(fmt.label or "")
    return float(m.group(1)) if m else 128.0


def estimate_format_bitrates(
    video_fmt: Optional[FormatOption],
    audio_fmt: Optional[FormatOption],
    audio_quality: str = "256",
) -> Tuple[float, float, float]:
    """Return estimated (video_kbps, audio_kbps, total_kbps)."""
    audio_only = bool(video_fmt and video_fmt.is_none)
    video_kbps = _video_kbps(video_fmt)
    audio_kbps = _audio_kbps(audio_fmt, audio_only, audio_quality)
    return video_kbps, audio_kbps, video_kbps + audio_kbps


def estimate_item_size(
    duration_sec: Optional[int],
    video_fmt: Optional[FormatOption],
    audio_fmt: Optional[FormatOption],
    audio_quality: str = "256",
    fallback_duration: int = DEFAULT_ITEM_DURATION,
) -> int:
    """Estimate the byte size of one media item from its duration and selected bitrates."""
    duration = duration_sec if duration_sec and duration_sec > 0 else fallback_duration
    total_kbps = estimate_format_bitrates(video_fmt, audio_fmt, audio_quality)[2]
    return max(1024, int(total_kbps * 125.0 * duration))  # kbps * 1000 / 8 = bytes/s


def estimate_playlist_size(
    items: List[SearchResultItem],
    video_fmt: Optional[FormatOption],
    audio_fmt: Optional[FormatOption],
    audio_quality: str = "256",
) -> Tuple[int, int]:
    """Estimate total (bytes, seconds) for playlist items; unknown durations use the known average."""
    if not items:
        return 0, 0
    known = [it.duration for it in items if it.duration and it.duration > 0]
    avg = int(sum(known) / len(known)) if known else DEFAULT_ITEM_DURATION
    total_kbps = estimate_format_bitrates(video_fmt, audio_fmt, audio_quality)[2]
    total_seconds = sum(it.duration if it.duration and it.duration > 0 else avg for it in items)
    total_bytes = sum(max(1024, int(total_kbps * 125.0 * (it.duration if it.duration and it.duration > 0 else avg))) for it in items)
    return total_bytes, total_seconds


def estimate_stream_sizes(
    video_fmt: Optional[FormatOption],
    audio_fmt: Optional[FormatOption],
    duration: Optional[int],
    audio_quality: str = "256",
) -> Tuple[int, int]:
    """Estimate (video_bytes, audio_bytes), preferring real filesizes over bitrate math."""
    sizes = []
    for fmt, kbps in (
        (video_fmt, _video_kbps(video_fmt)),
        (audio_fmt, _audio_kbps(audio_fmt, False, audio_quality)),  # source stream, not the re-encode
    ):
        if not fmt or fmt.is_none:
            sizes.append(0)
        elif fmt.filesize and fmt.filesize > 0:
            sizes.append(int(fmt.filesize))
        else:
            sizes.append(int(kbps * 125.0 * duration) if duration and duration > 0 else 0)
    return sizes[0], sizes[1]
