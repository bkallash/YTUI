<div align="center">

# ⚡ YTUI

**A sleek, keyboard-driven, high-density Terminal User Interface (TUI) client and download manager for [yt-dlp](https://github.com/yt-dlp/yt-dlp).**

[![Python Version](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Textual](https://img.shields.io/badge/built%20with-Textual-00D2FF.svg?style=flat)](https://textual.textualize.io/)
[![Rich](https://img.shields.io/badge/styled%20with-Rich-FF4B4B.svg?style=flat)](https://rich.readthedocs.io/)
[![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-FF0000.svg?style=flat&logo=youtube&logoColor=white)](https://github.com/yt-dlp/yt-dlp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)
[![Standalone Executable](https://img.shields.io/badge/Windows-Standalone%20.exe-22c55e.svg?style=flat&logo=windows&logoColor=white)](dist/yt-dlp-tui.exe)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg?style=flat)]()

</div>

---

## ⚡ Quick Download & Run (No Python Required)

Want to use the app immediately on Windows without setting up Python, Git, or virtual environments?

### 📥 1-Step Download & Launch
1. **Download the standalone binary**:
   - Grab **[`yt-dlp-tui.exe`](dist/yt-dlp-tui.exe)** from the [`dist/`](dist/) folder (or GitHub Releases).
2. **Launch & Auto-Setup**:
   - Double-click **`yt-dlp-tui.exe`**.
   - On first launch, the app automatically detects if FFmpeg is installed and offers a **1-click automatic download & install** for full 4K / MP3 support!

---

## 📖 Overview


**YTUI** brings the unmatched downloading power of `yt-dlp` and `FFmpeg` into a modern, interactive terminal interface built with **Python**, **Textual**, and **Rich**.

No more memorizing complex CLI flags or wrestling with stream formats:
- 🎯 **Visual Stream Selector**: Pick exact video (4K, 2K, 1080p...) and audio (320k, 256k, 192k...) streams side-by-side.
- ⚡ **Background Queue Manager**: Track active downloads with live speed, ETA, progress bars, and stdout logs.
- 📑 **Playlist Configurator**: Select, deselect, or invert tracks with live size and duration estimations.
- 🏷️ **Rich Media Embedding**: Embed subtitles, high-res thumbnails/cover art, artist/album metadata tags, and video chapter markers directly into your files.
- 🛡️ **Network Auto-Resume**: Automatically recovers interrupted downloads from exact byte offsets.
- 🎨 **17 Handcrafted Themes**: Tailored dark and light themes (Shadcn Zinc, Tokyo Night, Catppuccin, Dracula, Nord, OLED Black, and more).
- 🌍 **Native RTL Text Engine**: Clean rendering for Arabic, Hebrew, Persian, and Urdu metadata without character corruption.

---

## ✨ Key Features

### 🔍 Multi-Platform Search & URL Extraction
- **1,000+ Supported Sites**: Works seamlessly with YouTube, X/Twitter, TikTok, Twitch, SoundCloud, Vimeo, Reddit, Bilibili, Facebook, Instagram, and more.
- **Direct Search**: Search YouTube directly by typing search terms (`ytsearch`) without opening a browser.
- **Interactive Results**: View title, uploader, duration, view counts, and upload dates before downloading.

### 🎛️ Dual-Column Side-by-Side Stream Matrix
- **Independent Stream Pairing**:
  - **Left Column (Video)**: Choose 4K, 2K, 1080p, 720p, 480p, 360p, or **`🚫 No Video (Audio Only)`**.
  - **Right Column (Audio)**: Choose 320 kbps, 256 kbps, 192 kbps, 128 kbps, 64 kbps, or **`🔇 No Audio (Video Only)`**.
- **Container Flexibility**: Select target containers (`MP4`, `MKV`, `WEBM`, `MP3`, `M4A`, `FLAC`, `OPUS`, `WAV`, `AAC`).
- **1-Click Presets**:
  - `1` : **⭐ Best Quality** (Best available video + best audio)
  - `2` : **🎬 1080p FHD** (Crisp Full HD standard)
  - `3` : **📦 Smallest Size** (Storage-efficient resolution)
  - `4` : **🎵 Audio Only MP3** (Extracted high-bitrate music)

### 📑 Interactive Playlist & Batch Downloader
- **Track Selection Dialog**: Interactive checkboxes to pick specific videos from albums, playlists, or channels.
- **Batch Tools**: `Select All` (`Ctrl+A`), `Deselect All` (`Ctrl+D`), and `Invert Selection` (`I`).
- **Dynamic Estimations**: Live calculation of total selected tracks, combined runtime, and estimated download size.

### 📥 Multi-Worker Queue & Download Manager (`Ctrl+J`)
- **Concurrent Workers**: Download multiple tasks simultaneously in the background.
- **Live Statistics**: Real-time download speed, percentage, transferred bytes, and estimated completion time (ETA).
- **Task Controls**: Pause (`P`), Resume / Retry (`R`), Edit Format (`E`), Cancel (`C`), Delete (`D`), and Clear Completed (`X`).
- **Real-Time Logs**: Press `L` to toggle the live yt-dlp stdout log stream for deep diagnostics.
- **Quick File Launch**: Open downloaded files in your default media player (`O` / `Enter`) or reveal the destination directory in File Explorer (`F`).

### 🛡️ Network Resiliency & Smart Auto-Resume
- **Byte-Offset Resumption**: Partial `.part` files are automatically resumed from where they stopped (`continuedl: True`).
- **Connection Drop Recovery**: Automatic exponential retry backoff (up to 10 retries by default) for unstable networks.
- **HTTP 403 Forbidden Auto-Fallback**: Automatically retries with embedded web clients if YouTube throttles format downloads.

### 🍪 Authentication & Cookies Suite
- **Browser Extraction**: One-click session cookie extraction for Google Chrome, Mozilla Firefox, Microsoft Edge, Brave, Opera, Vivaldi, and Apple Safari.
- **Custom `cookies.txt` Support**: Fully compatible with exported Netscape format cookies for age-restricted and member-only videos.
- **Built-in Auth Tester**: Test your cookie file directly inside the Settings screen to verify active login sessions.

### ✂️ SponsorBlock, Embeddings & Media Post-Processing
- **Embed Subtitles**: Download and hard-embed or soft-embed subtitles directly into video streams (`MP4`, `MKV`, `WEBM`) with multi-language selection and AI/auto-generated caption support, or export as standalone `.srt` files.
- **Embed Thumbnails & Artwork**: Embed high-resolution video thumbnails and cover art directly into media files (`MP4`, `MKV`, `MP3`, `M4A`, `FLAC`, etc.) with native Mutagen integration.
- **Embed Artist & Metadata**: Automatically tag downloads with Artist, Title, Album, Channel/Uploader, and Year/Release Date metadata for a clean music and video library.
- **Embed Chapter Markers & Splitting**: Embed chapter markers directly into containers for instant chapter navigation in players (VLC, mpv, etc.), or split long videos into separate per-chapter tracks (`--split-chapters`).
- **SponsorBlock Integration**: Automatically detect and remove community-reported sponsored segments, self-promotions, intros, and outros from media files.

### 🎨 17 Handcrafted Themes
Switch between modern terminal aesthetics via **`Ctrl+O`** → **Appearance**:
- **Dark Profiles**: `Shadcn Zinc`, `Tokyo Night`, `Catppuccin Mocha`, `Dracula Pro`, `Nord Polar`, `Gruvbox Dark`, `Monokai Pro`, `Cyberpunk Neon`, `Midnight Amethyst`, `Matrix Emerald`, `Rosé Pine`, `Solarized Dark`, `Synthwave '84`, `OLED Jet Black`.
- **Light Profiles**: `Catppuccin Latte`, `Solarized Light`, `Titanium Light`.

### 🌍 Arabic & RTL Text Engine
- First-class support for Right-to-Left (RTL) languages including Arabic, Hebrew, Persian, and Urdu.
- Resolves broken disconnected characters and reversed terminal text with automatic glyph shaping and Unicode BiDi algorithm.
- Multiple selectable modes: `Reshaped + BiDi`, `Native Terminal RTL`, `BiDi Order Only`, or `Disabled`.

---

## 🚀 Setup & Installation

### Option A: Pre-built Executable (Fastest — No Python Required)

1. **Download**: Download [`yt-dlp-tui.exe`](dist/yt-dlp-tui.exe) from the [`dist/`](dist/) folder or GitHub Releases.
2. **FFmpeg (Optional but Recommended)**:
   - To enable 1080p/4K/8K stream merging, audio extraction, and SponsorBlock cutting:
     ```cmd
     winget install Gyan.FFmpeg
     ```
     *(Or download `ffmpeg.exe` and `ffprobe.exe` and place them next to `yt-dlp-tui.exe`)*.
3. **Launch**:
   - Double-click `yt-dlp-tui.exe` to run immediately.

---

### Option B: Run from Source (Python 3.10+)

#### 1. Prerequisites
- **Python 3.10 or higher**: Verify with `python --version`.
- **FFmpeg**:
  - **Windows**: `winget install Gyan.FFmpeg` or `scoop install ffmpeg` / `choco install ffmpeg`
  - **macOS**: `brew install ffmpeg`
  - **Linux**: `sudo apt install ffmpeg` / `sudo pacman -S ffmpeg` / `sudo dnf install ffmpeg`

#### 2. Clone & Install Dependencies
```bash
# Clone the repository
git clone https://github.com/yourusername/YTUI.git
cd YTUI

# Create and activate a virtual environment (recommended)
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On Linux / macOS:
source .venv/bin/activate

# Install required Python packages
pip install -r requirements.txt
```

#### 3. Launch the Application
```bash
python app.py
```

**On Windows**, you can also double-click or run:
```cmd
.\tui.bat
```


---

## ⌨️ Keyboard Shortcuts Cheat Sheet

### 🌐 Global Navigation
| Shortcut | Action |
| :--- | :--- |
| **`Ctrl+S`** | Switch to **Search & URL Input** screen |
| **`Ctrl+J`** | Switch to **Download Queue Manager** screen |
| **`Ctrl+Y`** | Switch to **Download History & Library** screen |
| **`Ctrl+O`** | Switch to **Settings & Configuration** screen |
| **`Ctrl+Q`** | Graceful exit (saves config and stops active workers) |

---

### 🔍 Search Screen
| Shortcut | Action |
| :--- | :--- |
| **`Enter`** (in input) | Start extraction / YouTube search |
| **`Up` / `Down`** | Navigate search results table |
| **`Enter`** (on row) | Select video and open format selector |
| **`Esc`** | Clear input / Return to previous state |

---

### 🎛️ Stream & Format Selector
| Shortcut | Action |
| :--- | :--- |
| **`Left` / `Right`** (`h`/`l`) | Switch focus between Video and Audio columns |
| **`Up` / `Down`** (`j`/`k`) | Navigate available format streams in active column |
| **`1` / `2` / `3` / `4`** | Select Preset: `1` Best, `2` 1080p, `3` Smallest, `4` Audio Only |
| **`C`** | Cycle target container format (`MP4`, `MKV`, `WEBM`, etc.) |
| **`Q`** | Cycle audio bitrate quality (`320k`, `256k`, `192k`, `128k`, `V0`) |
| **`Enter` / `D`** | Start download immediately and switch to Queue |
| **`A`** | Add task to Queue in background without leaving screen |
| **`Esc`** | Return to Search screen |

---

### 📑 Playlist Configurator
| Shortcut | Action |
| :--- | :--- |
| **`Space`** | Toggle inclusion checkbox for selected track |
| **`Ctrl+A`** | Select all tracks |
| **`Ctrl+D`** | Deselect all tracks |
| **`I`** | Invert selection |
| **`Left` / `Right`** | Switch focus between Tracks list and Format selector |
| **`Enter` / `D`** | Queue all selected tracks for download |
| **`Esc`** | Cancel and return to search |

---

### 📥 Download Queue Manager (`Ctrl+J`)
| Shortcut | Action |
| :--- | :--- |
| **`P`** | Pause selected download |
| **`R`** | Resume / Retry selected download |
| **`E`** | Edit format for selected task |
| **`C`** | Cancel active download |
| **`D` / `Delete`** | Delete task from queue |
| **`L`** | Toggle live stdout logs drawer |
| **`O` / `Enter`** | Open completed media file in default system player |
| **`F`** | Open destination folder in File Explorer / Finder |
| **`X`** | Clear all finished and cancelled tasks |

---

### 📚 Download History (`Ctrl+Y`)
| Shortcut | Action |
| :--- | :--- |
| **`/`** or **`Ctrl+F`** | Focus real-time filter input |
| **`Enter` / `O`** | Open media file in default player |
| **`F`** | Reveal file in Explorer / Finder |
| **`R`** | Re-download URL with format selector |
| **`D`** | Remove record from history |
| **`C`** | Clear entire download history |

---

### ⚙️ Settings Screen (`Ctrl+O`)
| Shortcut | Action |
| :--- | :--- |
| **`Up` / `Down`** | Navigate settings categories sidebar |
| **`Tab` / `Shift+Tab`** | Move focus between fields |
| **`Left` / `Right`** | Cycle dropdown / selector values |
| **`Ctrl+S`** | Save configuration |
| **`Ctrl+R`** | Reset configuration to default values |
| **`Ctrl+U`** | Self-update yt-dlp to latest upstream version |
| **`Esc`** | Discard unsaved changes and go back |

---

## 🍪 Cookies & Authentication (Windows / YouTube Guide)

For age-restricted, private, or subscriber-only videos, YouTube requires active account cookies.

### Why Direct Chrome Extraction Fails on Windows
1. **SQLite Database File Lock**: When Google Chrome is running on Windows, it holds an exclusive lock on its cookie database (`Network/Cookies`), preventing other applications from reading it.
2. **App-Bound Encryption (Chrome 127+)**: Recent versions of Chrome encrypt stored credentials with Windows App-Bound Encryption, blocking third-party process access.

### Recommended 100% Reliable Fix (`cookies.txt`):
1. Install an extension like **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** in Chrome or Firefox.
2. Open YouTube, click the extension icon, and click **Export**.
3. In **YTUI**, press **`Ctrl+O`** → **`Cookies & Auth`**.
4. Set **Browser Cookies** to `None (No Cookies)` and paste your file path into **`Custom Cookies.txt Path`** (e.g. `C:\Users\username\Downloads\youtube.com_cookies.txt`).
5. Click **`▶ Test Cookie Setup & Auth`** to verify login detection.

---

## ⚙️ Configuration

Configuration is automatically persisted to:
- **Windows**: `%APPDATA%\ytui\config.json`
- **Linux / macOS**: `~/.config/ytui/config.json`

### Sample `config.json`:
```json
{
  "download_dir": "C:\\Users\\user\\Downloads",
  "filename_template": "%(title)s [%(id)s].%(ext)s",
  "max_concurrent_downloads": 3,
  "rate_limit": "0",
  "retries": 10,
  "continuedl": true,
  "browser_cookies": "none",
  "cookies_file": "",
  "download_subtitles": false,
  "auto_generated_subtitles": false,
  "subtitle_mode": "embed",
  "subtitle_langs": "en",
  "download_thumbnail": false,
  "thumbnail_mode": "embed",
  "embed_chapters": false,
  "split_chapters": false,
  "remove_sponsor_segments": false,
  "sponsorblock_categories": "sponsor,selfpromo",
  "embed_metadata": true,
  "proxy": "",
  "geo_bypass": true,
  "theme": "shadcn-zinc",
  "rtl_mode": "reshaped_bidi"
}
```

---

## 📦 Building Standalone Executable (.exe)

You can package the entire application into a standalone Windows binary without requiring Python to be installed on target machines:

### Option 1: One-Click Build Script (Windows)
```cmd
.\build.bat
```

### Option 2: Command Line
```bash
pip install -r requirements.txt
pyinstaller --noconfirm --clean yt-dlp-tui.spec
```

The resulting standalone executable will be exported to:
```
dist/yt-dlp-tui.exe
```

---

## 🧪 Running Tests


The test suite covers configuration management, yt-dlp format extraction, download queue management, Arabic/RTL text rendering, and asynchronous Textual UI screens:

```bash
python -m pytest tests/ -v
```

---

## 🛠️ Built With

- **[Textual](https://textual.textualize.io/)**: Modern async TUI application framework for Python.
- **[Rich](https://rich.readthedocs.io/)**: Terminal formatting, tables, styled markup, and rendering.
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**: Feature-rich command-line audio/video downloader.
- **[arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper)** & **[python-bidi](https://github.com/MeirKriheli/python-bidi)**: Advanced Right-to-Left (RTL) text shaping.
- **[mutagen](https://github.com/quodlibet/mutagen)**: Native audio & video tag and artwork embedding.

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <sub>Built with ❤️ for terminal power users. Star ⭐ this repository if you find it useful!</sub>
</div>
