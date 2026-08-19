"""Asynchronous concurrent download queue and network resilience manager."""

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yt_dlp

from config import AppConfig, get_config_dir
from history import HistoryItem, HistoryManager
from ytdlp_engine import YOUTUBE_CLIENT_FALLBACKS, YtDlpEngine, format_bytes


class DownloadStatus(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    MERGING = "MERGING"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass
class DownloadTask:
    """A download job in the manager queue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    title: str = "Loading..."
    uploader: str = "Unknown"
    duration_str: str = "--:--"
    video_format: str = "bestvideo"
    video_format_label: str = ""  # Human-readable label, e.g. "1080p60 (FHD)"
    audio_format: str = "bestaudio"
    audio_format_label: str = ""  # Human-readable label, e.g. "256 kbps (Best)"
    audio_quality: str = "256"  # Quality / bitrate, e.g. "256", "320", "192", "128", "V0"
    container: str = "mp4"
    video_ext: str = ""
    video_codec: str = ""
    audio_ext: str = ""
    audio_codec: str = ""

    status: DownloadStatus = DownloadStatus.QUEUED
    progress_percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_str: str = "--"
    eta_str: str = "--"
    error_message: str = ""
    output_filepath: str = ""

    # Pre-estimated stream sizes for accurate combined progress tracking
    video_filesize: int = 0  # Known/estimated video stream bytes
    audio_filesize: int = 0  # Known/estimated audio stream bytes
    estimated_total_bytes: int = 0  # Combined estimated total across all streams

    logs: List[str] = field(default_factory=list)
    retry_count: int = 0
    is_cancelled: bool = False
    is_paused: bool = False

    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def add_log(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        lock = getattr(self, "_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._lock = lock
        with lock:
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] {clean}")
            if len(self.logs) > 300:
                self.logs = self.logs[-300:]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloadTask":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        status_val = filtered.get("status", "QUEUED")
        try:
            filtered["status"] = DownloadStatus(status_val)
        except ValueError:
            filtered["status"] = DownloadStatus.QUEUED
        return cls(**filtered)


class TaskLogger:
    """Logger hook for yt-dlp to route task logs into DownloadTask with error detection."""

    def __init__(self, task: DownloadTask):
        self.task = task
        self.errors: List[str] = []
        self.has_fatal_error = False

    def debug(self, msg: str) -> None:
        clean = msg.strip()
        if clean:
            self.task.add_log(clean)

    def info(self, msg: str) -> None:
        clean = msg.strip()
        if clean:
            self.task.add_log(clean)

    def warning(self, msg: str) -> None:
        clean = msg.strip()
        if clean:
            prefix = "" if clean.upper().startswith("WARNING:") else "WARNING: "
            self.task.add_log(f"{prefix}{clean}")

    def error(self, msg: str) -> None:
        clean = msg.strip()
        if clean:
            prefix = "" if clean.upper().startswith("ERROR:") else "ERROR: "
            self.task.add_log(f"{prefix}{clean}")
            # Strip redundant ERROR: prefixes for clean message
            err_text = clean
            while err_text.upper().startswith("ERROR:") or err_text.upper().startswith("ERROR :"):
                err_text = err_text.split(":", 1)[1].strip()

            err_lower = err_text.lower()
            # Non-fatal cookie copy/database warnings should not fail the entire stream validation if stream succeeded
            is_cookie_warning = any(c in err_lower for c in [
                "could not copy chrome cookie", "could not copy", "cookie database",
                "failed to decrypt with dpapi", "failed to load cookies", "cookie database is locked"
            ])
            if not is_cookie_warning:
                self.errors.append(err_text)
                if any(k in err_lower for k in ["http error", "403", "forbidden", "unable to download", "fatal", "download error"]):
                    self.has_fatal_error = True


class DownloadManager:
    """Singleton-style download manager orchestrating concurrent workers, persistence, and auto-resumes."""

    _instance: Optional["DownloadManager"] = None

    @classmethod
    def get_instance(
        cls,
        config: Optional[AppConfig] = None,
        history: Optional[HistoryManager] = None,
        queue_path: Optional[Path] = None,
    ) -> "DownloadManager":
        if cls._instance is None:
            cls._instance = cls(
                config=config or AppConfig.load(),
                history=history or HistoryManager(),
                queue_path=queue_path,
            )
        return cls._instance

    def __init__(
        self,
        config: AppConfig,
        history: HistoryManager,
        queue_path: Optional[Path] = None,
        auto_start_worker: bool = True,
    ):
        self.config = config
        self.history = history
        self.queue_path = queue_path or (get_config_dir() / "queue.json")
        self.auto_start_worker = auto_start_worker
        self.tasks: List[DownloadTask] = []
        self._lock = threading.Lock()
        self._listeners: List[Callable[[], None]] = []
        self._worker_thread: Optional[threading.Thread] = None
        self._running = True
        self._last_save_time = 0.0

        # Load persisted queue from disk
        self._load_tasks()

        if self.auto_start_worker:
            self._start_worker()

    def _load_tasks(self) -> None:
        """Load persistent download queue from disk."""
        if not self.queue_path.exists():
            self.tasks = []
            return
        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded: List[DownloadTask] = []
            for item in data:
                task = DownloadTask.from_dict(item)
                # If task was actively downloading or merging when app was exited, mark as INTERRUPTED
                if task.status in [DownloadStatus.DOWNLOADING, DownloadStatus.MERGING]:
                    task.status = DownloadStatus.INTERRUPTED
                    task.speed_str = "--"
                    task.eta_str = "--"
                    task.add_log("[Session Restored] Task interrupted when app closed. Press 'r' to resume.")
                loaded.append(task)
            self.tasks = loaded
        except Exception as e:
            print(f"Warning: Could not load download queue: {e}", file=sys.stderr)
            self.tasks = []

    def _save_tasks(self) -> None:
        """Save download queue to disk atomically."""
        try:
            with self._lock:
                tasks_data = [t.to_dict() for t in self.tasks]
                self.queue_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.queue_path.with_suffix(f".tmp.{os.getpid()}_{threading.get_ident()}")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(tasks_data, f, indent=2)
                os.replace(temp_path, self.queue_path)
                self._last_save_time = time.time()
        except Exception as e:
            print(f"Warning: Could not save download queue: {e}", file=sys.stderr)

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register UI callback for state changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def enqueue(self, task: DownloadTask) -> None:
        with self._lock:
            self.tasks.append(task)
            task.add_log(f"Queued download for '{task.title}'")
        self._save_tasks()
        if self.auto_start_worker:
            self._start_worker()
        self._notify()

    def enqueue_many(self, tasks: List[DownloadTask]) -> None:
        """Enqueue multiple tasks atomically in strict sequential order."""
        if not tasks:
            return
        with self._lock:
            for task in tasks:
                self.tasks.append(task)
                task.add_log(f"Queued playlist download for '{task.title}'")
        self._save_tasks()
        if self.auto_start_worker:
            self._start_worker()
        self._notify()

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    return t
        return None

    def pause_task(self, task_id: str) -> None:
        updated = False
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED]:
                        t.is_paused = True
                        t.status = DownloadStatus.PAUSED
                        t.add_log("Download paused by user")
                        updated = True
                    break
        if updated:
            self._save_tasks()
            self._notify()

    def resume_task(self, task_id: str) -> None:
        updated = False
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    if t.status in [DownloadStatus.PAUSED, DownloadStatus.INTERRUPTED, DownloadStatus.ERROR, DownloadStatus.CANCELLED]:
                        t.is_paused = False
                        t.is_cancelled = False
                        t.status = DownloadStatus.QUEUED
                        t.error_message = ""
                        t.add_log("Resuming download from byte offset...")
                        updated = True
                    break
        if updated:
            self._save_tasks()
            self._notify()

    def cancel_task(self, task_id: str) -> None:
        updated = False
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.is_cancelled = True
                    t.status = DownloadStatus.CANCELLED
                    t.add_log("Download cancelled by user")
                    updated = True
                    break
        if updated:
            self._save_tasks()
            self._notify()

    def retry_task(self, task_id: str) -> None:
        updated = False
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.is_cancelled = False
                    t.is_paused = False
                    t.status = DownloadStatus.QUEUED
                    t.error_message = ""
                    t.add_log("Retrying download...")
                    updated = True
                    break
        if updated:
            self._save_tasks()
            self._notify()

    def delete_task(self, task_id: str) -> None:
        """Remove a task from the download queue completely."""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self._save_tasks()
        self._notify()

    def clear_completed(self) -> None:
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status not in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED]]
        self._save_tasks()
        self._notify()

    def _start_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Main dispatcher loop."""
        while self._running:
            next_task: Optional[DownloadTask] = None
            with self._lock:
                active_count = sum(1 for t in self.tasks if t.status == DownloadStatus.DOWNLOADING)
                max_concurrent = max(1, self.config.max_concurrent_downloads)

                if active_count < max_concurrent:
                    for t in self.tasks:
                        if t.status == DownloadStatus.QUEUED and not t.is_paused and not t.is_cancelled:
                            next_task = t
                            t.status = DownloadStatus.DOWNLOADING
                            t.add_log("Worker picked up task. Initializing yt-dlp...")
                            break

            if next_task:
                self._save_tasks()
                self._notify()
                thread = threading.Thread(target=self._execute_download, args=(next_task,), daemon=True)
                thread.start()

            time.sleep(0.3)

    def _execute_download(self, task: DownloadTask) -> None:
        """Execute a single download task using yt-dlp with network resilience & resume."""
        task.status = DownloadStatus.DOWNLOADING

        # Track multi-stream downloads (video+audio fires "finished" once per stream)
        is_multi_stream = (task.video_format != "none" and task.audio_format != "none")
        v_label = task.video_format_label or task.video_format or "Video"
        a_label = task.audio_format_label or task.audio_format or "Audio"

        stream_state = {
            "finished_count": 0,
            "expected_streams": 2 if is_multi_stream else 1,
            "completed_bytes": 0,       # bytes from already-finished streams
            "completed_total": 0,       # total bytes from already-finished streams
        }
        _last_progress_notify_time = 0.0

        def get_current_failing_format_label() -> str:
            """Identify specifically which format (video vs audio) is being processed when a failure occurs."""
            if is_multi_stream:
                # yt-dlp downloads video stream first (stream 1), audio stream second (stream 2)
                if stream_state["finished_count"] == 0:
                    return f"Video format ({v_label})"
                else:
                    return f"Audio format ({a_label})"
            elif task.video_format == "none":
                return f"Audio format ({a_label})"
            elif task.audio_format == "none":
                return f"Video format ({v_label})"
            else:
                return f"Stream format ({v_label})"

        def progress_hook(d: Dict[str, Any]) -> None:
            nonlocal _last_progress_notify_time
            if task.is_cancelled or task.is_paused:
                raise yt_dlp.utils.DownloadCancelled("Task paused or cancelled")

            status_str = d.get("status")
            if status_str == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0

                # For multi-stream: calculate progress against the combined total of all streams
                combined_downloaded = stream_state["completed_bytes"] + downloaded
                combined_total = stream_state["completed_total"] + total

                # Use pre-estimated total when we haven't seen all streams yet.
                # This prevents the progress bar from showing 0-100% for just the first stream.
                if is_multi_stream and task.estimated_total_bytes > 0:
                    # Once we have real totals from ALL finished streams + current, prefer actual data.
                    # But during stream 1, completed_total is 0 so combined_total is just stream 1's size.
                    # Use the larger of (estimated total, actual combined total) as the denominator
                    # so progress reflects the full download, not just the current stream.
                    effective_total = max(task.estimated_total_bytes, combined_total)
                else:
                    effective_total = combined_total

                task.total_bytes = effective_total
                task.downloaded_bytes = combined_downloaded
                if effective_total > 0:
                    task.progress_percent = min(99.9, (combined_downloaded / effective_total) * 100.0)

                if speed:
                    task.speed_str = f"{format_bytes(int(speed))}/s"

                # Adjust ETA to reflect remaining bytes across ALL streams, not just current
                if speed and speed > 0 and effective_total > 0:
                    remaining_bytes = max(0, effective_total - combined_downloaded)
                    adjusted_eta = int(remaining_bytes / speed)
                    m, s = divmod(adjusted_eta, 60)
                    task.eta_str = f"{m:02d}:{s:02d}"
                elif eta is not None:
                    m, s = divmod(int(eta), 60)
                    task.eta_str = f"{m:02d}:{s:02d}"

                task.status = DownloadStatus.DOWNLOADING

                now = time.time()
                # Throttle disk saves to once per 5 seconds during active downloads
                if now - self._last_save_time > 5.0:
                    self._save_tasks()

                # UI Event-Loop Throttling: at most once every ~120-150ms during continuous byte downloads
                if now - _last_progress_notify_time >= 0.125:
                    _last_progress_notify_time = now
                    self._notify()

            elif status_str == "finished":
                # Accumulate bytes from the stream that just finished
                finished_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                finished_downloaded = d.get("downloaded_bytes") or finished_total
                stream_state["finished_count"] += 1
                stream_state["completed_bytes"] += finished_downloaded
                stream_state["completed_total"] += finished_total

                if stream_state["finished_count"] >= stream_state["expected_streams"]:
                    # All streams done — now merging/postprocessing
                    task.status = DownloadStatus.MERGING
                    task.progress_percent = 100.0
                    task.speed_str = "--"
                    task.eta_str = "Merging..."
                    task.add_log("All streams downloaded. Merging & processing output...")
                else:
                    # More streams to go — update progress but stay in DOWNLOADING
                    stream_label = f"Stream {stream_state['finished_count']}/{stream_state['expected_streams']}"
                    task.add_log(f"{stream_label} finished ({format_bytes(finished_downloaded)}). Downloading next stream...")
                    # Calculate progress using the best total estimate available
                    effective_total = max(task.estimated_total_bytes, stream_state["completed_total"]) if task.estimated_total_bytes > 0 else stream_state["completed_total"]
                    if effective_total > 0:
                        task.progress_percent = min(99.9, (stream_state["completed_bytes"] / effective_total) * 100.0)
                self._notify()

        def postprocessor_hook(d: Dict[str, Any]) -> None:
            status_str = d.get("status")
            if status_str == "finished":
                info = d.get("info_dict", {})
                filepath = info.get("filepath") or info.get("_filename") or ""
                if filepath:
                    task.output_filepath = filepath

        logger = TaskLogger(task)
        opts = YtDlpEngine.build_download_options(
            config=self.config,
            video_format_id=task.video_format,
            audio_format_id=task.audio_format,
            target_container=task.container,
            audio_quality=task.audio_quality,
            progress_hook=progress_hook,
            postprocessor_hook=postprocessor_hook,
            logger=logger,
            video_ext=task.video_ext,
            video_codec=task.video_codec,
            audio_ext=task.audio_ext,
            audio_codec=task.audio_codec,
        )

        task.container = opts.get("merge_output_format", task.container)

        is_audio_only = (task.video_format == "none")

        try:
            task.add_log(f"Starting download: {task.url}")
            extract_res = None
            active_ydl = None

            def _try_download(current_opts: Dict[str, Any]) -> Tuple[Optional[Any], Optional[Any], Optional[Exception]]:
                nonlocal active_ydl
                logger.errors.clear()
                logger.has_fatal_error = False
                try:
                    with yt_dlp.YoutubeDL(current_opts) as ydl:
                        active_ydl = ydl
                        res = ydl.extract_info(task.url, download=True)
                        if any(k in " ".join(logger.errors).lower() for k in ["403", "forbidden"]):
                            return res, active_ydl, yt_dlp.utils.DownloadError("Stream returned HTTP 403 Forbidden")
                        return res, active_ydl, None
                except Exception as ex:
                    return None, active_ydl, ex

            extract_res, active_ydl, download_err = _try_download(opts)

            # If failed due to locked browser cookies, retry download once without cookies
            if download_err and ("cookiesfrombrowser" in opts or "cookiefile" in opts) and not task.is_cancelled and not task.is_paused:
                task.add_log("Notice: Browser cookies locked or unavailable. Retrying download without cookies...")
                opts_no_cookies = dict(opts)
                opts_no_cookies.pop("cookiesfrombrowser", None)
                opts_no_cookies.pop("cookiefile", None)
                extract_res, active_ydl, download_err = _try_download(opts_no_cookies)

            # If 403 Forbidden occurred, cycle through alternative YouTube player clients
            if download_err and not task.is_cancelled and not task.is_paused:
                err_str = str(download_err).lower()
                is_403 = any(k in err_str for k in ["403", "forbidden"]) or any(k in " ".join(logger.errors).lower() for k in ["403", "forbidden"])
                if is_403:
                    failing_label = get_current_failing_format_label()
                    for client_set in YtDlpEngine.YOUTUBE_CLIENT_FALLBACKS[1:]:
                        if task.is_cancelled or task.is_paused:
                            break
                        client_desc = ", ".join(client_set)
                        task.add_log(f"Notice: HTTP 403 Forbidden on {failing_label}. Retrying with {client_desc} client fallback...")
                        opts_fallback = dict(opts)
                        opts_fallback["extractor_args"] = {
                            "youtube": {
                                "player_client": client_set,
                            }
                        }
                        extract_res, active_ydl, download_err = _try_download(opts_fallback)
                        if not download_err and not logger.has_fatal_error:
                            break

            if download_err and not task.is_cancelled and not task.is_paused:
                raise download_err

            if extract_res and active_ydl:
                filename = active_ydl.prepare_filename(extract_res)
                task.output_filepath = YtDlpEngine.resolve_output_filepath(
                    filename,
                    container=task.container,
                    is_audio_only=is_audio_only,
                )

            if task.is_cancelled:
                task.status = DownloadStatus.CANCELLED
            elif task.is_paused:
                task.status = DownloadStatus.PAUSED
            else:
                # Strict multi-layer validation before marking COMPLETED
                download_valid = True
                incomplete_reason = ""

                # Verification 1: Check if logger recorded fatal stream error
                if logger.has_fatal_error or logger.errors:
                    raw_err = logger.errors[-1] if logger.errors else "Stream error"
                    download_valid = False
                    incomplete_reason = f"{get_current_failing_format_label()} failed: {raw_err}"

                # Verification 2: Multi-stream completion (both streams must finish)
                if download_valid and is_multi_stream and stream_state["finished_count"] < stream_state["expected_streams"]:
                    download_valid = False
                    failing_fmt = get_current_failing_format_label()
                    incomplete_reason = f"{failing_fmt} download incomplete (finished {stream_state['finished_count']}/{stream_state['expected_streams']} streams)"

                # Verification 3: Output file must exist on disk and have non-zero size
                out_path = Path(task.output_filepath) if task.output_filepath else None
                if download_valid:
                    if not out_path or not out_path.exists() or not out_path.is_file() or out_path.stat().st_size == 0:
                        download_valid = False
                        failing_fmt = get_current_failing_format_label()
                        incomplete_reason = f"{failing_fmt} output file was not created or is empty"

                # Verification 4: Downloaded bytes vs total bytes
                if download_valid and task.total_bytes > 0 and task.downloaded_bytes > 0:
                    completion_ratio = task.downloaded_bytes / task.total_bytes
                    if completion_ratio < 0.95:
                        download_valid = False
                        pct = completion_ratio * 100
                        incomplete_reason = (
                            f"{get_current_failing_format_label()}: only {format_bytes(task.downloaded_bytes)} of "
                            f"{format_bytes(task.total_bytes)} downloaded ({pct:.1f}%)"
                        )

                if download_valid:
                    task.status = DownloadStatus.COMPLETED
                    task.progress_percent = 100.0
                    task.speed_str = "Done"
                    task.eta_str = "Complete"
                    task.error_message = ""
                    task.add_log(f"Successfully saved: {task.output_filepath}")

                    # Record in history
                    filesize = 0
                    if task.output_filepath and Path(task.output_filepath).exists():
                        try:
                            filesize = Path(task.output_filepath).stat().st_size
                        except Exception:
                            pass
                    if filesize == 0:
                        filesize = task.total_bytes

                    self.history.add(
                        HistoryItem(
                            id=task.id,
                            title=task.title,
                            url=task.url,
                            channel=task.uploader,
                            duration_str=task.duration_str,
                            filepath=task.output_filepath,
                            filesize_bytes=filesize,
                            format_note=f"{task.video_format_label or task.video_format} + {task.audio_format_label or task.audio_format} ({task.container})",
                        )
                    )
                else:
                    task.status = DownloadStatus.ERROR
                    task.error_message = incomplete_reason
                    task.speed_str = "--"
                    task.eta_str = "--"
                    task.add_log(f"Download failed: {incomplete_reason}. Press 'R' to retry or 'E' to select a different format.")

        except yt_dlp.utils.DownloadCancelled:
            if task.is_paused:
                task.status = DownloadStatus.PAUSED
                task.add_log("Download paused. Progress preserved.")
            else:
                task.status = DownloadStatus.CANCELLED
                task.add_log("Download cancelled.")

        except Exception as err:
            err_msg = str(err)
            while err_msg.upper().startswith("ERROR:") or err_msg.upper().startswith("ERROR :"):
                err_msg = err_msg.split(":", 1)[1].strip()

            if task.is_paused:
                task.status = DownloadStatus.PAUSED
                task.add_log("Download paused by user.")
            elif task.is_cancelled:
                task.status = DownloadStatus.CANCELLED
                task.add_log("Download cancelled by user.")
            else:
                failing_fmt = get_current_failing_format_label()
                formatted_err = f"{failing_fmt} error: {err_msg}"
                if any(k in err_msg.lower() for k in ["403", "forbidden", "sign in", "private video", "members-only"]):
                    if self.config.browser_cookies == "chrome":
                        formatted_err += " (Notice: Chrome cookies are locked while Chrome is open on Windows. Export cookies to a cookies.txt file in Config -> Cookies & Auth)"
                task.status = DownloadStatus.ERROR
                task.error_message = formatted_err
                task.speed_str = "--"
                task.eta_str = "--"
                task.add_log(f"Error: {formatted_err}. Press 'R' to retry or 'E' to select a different format.")

        self._save_tasks()
        self._notify()

    def shutdown(self) -> None:
        self._running = False
        self._save_tasks()
