"""Concurrent download queue with persistence, pause/resume, and network resilience."""

import itertools
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config import AppConfig, atomic_json_save, get_config_dir, load_json_or_backup
from .formats import format_bytes, format_duration
from .history import HistoryItem, HistoryManager
from .ytdlp_engine import YtDlpEngine

MAX_TASK_LOGS = 300
SAVE_INTERVAL = 5.0  # seconds between queue saves during active downloads


class DownloadStatus(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    MERGING = "MERGING"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


ACTIVE_STATUSES = (DownloadStatus.DOWNLOADING, DownloadStatus.MERGING)
RESUMABLE_STATUSES = (DownloadStatus.PAUSED, DownloadStatus.INTERRUPTED, DownloadStatus.ERROR, DownloadStatus.CANCELLED)


@dataclass
class DownloadTask:
    """A download job in the queue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    title: str = "Loading..."
    uploader: str = "Unknown"
    duration_str: str = "--:--"
    video_format: str = "bestvideo"
    video_format_label: str = ""  # e.g. "1080p60 (FHD)"
    audio_format: str = "bestaudio"
    audio_format_label: str = ""  # e.g. "256 kbps (Best)"
    audio_quality: str = "256"  # export bitrate: "256", "320", "192", "128", "V0"
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

    # Pre-estimated stream sizes so a video+audio download shows one combined progress bar
    video_filesize: int = 0
    audio_filesize: int = 0
    estimated_total_bytes: int = 0

    logs: List[str] = field(default_factory=list)
    log_total: int = 0  # lines ever logged; lets the UI append only new lines
    retry_count: int = 0
    is_cancelled: bool = False
    is_paused: bool = False

    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self.log_total = max(self.log_total, len(self.logs))
        # Set by pause/cancel/delete, cleared only when a new run starts. Unlike is_paused it survives
        # a quick resume, so a still-running old thread always stops. Not persisted.
        self.stop_requested = False

    @property
    def is_audio_only(self) -> bool:
        return self.video_format == "none"

    def add_log(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        with self._lock:
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] {clean}")
            self.log_total += 1
            if len(self.logs) > MAX_TASK_LOGS:
                del self.logs[: len(self.logs) - MAX_TASK_LOGS]

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            data = {f.name: getattr(self, f.name) for f in fields(self)}
            data["logs"] = list(self.logs)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloadTask":
        names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in names}
        try:
            filtered["status"] = DownloadStatus(filtered.get("status", "QUEUED"))
        except ValueError:
            filtered["status"] = DownloadStatus.QUEUED
        return cls(**filtered)


class TaskLogger:
    """yt-dlp logger that routes messages into a task and records fatal errors."""

    _NON_FATAL = (
        "could not copy", "cookie database", "failed to decrypt with dpapi", "failed to load cookies",
        "sponsorblock", "thumbnail", "mutagen", "atomicparsley", "metadata",
        "retrying fragment", "retrying (", "unable to download video subtitles",
        "unable to download subtitles", "postprocessing",
    )
    _FATAL = ("http error", "403", "forbidden", "unable to download", "fatal", "download error", "requested format is not available")

    def __init__(self, task: DownloadTask):
        self.task = task
        self.errors: List[str] = []
        self.has_fatal_error = False

    def reset(self) -> None:
        self.errors.clear()
        self.has_fatal_error = False

    def debug(self, msg: str) -> None:
        self.task.add_log(msg)

    info = debug

    def warning(self, msg: str) -> None:
        clean = msg.strip()
        if clean:
            self.task.add_log(clean if clean.upper().startswith("WARNING:") else f"WARNING: {clean}")

    def error(self, msg: str) -> None:
        clean = msg.strip()
        if not clean:
            return
        self.task.add_log(clean if clean.upper().startswith("ERROR:") else f"ERROR: {clean}")
        err_text = strip_error_prefix(clean)
        err_lower = err_text.lower()
        # Postprocessor notices and cookie warnings must not fail a download whose stream succeeded.
        if not any(k in err_lower for k in self._NON_FATAL):
            self.errors.append(err_text)
            if any(k in err_lower for k in self._FATAL):
                self.has_fatal_error = True


def strip_error_prefix(text: str) -> str:
    while text.upper().startswith(("ERROR:", "ERROR :")):
        text = text.split(":", 1)[1].strip()
    return text


class DownloadManager:
    """Runs queued tasks on worker threads (up to config.max_concurrent_downloads) and persists the queue.

    The UI polls `version`, which changes on every state change; download threads never wait on the UI.
    """

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
        self.version = 0
        self._versions = itertools.count(1)
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()
        self._running: Set[str] = set()
        self._stopped = False
        self._last_save_time = 0.0
        self._load_tasks()
        if self.auto_start_worker:
            self.dispatch()

    # ------------------------------------------------------------------ persistence

    def _load_tasks(self) -> None:
        data = load_json_or_backup(self.queue_path)
        loaded: List[DownloadTask] = []
        for item in data if isinstance(data, list) else []:
            try:
                task = DownloadTask.from_dict(item)
            except (TypeError, AttributeError):
                continue
            if task.status in ACTIVE_STATUSES:
                task.status = DownloadStatus.INTERRUPTED
                task.speed_str = task.eta_str = "--"
                task.add_log("[Session Restored] Task interrupted when app closed. Press 'r' to resume.")
            loaded.append(task)
        self.tasks = loaded

    def _save_tasks(self) -> None:
        """Snapshot under the queue lock, write outside it so the UI never waits on disk I/O."""
        with self._lock:
            tasks_data = [t.to_dict() for t in self.tasks]
        try:
            with self._save_lock:
                atomic_json_save(self.queue_path, tasks_data, indent=None)
                self._last_save_time = time.monotonic()
        except Exception as e:
            print(f"Warning: Could not save download queue: {e}", file=sys.stderr)

    def _touch(self) -> None:
        self.version = next(self._versions)

    def _changed(self) -> None:
        self._touch()
        self._save_tasks()

    # ------------------------------------------------------------------ queue operations

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return next((t for t in self.tasks if t.id == task_id), None)

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running

    def enqueue(self, task: DownloadTask) -> None:
        self.enqueue_many([task])

    def enqueue_many(self, tasks: List[DownloadTask]) -> None:
        """Append tasks in the given order (playlists rely on this)."""
        if not tasks:
            return
        with self._lock:
            for task in tasks:
                self.tasks.append(task)
                task.add_log(f"Queued download for '{task.title}'")
        self._changed()
        self._maybe_dispatch()

    def pause_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.get_task(task_id)
            if not task or task.status not in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED):
                return False
            task.is_paused = task.stop_requested = True
            task.status = DownloadStatus.PAUSED
            task.speed_str = task.eta_str = "--"
            task.add_log("Download paused by user")
        self._changed()
        return True

    def resume_task(self, task_id: str) -> bool:
        return self._requeue(task_id, RESUMABLE_STATUSES, "Resuming download from byte offset...")

    def retry_task(self, task_id: str) -> bool:
        return self._requeue(task_id, tuple(DownloadStatus), "Retrying download...")

    def requeue_with(self, task_id: str, **changes: Any) -> bool:
        """Change a task's formats and queue it again. Refused while the task is still running."""
        with self._lock:
            task = self.get_task(task_id)
            if not task or self.is_running(task_id):
                return False
            for name, value in changes.items():
                setattr(task, name, value)
        return self._requeue(task_id, tuple(DownloadStatus), f"Format updated to {task.video_format}+{task.audio_format} ({task.container}). Re-queued.")

    def _requeue(self, task_id: str, allowed: tuple, message: str) -> bool:
        with self._lock:
            task = self.get_task(task_id)
            if not task or task.status not in allowed or task.status in ACTIVE_STATUSES:
                return False
            task.is_paused = task.is_cancelled = False
            task.status = DownloadStatus.QUEUED
            task.error_message = ""
            task.add_log(message)
        self._changed()
        self._maybe_dispatch()
        return True

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.get_task(task_id)
            if not task or task.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED):
                return False
            task.is_cancelled = task.stop_requested = True
            task.status = DownloadStatus.CANCELLED
            task.speed_str = task.eta_str = "--"
            task.add_log("Download cancelled by user")
        self._changed()
        return True

    def delete_task(self, task_id: str) -> None:
        """Remove a task; a running download is told to stop at its next progress tick."""
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.is_cancelled = t.stop_requested = True
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self._changed()

    def clear_completed(self) -> None:
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status not in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED)]
        self._changed()

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._touch()
        self._maybe_dispatch()  # concurrency limit may have grown

    # ------------------------------------------------------------------ scheduling

    def _maybe_dispatch(self) -> None:
        if self.auto_start_worker:
            self.dispatch()

    def dispatch(self) -> None:
        """Start queued tasks while worker slots are free. Called on every state change that may free a slot."""
        started = []
        with self._lock:
            if self._stopped:
                return
            limit = max(1, self.config.max_concurrent_downloads)
            for task in self.tasks:
                if len(self._running) >= limit:
                    break
                # A paused/re-queued task may still be winding down; never run it twice at once.
                if task.status == DownloadStatus.QUEUED and task.id not in self._running:
                    task.status = DownloadStatus.DOWNLOADING
                    task.stop_requested = False
                    task.add_log("Worker picked up task. Initializing yt-dlp...")
                    self._running.add(task.id)
                    started.append(task)
        if started:
            self._changed()
        for task in started:
            threading.Thread(target=self._run_task, args=(task,), daemon=True, name=f"download-{task.id}").start()

    def _run_task(self, task: DownloadTask) -> None:
        try:
            self._execute_download(task)
        except Exception as e:  # never let a crashed worker hold its slot
            task.status = DownloadStatus.ERROR
            task.error_message = f"Internal error: {e}"
            task.add_log(task.error_message)
        finally:
            with self._lock:
                self._running.discard(task.id)
            self._changed()
            self.dispatch()

    # ------------------------------------------------------------------ download execution

    def _execute_download(self, task: DownloadTask) -> None:
        """Run one download with yt-dlp, updating task state as it progresses."""
        import yt_dlp

        is_multi_stream = task.video_format != "none" and task.audio_format != "none"
        expected_streams = 2 if is_multi_stream else 1
        finished = {"count": 0, "bytes": 0, "total": 0}  # streams already completed
        task.output_filepath = ""  # never mistake a previous run's file for this run's output

        def failing_stream_label() -> str:
            v_label = task.video_format_label or task.video_format or "Video"
            a_label = task.audio_format_label or task.audio_format or "Audio"
            if task.is_audio_only or (is_multi_stream and finished["count"] > 0):
                return f"Audio format ({a_label})"
            return f"Video format ({v_label})"

        def should_stop() -> bool:
            return task.stop_requested

        def progress_hook(d: Dict[str, Any]) -> None:
            if should_stop():
                raise yt_dlp.utils.DownloadCancelled("Task paused or cancelled")

            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = finished["bytes"] + (d.get("downloaded_bytes") or 0)
                combined_total = finished["total"] + total
                # While stream 1 downloads, the pre-estimate keeps the bar from reaching 100% early.
                effective_total = max(task.estimated_total_bytes, combined_total) if is_multi_stream else combined_total
                speed = d.get("speed") or 0
                task.total_bytes = effective_total
                task.downloaded_bytes = downloaded
                if effective_total > 0:
                    task.progress_percent = min(99.9, downloaded / effective_total * 100.0)
                if speed:
                    task.speed_str = f"{format_bytes(speed)}/s"
                    if effective_total > 0:
                        task.eta_str = format_duration(max(0, effective_total - downloaded) / speed)
                elif d.get("eta") is not None:
                    task.eta_str = format_duration(d["eta"])

                self._touch()
                if time.monotonic() - self._last_save_time > SAVE_INTERVAL:
                    self._save_tasks()

            elif d.get("status") == "finished":
                stream_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                finished["count"] += 1
                finished["bytes"] += d.get("downloaded_bytes") or stream_total
                finished["total"] += stream_total
                if finished["count"] >= expected_streams:
                    task.status = DownloadStatus.MERGING
                    task.progress_percent = 100.0
                    task.speed_str = "--"
                    task.eta_str = "Merging..."
                    task.add_log("All streams downloaded. Merging & processing output...")
                else:
                    task.add_log(f"Stream {finished['count']}/{expected_streams} finished ({format_bytes(finished['bytes'])}). Downloading next stream...")
                self._touch()

        def postprocessor_hook(d: Dict[str, Any]) -> None:
            if d.get("status") == "finished":
                path = (d.get("info_dict") or {}).get("filepath") or ""
                if path:
                    task.output_filepath = path

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
            video_codec=task.video_codec,
            audio_codec=task.audio_codec,
        )

        def download(ydl: Any) -> tuple:
            logger.reset()
            info = ydl.extract_info(task.url, download=True)
            if any(k in " ".join(logger.errors).lower() for k in ("403", "forbidden")):
                raise yt_dlp.utils.DownloadError("Stream returned HTTP 403 Forbidden")
            return info, ydl

        try:
            task.add_log(f"Starting download: {task.url}")
            info, ydl = YtDlpEngine.run_with_fallbacks(opts, download, should_stop, lambda msg: task.add_log(f"Notice: {msg} [{failing_stream_label()}]"))
        except Exception as err:
            if should_stop():
                # pause/cancel already set the status; the task may even be re-queued by now
                task.add_log("Download stopped. Partial progress is kept for resuming.")
                return
            message = f"{failing_stream_label()} error: {strip_error_prefix(str(err))}"
            if any(k in message.lower() for k in ("403", "forbidden", "sign in", "private video", "members-only")) and self.config.browser_cookies == "chrome":
                message += " (Notice: Chrome locks its cookies while open on Windows. Export a cookies.txt file in Config -> Cookies & Auth)"
            self._fail(task, message)
            return

        if should_stop():  # cancelled while post-processing (no progress ticks there)
            return
        output = self._locate_output(task, info, ydl)
        if not output:
            if logger.errors:
                self._fail(task, f"{failing_stream_label()} failed: {logger.errors[-1]}")
            else:
                self._fail(task, f"{failing_stream_label()} output file was not created or is empty")
            return

        task.output_filepath = output
        task.status = DownloadStatus.COMPLETED
        task.progress_percent = 100.0
        task.speed_str = "Done"
        task.eta_str = "Complete"
        task.error_message = ""
        task.add_log(f"Successfully saved: {output}")
        self.history.add(
            HistoryItem(
                id=task.id,
                title=task.title,
                url=task.url,
                channel=task.uploader,
                duration_str=task.duration_str,
                filepath=output,
                filesize_bytes=Path(output).stat().st_size,
                format_note=f"{task.video_format_label or task.video_format} + {task.audio_format_label or task.audio_format} ({task.container})",
            )
        )

    @staticmethod
    def _locate_output(task: DownloadTask, info: Any, ydl: Any) -> str:
        """Final output file path, or '' if no non-empty file exists."""
        candidates = []
        if isinstance(info, dict):
            downloads = info.get("requested_downloads") or []
            if downloads and downloads[-1].get("filepath"):
                candidates.append(downloads[-1]["filepath"])
            try:
                candidates.append(YtDlpEngine.resolve_output_filepath(ydl.prepare_filename(info), container=task.container, is_audio_only=task.is_audio_only))
            except Exception:
                pass
        candidates.append(task.output_filepath)
        for path in candidates:
            try:
                if path and Path(path).is_file() and Path(path).stat().st_size > 0:
                    return str(path)
            except OSError:
                continue
        return ""

    def _fail(self, task: DownloadTask, message: str) -> None:
        task.status = DownloadStatus.ERROR
        task.error_message = message
        task.speed_str = task.eta_str = "--"
        task.add_log(f"Error: {message}. Press 'R' to retry or 'E' to select a different format.")

    def shutdown(self) -> None:
        """Stop starting new tasks and persist the queue. Running daemon threads die with the process."""
        self._stopped = True
        self._save_tasks()
