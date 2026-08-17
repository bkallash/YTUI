"""FFmpeg detection, path management, and automatic installer utilities."""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional, Tuple

from config import get_config_dir

# Official static builds recommended by yt-dlp project
FFMPEG_URLS = {
    "win64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    ],
    "linux64": [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    ],
    "macos": [
        "https://evermeet.cx/ffmpeg/getrelease/zip",
    ],
}


def get_ffmpeg_bin_dir() -> Path:
    """Return the application-managed binary directory for FFmpeg."""
    bin_dir = get_config_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return bin_dir


def _get_binary_name(binary: str) -> str:
    """Return platform-specific binary name."""
    if sys.platform == "win32" and not binary.lower().endswith(".exe"):
        return f"{binary}.exe"
    return binary


def _scan_directory_recursive(base_dir: Path, target_name: str, max_depth: int = 3) -> Optional[str]:
    """Recursively search for a binary within a directory up to max_depth levels."""
    if not base_dir.is_dir():
        return None
    try:
        for item in base_dir.iterdir():
            if item.is_file() and item.name.lower() == target_name.lower():
                return str(item.resolve())
            if item.is_dir() and max_depth > 0:
                result = _scan_directory_recursive(item, target_name, max_depth - 1)
                if result:
                    return result
    except (PermissionError, OSError):
        pass
    return None


def _get_windows_search_dirs() -> list:
    """Return a list of common Windows directories where FFmpeg might be installed."""
    dirs = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")

    # WinGet package directories (most common modern Windows install method)
    if local_appdata:
        winget_packages = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_packages.is_dir():
            dirs.append(winget_packages)
        winget_links = Path(local_appdata) / "Microsoft" / "WinGet" / "Links"
        if winget_links.is_dir():
            dirs.append(winget_links)
    # System-level WinGet links
    sys_winget_links = Path("C:/Program Files/WinGet/Links")
    if sys_winget_links.is_dir():
        dirs.append(sys_winget_links)

    # Chocolatey
    choco_bin = Path("C:/ProgramData/chocolatey/bin")
    if choco_bin.is_dir():
        dirs.append(choco_bin)
    choco_lib = Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools")
    if choco_lib.is_dir():
        dirs.append(choco_lib)

    # Scoop
    if userprofile:
        scoop_shims = Path(userprofile) / "scoop" / "shims"
        if scoop_shims.is_dir():
            dirs.append(scoop_shims)
        scoop_apps = Path(userprofile) / "scoop" / "apps" / "ffmpeg" / "current" / "bin"
        if scoop_apps.is_dir():
            dirs.append(scoop_apps)

    # Program Files
    for pf in ["C:/Program Files", "C:/Program Files (x86)"]:
        ffmpeg_pf = Path(pf) / "ffmpeg" / "bin"
        if ffmpeg_pf.is_dir():
            dirs.append(ffmpeg_pf)
        ffmpeg_pf2 = Path(pf) / "ffmpeg"
        if ffmpeg_pf2.is_dir():
            dirs.append(ffmpeg_pf2)

    return dirs


def find_binary(binary_name: str, custom_dir: Optional[str] = None) -> Optional[str]:
    """Locate a binary (ffmpeg or ffprobe) in known locations."""
    target_name = _get_binary_name(binary_name)

    # 1. Custom directory / file
    if custom_dir:
        custom_path = Path(custom_dir)
        if custom_path.is_file() and custom_path.name.lower() == target_name.lower() and custom_path.exists():
            return str(custom_path.resolve())
        if custom_path.is_dir():
            candidate = custom_path / target_name
            if candidate.is_file() and candidate.exists():
                return str(candidate.resolve())

    # 2. PyInstaller temporary extraction folder (if frozen)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / target_name
        if candidate.is_file() and candidate.exists():
            return str(candidate.resolve())

    # 3. Directory where executable or script resides
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).resolve().parent
    candidate = exe_dir / target_name
    if candidate.is_file() and candidate.exists():
        return str(candidate.resolve())

    # 4. Application-managed config bin directory
    app_bin = get_ffmpeg_bin_dir() / target_name
    if app_bin.is_file() and app_bin.exists():
        return str(app_bin.resolve())

    # 5. System PATH
    system_match = shutil.which(target_name) or shutil.which(binary_name)
    if system_match:
        return str(Path(system_match).resolve())

    # 6. Windows-specific: scan common installation directories (WinGet, Chocolatey, Scoop, etc.)
    if sys.platform == "win32":
        for search_dir in _get_windows_search_dirs():
            # Check directly in the directory first
            candidate = search_dir / target_name
            if candidate.is_file():
                return str(candidate.resolve())
            # Recursively scan (e.g., WinGet packages have nested structures)
            result = _scan_directory_recursive(search_dir, target_name, max_depth=3)
            if result:
                return result

    # 7. Fallback: use OS-native binary locator (where.exe on Windows, which on Unix)
    try:
        if sys.platform == "win32":
            res = subprocess.run(
                ["where.exe", target_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            res = subprocess.run(
                ["which", binary_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        if res.returncode == 0 and res.stdout.strip():
            found_path = res.stdout.strip().splitlines()[0].strip()
            if Path(found_path).is_file():
                return str(Path(found_path).resolve())
    except Exception:
        pass

    return None


def find_ffmpeg(custom_dir: Optional[str] = None) -> Optional[str]:
    """Locate ffmpeg binary."""
    return find_binary("ffmpeg", custom_dir)


def find_ffprobe(custom_dir: Optional[str] = None) -> Optional[str]:
    """Locate ffprobe binary."""
    return find_binary("ffprobe", custom_dir)


def is_ffmpeg_available(custom_dir: Optional[str] = None) -> bool:
    """Return True if ffmpeg is available."""
    return find_ffmpeg(custom_dir) is not None


def ensure_ffmpeg_in_path(custom_dir: Optional[str] = None) -> Optional[str]:
    """Ensure ffmpeg parent directory is in os.environ['PATH']."""
    ffmpeg_path = find_ffmpeg(custom_dir)
    if ffmpeg_path:
        parent_dir = str(Path(ffmpeg_path).parent.resolve())
        current_path = os.environ.get("PATH", "")
        # Prepend to PATH if not already at the front
        path_entries = current_path.split(os.pathsep)
        if parent_dir not in path_entries:
            os.environ["PATH"] = f"{parent_dir}{os.pathsep}{current_path}"
        return ffmpeg_path
    return None


def get_ffmpeg_version(custom_dir: Optional[str] = None) -> Optional[str]:
    """Retrieve human-readable version string for the active FFmpeg binary."""
    ffmpeg_path = find_ffmpeg(custom_dir)
    if not ffmpeg_path:
        return None
    try:
        res = subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0 and res.stdout:
            first_line = res.stdout.splitlines()[0]
            # e.g., "ffmpeg version 7.1-full_build-www.gyan.dev ..."
            return first_line.strip()
    except Exception:
        pass
    return "Unknown Version"


def download_and_install_ffmpeg(
    progress_callback: Optional[Callable[[int, int, float, str], None]] = None,
) -> Tuple[bool, str]:
    """Download official static FFmpeg binaries and install to app bin directory.

    Args:
        progress_callback: Optional callable(downloaded_bytes, total_bytes, percentage, status_message)

    Returns:
        Tuple of (success: bool, message: str)
    """
    bin_dir = get_ffmpeg_bin_dir()

    # Determine candidate URLs based on OS and architecture
    urls = []
    if sys.platform == "win32":
        urls = FFMPEG_URLS["win64"]
    elif sys.platform == "darwin":
        urls = FFMPEG_URLS["macos"]
    else:
        urls = FFMPEG_URLS["linux64"]

    if not urls:
        return False, f"Automatic FFmpeg download is not supported on {sys.platform}."

    last_error = ""
    for url in urls:
        try:
            if progress_callback:
                progress_callback(0, 100, 0.0, f"Connecting to download server...")

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YTUI/1.0"},
            )

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
                tmp_path = Path(tmp_file.name)

            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    block_size = 128 * 1024  # 128 KB

                    with open(tmp_path, "wb") as f_out:
                        while True:
                            chunk = response.read(block_size)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100.0
                                msg = f"Downloading FFmpeg ({downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB)"
                            else:
                                percent = 0.0
                                msg = f"Downloading FFmpeg ({downloaded / (1024*1024):.1f} MB)..."

                            if progress_callback:
                                progress_callback(downloaded, total_size, percent, msg)

                if progress_callback:
                    progress_callback(total_size, total_size, 100.0, "Extracting ffmpeg and ffprobe binaries...")

                # Extract binaries from zip
                extracted_count = 0
                target_binaries = ["ffmpeg.exe", "ffprobe.exe"] if sys.platform == "win32" else ["ffmpeg", "ffprobe"]

                if zipfile.is_zipfile(tmp_path):
                    with zipfile.ZipFile(tmp_path, "r") as zip_ref:
                        for member in zip_ref.namelist():
                            member_name = Path(member).name.lower()
                            for target in target_binaries:
                                if member_name == target.lower():
                                    target_dest = bin_dir / target
                                    with zip_ref.open(member) as source_file, open(target_dest, "wb") as dest_file:
                                        shutil.copyfileobj(source_file, dest_file)
                                    if os.name == "posix":
                                        os.chmod(target_dest, 0o755)
                                    extracted_count += 1

                if extracted_count > 0:
                    ensure_ffmpeg_in_path()
                    return True, f"Successfully installed FFmpeg ({extracted_count} binaries) to {bin_dir}"
                else:
                    last_error = "Archive did not contain required ffmpeg binaries."
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except Exception as e:
            last_error = str(e)
            continue

    return False, f"Failed to download FFmpeg: {last_error}"
