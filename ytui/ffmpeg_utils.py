"""FFmpeg detection, PATH management, and automatic installer."""

import os
import platform
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import IO, Callable, Iterator, List, Optional, Tuple

from .config import get_config_dir

# Official static builds recommended by the yt-dlp project
FFMPEG_URLS = {
    "win64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    ],
    "winarm64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-winarm64-gpl.zip",
    ],
    "linux64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    ],
    "linuxarm64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    ],
    "macos": [
        "https://evermeet.cx/ffmpeg/getrelease/zip",
    ],
}

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def get_ffmpeg_bin_dir() -> Path:
    """Return the application-managed binary directory for FFmpeg."""
    bin_dir = get_config_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return bin_dir


def _get_binary_name(binary: str) -> str:
    if sys.platform == "win32" and not binary.lower().endswith(".exe"):
        return f"{binary}.exe"
    return binary


def _scan_directory_recursive(base_dir: Path, target_name: str, max_depth: int = 3) -> Optional[str]:
    """Search for a binary within a directory up to max_depth levels."""
    try:
        for item in base_dir.iterdir():
            if item.is_file() and item.name.lower() == target_name.lower():
                return str(item.resolve())
            if max_depth > 0 and item.is_dir():
                result = _scan_directory_recursive(item, target_name, max_depth - 1)
                if result:
                    return result
    except OSError:
        pass
    return None


def _get_windows_search_dirs() -> List[Path]:
    """Common Windows install locations (WinGet, Chocolatey, Scoop, Program Files)."""
    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    if local_appdata:
        candidates += [Path(local_appdata) / "Microsoft" / "WinGet" / "Packages", Path(local_appdata) / "Microsoft" / "WinGet" / "Links"]
    candidates += [
        Path("C:/Program Files/WinGet/Links"),
        Path("C:/ProgramData/chocolatey/bin"),
        Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools"),
    ]
    if userprofile:
        candidates += [Path(userprofile) / "scoop" / "shims", Path(userprofile) / "scoop" / "apps" / "ffmpeg" / "current" / "bin"]
    for pf in ("C:/Program Files", "C:/Program Files (x86)"):
        candidates += [Path(pf) / "ffmpeg" / "bin", Path(pf) / "ffmpeg"]
    return [d for d in candidates if d.is_dir()]


@lru_cache(maxsize=None)
def find_binary(binary_name: str, custom_dir: Optional[str] = None) -> Optional[str]:
    """Locate a binary (ffmpeg or ffprobe). Cached: call clear_ffmpeg_cache() after installs."""
    target_name = _get_binary_name(binary_name)

    if custom_dir:
        custom_path = Path(custom_dir)
        if custom_path.is_file() and custom_path.name.lower() == target_name.lower():
            return str(custom_path.resolve())
        if (custom_path / target_name).is_file():
            return str((custom_path / target_name).resolve())

    local_dirs = []
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller extraction folder
    if meipass:
        local_dirs.append(Path(meipass))
    # Next to the frozen executable, or the source checkout root
    local_dirs.append(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)
    local_dirs.append(get_ffmpeg_bin_dir())
    for directory in local_dirs:
        if (directory / target_name).is_file():
            return str((directory / target_name).resolve())

    system_match = shutil.which(target_name) or shutil.which(binary_name)
    if system_match:
        return str(Path(system_match).resolve())

    if sys.platform == "win32":
        for search_dir in _get_windows_search_dirs():
            result = _scan_directory_recursive(search_dir, target_name, max_depth=3)
            if result:
                return result
        try:
            res = subprocess.run(["where.exe", target_name], capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW)
            found = res.stdout.strip().splitlines()[0].strip() if res.returncode == 0 and res.stdout.strip() else ""
            if found and Path(found).is_file():
                return str(Path(found).resolve())
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def clear_ffmpeg_cache() -> None:
    find_binary.cache_clear()


def find_ffmpeg(custom_dir: Optional[str] = None) -> Optional[str]:
    return find_binary("ffmpeg", custom_dir or None)


def find_ffprobe(custom_dir: Optional[str] = None) -> Optional[str]:
    return find_binary("ffprobe", custom_dir or None)


def is_ffmpeg_available(custom_dir: Optional[str] = None) -> bool:
    return find_ffmpeg(custom_dir) is not None


def ensure_ffmpeg_in_path(custom_dir: Optional[str] = None) -> Optional[str]:
    """Prepend the ffmpeg directory to PATH so yt-dlp and postprocessors find it."""
    ffmpeg_path = find_ffmpeg(custom_dir)
    if ffmpeg_path:
        parent_dir = str(Path(ffmpeg_path).parent.resolve())
        current_path = os.environ.get("PATH", "")
        if parent_dir not in current_path.split(os.pathsep):
            os.environ["PATH"] = f"{parent_dir}{os.pathsep}{current_path}"
    return ffmpeg_path


def get_ffmpeg_version(custom_dir: Optional[str] = None) -> Optional[str]:
    """First line of `ffmpeg -version`, or None when ffmpeg is missing. Spawns a process: call off the UI thread."""
    ffmpeg_path = find_ffmpeg(custom_dir)
    if not ffmpeg_path:
        return None
    try:
        res = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW)
        if res.returncode == 0 and res.stdout:
            return res.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "Unknown Version"


def _platform_key() -> str:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "winarm64" if arm else "win64"
    if sys.platform == "darwin":
        return "macos"
    return "linuxarm64" if arm else "linux64"


def _archive_members(archive: Path) -> Iterator[Tuple[str, Callable[[], IO[bytes]]]]:
    """Yield (basename, opener) for every regular file in a zip or tar archive."""
    import tarfile
    import zipfile

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    yield Path(info.filename).name, lambda info=info: zf.open(info)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf:
                if member.isfile():
                    yield Path(member.name).name, lambda member=member: tf.extractfile(member)


def download_and_install_ffmpeg(
    progress_callback: Optional[Callable[[int, int, float, str], None]] = None,
) -> Tuple[bool, str]:
    """Download a static FFmpeg build into the app bin directory.

    progress_callback(downloaded_bytes, total_bytes, percent, message) is throttled to ~10 calls/s.
    Returns (success, message).
    """
    import tempfile  # installer-only imports, kept out of app startup
    import urllib.request

    bin_dir = get_ffmpeg_bin_dir()
    report = progress_callback or (lambda *args: None)
    targets = {_get_binary_name("ffmpeg").lower(), _get_binary_name("ffprobe").lower()}
    last_error = ""

    for url in FFMPEG_URLS[_platform_key()]:
        tmp_path: Optional[Path] = None
        try:
            report(0, 100, 0.0, "Connecting to download server...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 YTUI"})
            with tempfile.NamedTemporaryFile(delete=False, suffix=".download") as tmp_file:
                tmp_path = Path(tmp_file.name)
            with urllib.request.urlopen(req, timeout=30) as response, open(tmp_path, "wb") as f_out:
                total = int(response.headers.get("content-length", 0))
                downloaded, last_report = 0, 0.0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 0.1:
                        last_report = now
                        mb = downloaded / (1024 * 1024)
                        if total:
                            report(downloaded, total, downloaded / total * 100.0, f"Downloading FFmpeg ({mb:.1f} MB / {total / (1024 * 1024):.1f} MB)")
                        else:
                            report(downloaded, total, 0.0, f"Downloading FFmpeg ({mb:.1f} MB)...")

            report(downloaded, total, 100.0, "Extracting ffmpeg and ffprobe binaries...")
            extracted = 0
            for name, opener in _archive_members(tmp_path):
                if name.lower() in targets:
                    dest = bin_dir / name  # basename only: archive paths can never escape bin_dir
                    with opener() as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if os.name == "posix":
                        os.chmod(dest, 0o755)
                    extracted += 1

            if extracted:
                clear_ffmpeg_cache()
                ensure_ffmpeg_in_path()
                return True, f"Successfully installed FFmpeg ({extracted} binaries) to {bin_dir}"
            last_error = "Archive did not contain required ffmpeg binaries."
        except Exception as e:
            last_error = str(e)
        finally:
            if tmp_path:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    return False, f"Failed to download FFmpeg: {last_error}"
