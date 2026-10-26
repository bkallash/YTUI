"""Configuration model and persistence helpers for YTUI."""

import json
import os
import re
import sys
from dataclasses import MISSING, asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

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

# Allowed values for enum-like settings; the first entry is the fallback.
CHOICES: Dict[str, tuple] = {
    "browser_cookies": ("none", "chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari"),
    "subtitle_mode": ("embed", "external", "both"),
    "thumbnail_mode": ("embed", "file"),
    "rtl_mode": ("reshaped_bidi", "native_raw", "bidi_only", "disabled"),
}

# Same grammar as yt_dlp.utils.parse_bytes, so validation needs no yt-dlp import.
_RATE_RE = re.compile(r"^(\d+(?:\.\d+)?)([kMGTPEZY]?)$", re.IGNORECASE)
_QUOTES = "\"'“”‘’"


def sanitize_path(raw_path: Optional[str]) -> str:
    """Strip quotes/whitespace and expand env variables and ~ in a user-entered path."""
    cleaned = str(raw_path or "").strip().strip(_QUOTES).strip()
    if not cleaned:
        return ""
    return os.path.expanduser(os.path.expandvars(cleaned))


def sanitize_filename_template(template: Optional[str]) -> str:
    """Reject templates that are absolute or escape the download directory."""
    if not isinstance(template, str):
        return DEFAULT_FILENAME_TEMPLATE
    cleaned = template.strip().strip(_QUOTES).strip()
    if not cleaned:
        return DEFAULT_FILENAME_TEMPLATE
    if cleaned.startswith(("/", "\\")) or (len(cleaned) >= 2 and cleaned[1] == ":") or Path(cleaned).is_absolute():
        return DEFAULT_FILENAME_TEMPLATE
    if ".." in cleaned.replace("\\", "/").split("/"):
        return DEFAULT_FILENAME_TEMPLATE
    return cleaned


def sanitize_sponsorblock_categories(categories: Optional[str]) -> str:
    """Return a normalized comma-separated list of removable SponsorBlock categories."""
    valid = []
    for category in str(categories or "").lower().split(","):
        category = category.strip()
        if category in SPONSORBLOCK_CATEGORIES and category not in valid:
            valid.append(category)
    return ",".join(valid) or DEFAULT_SPONSORBLOCK_CATEGORIES


def parse_rate_limit(value: Optional[str]) -> Optional[int]:
    """Parse '500K' / '2M' / '1.5m' into bytes per second. 0 or empty means unlimited (None)."""
    match = _RATE_RE.match(str(value or "").strip())
    if not match:
        return None
    number = float(match.group(1)) * 1024 ** "bkmgtpezy".index((match.group(2) or "b").lower())
    return int(number) or None


def is_valid_rate_limit(value: Optional[str]) -> bool:
    text = str(value or "").strip()
    return text in ("", "0") or parse_rate_limit(text) is not None


def atomic_json_save(path: Path, data: Any, indent: Optional[int] = 2, file_mode: int = 0o600, dir_mode: int = 0o700) -> None:
    """Atomically write JSON to path via a temporary file and os.replace."""
    target_path = Path(path)
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
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def load_json_or_backup(path: Path) -> Any:
    """Load JSON from path. A corrupt file is renamed to *.bak so a later save cannot destroy it."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as err:
        print(f"Warning: could not read {path}: {err}", file=sys.stderr)
        try:
            os.replace(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
        return None


def get_default_download_dir() -> str:
    """Return the user's Downloads folder, or home if it does not exist."""
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


@lru_cache(maxsize=None)
def get_config_dir() -> Path:
    """Return (and create once) the platform-appropriate configuration directory."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
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
    """Strongly typed application settings. Values are coerced and validated on construction."""

    # Download paths & naming
    download_dir: str = field(default_factory=get_default_download_dir)
    filename_template: str = DEFAULT_FILENAME_TEMPLATE

    # Bandwidth & concurrency
    max_concurrent_downloads: int = 3
    rate_limit: str = "0"  # '0' for unlimited, '2M', '500K'

    # Network resiliency & auto-resume
    retries: int = 10
    fragment_retries: int = 10
    continuedl: bool = True

    # Authentication & cookies
    browser_cookies: str = "none"
    cookies_file: str = ""

    # Subtitles
    download_subtitles: bool = False
    auto_generated_subtitles: bool = False
    subtitle_mode: str = "embed"
    subtitle_langs: str = "en"

    # Thumbnails & chapters
    download_thumbnail: bool = False
    thumbnail_mode: str = "embed"
    embed_chapters: bool = False
    split_chapters: bool = False
    remove_sponsor_segments: bool = False
    sponsorblock_categories: str = DEFAULT_SPONSORBLOCK_CATEGORIES

    # Metadata
    embed_metadata: bool = True

    # Media engine & FFmpeg
    ffmpeg_location: str = ""
    skip_ffmpeg_check: bool = False

    # Proxy & geo-bypass
    proxy: str = ""
    geo_bypass: bool = True

    # Appearance
    theme: str = "shadcn-zinc"
    rtl_mode: str = "reshaped_bidi"

    def __post_init__(self) -> None:
        # Coerce every field to its default's type so a hand-edited config cannot crash the app.
        for f in fields(self):
            default = f.default if f.default is not MISSING else f.default_factory()
            value = getattr(self, f.name)
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    value = str(value).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            elif not isinstance(value, str):
                value = default if value is None else str(value)
            setattr(self, f.name, value)

        for name, allowed in CHOICES.items():
            if getattr(self, name) not in allowed:
                setattr(self, name, allowed[0])
        self.max_concurrent_downloads = max(1, self.max_concurrent_downloads)
        self.retries = max(0, self.retries)
        self.fragment_retries = max(0, self.fragment_retries)
        self.rate_limit = self.rate_limit.strip() or "0"
        if not is_valid_rate_limit(self.rate_limit):
            self.rate_limit = "0"
        self.cookies_file = sanitize_path(self.cookies_file)
        self.ffmpeg_location = sanitize_path(self.ffmpeg_location)
        self.download_dir = sanitize_path(self.download_dir) or get_default_download_dir()
        self.filename_template = sanitize_filename_template(self.filename_template)
        self.sponsorblock_categories = sanitize_sponsorblock_categories(self.sponsorblock_categories)
        self.proxy = self.proxy.strip()
        self.subtitle_langs = self.subtitle_langs.strip()

    @classmethod
    def config_file_path(cls) -> Path:
        return get_config_dir() / "config.json"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Build a config from a dict, ignoring unknown keys."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @classmethod
    def load(cls) -> "AppConfig":
        path = cls.config_file_path()
        data = load_json_or_backup(path)
        if data is None:
            config = cls()
            if not path.exists():
                config.save()
            return config
        return cls.from_dict(data) if isinstance(data, dict) else cls()

    def save(self) -> None:
        try:
            atomic_json_save(self.config_file_path(), asdict(self))
        except Exception as e:
            print(f"Warning: Could not save config: {e}", file=sys.stderr)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def replace(self, **changes: Any) -> "AppConfig":
        """Return a validated copy with the given fields changed."""
        return AppConfig.from_dict({**asdict(self), **changes})

    def update(self, **kwargs: Any) -> None:
        """Apply validated changes in place and persist them."""
        validated = self.replace(**kwargs)
        for f in fields(self):
            setattr(self, f.name, getattr(validated, f.name))
        self.save()
