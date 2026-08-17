"""Configuration manager for YTUI."""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


def sanitize_path(raw_path: Optional[str]) -> str:
    """Sanitize user-entered path strings: strip quotes, expand variables, resolve tildes."""
    if not raw_path:
        return ""
    # Strip surrounding single/double quotes, whitespace, and smart quotes
    cleaned = str(raw_path).strip().strip('"\'“”‘’').strip()
    if not cleaned:
        return ""
    # Expand environment variables (e.g. %USERPROFILE%, %APPDATA%)
    cleaned = os.path.expandvars(cleaned)
    # Expand user home tilde (~)
    cleaned = os.path.expanduser(cleaned)
    return cleaned


DEFAULT_FILENAME_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
SPONSORBLOCK_CATEGORIES = (
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "preview",
    "filler",
    "music_offtopic",
    "hook",
)
DEFAULT_SPONSORBLOCK_CATEGORIES = "sponsor,selfpromo"


def sanitize_filename_template(template: Optional[str]) -> str:
    """Sanitize and validate filename template to prevent directory traversal outside download directory."""
    if not template or not isinstance(template, str):
        return DEFAULT_FILENAME_TEMPLATE
    cleaned = str(template).strip().strip('"\'“”‘’').strip()
    if not cleaned:
        return DEFAULT_FILENAME_TEMPLATE
    # Block absolute paths (POSIX / Windows) or drive specifications
    if cleaned.startswith(("/", "\\")) or (len(cleaned) >= 2 and cleaned[1] == ":"):
        return DEFAULT_FILENAME_TEMPLATE
    p = Path(cleaned)
    if p.is_absolute():
        return DEFAULT_FILENAME_TEMPLATE
    # Block path traversal segments (..)
    parts = cleaned.replace("\\", "/").split("/")
    if ".." in parts:
        return DEFAULT_FILENAME_TEMPLATE
    return cleaned


def sanitize_sponsorblock_categories(categories: Optional[str]) -> str:
    """Return a normalized comma-separated list of removable SponsorBlock categories."""
    requested = str(categories or "").lower().split(",")
    valid_categories = []
    for category in requested:
        clean_category = category.strip()
        if clean_category in SPONSORBLOCK_CATEGORIES and clean_category not in valid_categories:
            valid_categories.append(clean_category)
    return ",".join(valid_categories) or DEFAULT_SPONSORBLOCK_CATEGORIES


def atomic_json_save(path: Path, data: Any, indent: int = 2, file_mode: int = 0o600, dir_mode: int = 0o700) -> None:
    """Atomically write JSON data to path using a temporary file and os.replace."""
    target_path = Path(path).resolve() if not isinstance(path, Path) else path
    parent_dir = target_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(parent_dir, dir_mode)
        except OSError:
            pass

    tmp_path = parent_dir / f"{target_path.name}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        if os.name == "posix":
            try:
                os.chmod(tmp_path, file_mode)
            except OSError:
                pass
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def get_default_download_dir() -> str:
    """Return default user Downloads folder or current directory."""
    home = Path.home()
    downloads = home / "Downloads"
    if downloads.exists():
        return str(downloads)
    return str(home)


def get_config_dir() -> Path:
    """Return platform-appropriate configuration directory."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = Path(app_data)
        else:
            base = Path.home() / "AppData" / "Roaming"
    else:
        base = Path.home() / ".config"
    legacy_dir = base / "yt-dlp-tui"
    cfg_dir = base / "ytui"
    if not cfg_dir.exists() and legacy_dir.exists():
        cfg_dir = legacy_dir
    else:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(cfg_dir, 0o700)
        except OSError:
            pass
    return cfg_dir


@dataclass
class AppConfig:
    """Strongly typed application configuration settings."""

    # Download paths & naming
    download_dir: str = field(default_factory=get_default_download_dir)
    filename_template: str = DEFAULT_FILENAME_TEMPLATE

    def __post_init__(self) -> None:
        if self.cookies_file:
            self.cookies_file = sanitize_path(self.cookies_file)
        if self.download_dir:
            self.download_dir = sanitize_path(self.download_dir) or get_default_download_dir()
        self.filename_template = sanitize_filename_template(self.filename_template)
        self.sponsorblock_categories = sanitize_sponsorblock_categories(self.sponsorblock_categories)

    # Bandwidth & concurrency
    max_concurrent_downloads: int = 3
    rate_limit: str = "0"  # e.g., '0' for unlimited, '2M', '500K'

    # Network resiliency & auto-resume
    retries: int = 10
    fragment_retries: int = 10
    continuedl: bool = True

    # Authentication & Cookies
    browser_cookies: str = "none"  # none, chrome, firefox, edge, brave, opera, vivaldi, safari
    cookies_file: str = ""

    # Subtitles
    download_subtitles: bool = False
    auto_generated_subtitles: bool = False
    subtitle_mode: str = "embed"  # 'embed', 'external', or 'both'
    subtitle_langs: str = "en"

    # Thumbnails & Chapters
    download_thumbnail: bool = False
    thumbnail_mode: str = "embed"  # 'embed' or 'file'
    embed_chapters: bool = False
    split_chapters: bool = False
    remove_sponsor_segments: bool = False
    sponsorblock_categories: str = DEFAULT_SPONSORBLOCK_CATEGORIES

    # Metadata
    embed_metadata: bool = True

    # Media Engine & FFmpeg
    ffmpeg_location: str = ""
    skip_ffmpeg_check: bool = False

    # Proxy & Geo-bypass
    proxy: str = ""
    geo_bypass: bool = True

    # Appearance & Display
    theme: str = "shadcn-zinc"
    rtl_mode: str = "reshaped_bidi"  # 'reshaped_bidi', 'native_raw', 'bidi_only', 'disabled'

    @classmethod
    def config_file_path(cls) -> Path:
        return get_config_dir() / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        path = cls.config_file_path()
        if not path.exists():
            config = cls()
            config.save()
            return config
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Filter out keys that don't match dataclass fields
            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**filtered)
        except Exception:
            return cls()

    def save(self) -> None:
        path = self.config_file_path()
        try:
            atomic_json_save(path, asdict(self), indent=2, file_mode=0o600, dir_mode=0o700)
        except Exception as e:
            print(f"Warning: Could not save config: {e}", file=sys.stderr)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def update(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if "filename_template" in kwargs:
            self.filename_template = sanitize_filename_template(self.filename_template)
        if "sponsorblock_categories" in kwargs:
            self.sponsorblock_categories = sanitize_sponsorblock_categories(self.sponsorblock_categories)
        self.save()
