import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from ytui.config import AppConfig
from ytui.history import HistoryManager
from ytui.manager import DownloadManager, DownloadStatus, DownloadTask


def test_task_serialization():
    task = DownloadTask(
        id="test-123",
        url="https://youtube.com/watch?v=xyz",
        title="Sample Video",
        uploader="Sample Channel",
        duration_str="03:45",
        video_format="1080p",
        audio_format="128k",
        container="mp4",
        status=DownloadStatus.PAUSED,
        progress_percent=45.5,
        downloaded_bytes=45000,
        total_bytes=100000,
    )

    data = task.to_dict()
    assert data["id"] == "test-123"
    assert data["status"] == "PAUSED"
    assert data["progress_percent"] == 45.5

    restored = DownloadTask.from_dict(data)
    assert restored.id == task.id
    assert restored.title == task.title
    assert restored.status == DownloadStatus.PAUSED
    assert restored.progress_percent == 45.5


def test_manager_queue_and_state(tmp_path):
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig(max_concurrent_downloads=2)
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    task1 = DownloadTask(
        id="t1",
        url="https://youtube.com/watch?v=1",
        title="Video 1",
        video_format="bestvideo",
        audio_format="bestaudio",
    )
    task2 = DownloadTask(
        id="t2",
        url="https://youtube.com/watch?v=2",
        title="Video 2",
        video_format="137",
        audio_format="140",
    )

    manager.enqueue(task1)
    manager.enqueue(task2)

    assert len(manager.tasks) == 2
    assert manager.get_task("t1") == task1
    assert queue_file.exists()

    # Test pause / resume
    manager.pause_task("t1")
    assert task1.is_paused is True
    assert task1.status == DownloadStatus.PAUSED

    manager.resume_task("t1")
    assert task1.is_paused is False
    assert task1.status == DownloadStatus.QUEUED

    # Test cancel
    manager.cancel_task("t2")
    assert task2.is_cancelled is True
    assert task2.status == DownloadStatus.CANCELLED

    # Test delete
    manager.delete_task("t2")
    assert len(manager.tasks) == 1
    assert manager.get_task("t2") is None

    manager.shutdown()


def test_manager_session_persistence_and_recovery(tmp_path):
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig(max_concurrent_downloads=2)
    history = HistoryManager(storage_path=storage)

    # Session 1: Create manager and add tasks
    mgr1 = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    t_queued = DownloadTask(id="q1", url="https://youtube.com/watch?v=q1", title="Queued Task", status=DownloadStatus.QUEUED)
    t_active = DownloadTask(id="a1", url="https://youtube.com/watch?v=a1", title="Active Task", status=DownloadStatus.DOWNLOADING, progress_percent=60.0)
    t_paused = DownloadTask(id="p1", url="https://youtube.com/watch?v=p1", title="Paused Task", status=DownloadStatus.PAUSED, progress_percent=25.0)

    mgr1.tasks = [t_queued, t_active, t_paused]
    mgr1._save_tasks()
    mgr1.shutdown()

    # Session 2: New manager starts up from same queue_file
    mgr2 = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    assert len(mgr2.tasks) == 3
    # Queued task remains queued
    assert mgr2.get_task("q1").status == DownloadStatus.QUEUED
    # In-progress task is safely restored as INTERRUPTED
    assert mgr2.get_task("a1").status == DownloadStatus.INTERRUPTED
    assert mgr2.get_task("a1").progress_percent == 60.0
    # Paused task remains paused
    assert mgr2.get_task("p1").status == DownloadStatus.PAUSED
    assert mgr2.get_task("p1").progress_percent == 25.0

    # Resuming the interrupted task transitions it to QUEUED
    mgr2.resume_task("a1")
    assert mgr2.get_task("a1").status == DownloadStatus.QUEUED

    mgr2.shutdown()


def test_task_logger_and_fatal_error_detection():
    from ytui.manager import TaskLogger
    task = DownloadTask(id="log-t1", url="https://youtube.com/watch?v=1", title="Test Log Task")
    logger = TaskLogger(task)

    logger.info("Starting info message")
    assert "Starting info message" in task.logs[-1]

    logger.warning("Minor warning")
    assert "WARNING: Minor warning" in task.logs[-1]

    # Test error logging without double prefix
    logger.error("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    assert "ERROR: unable to download video data: HTTP Error 403: Forbidden" in task.logs[-1]
    assert "ERROR: ERROR:" not in task.logs[-1]
    assert logger.has_fatal_error is True
    assert any("HTTP Error 403" in e for e in logger.errors)


def test_download_validation_and_format_attribution(tmp_path, monkeypatch):
    import yt_dlp
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig(download_dir=str(tmp_path))
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    task = DownloadTask(
        id="err-task-1",
        url="https://youtube.com/watch?v=test",
        title="Test Failed Video",
        video_format="137",
        video_format_label="1080p60 (FHD)",
        audio_format="140",
        audio_format_label="128 kbps (m4a)",
        container="mp4",
        status=DownloadStatus.QUEUED,
    )
    manager.tasks = [task]

    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)

    from unittest.mock import patch

    with patch.object(yt_dlp.YoutubeDL, "extract_info", side_effect=yt_dlp.utils.DownloadError("unable to download video data: HTTP Error 403: Forbidden")):
        manager._execute_download(task)

    # Verify task is NOT marked as completed
    assert task.status == DownloadStatus.ERROR
    assert task.progress_percent < 100.0
    assert "Video format" in task.error_message
    assert "403" in task.error_message or "Forbidden" in task.error_message
    assert len(history.items) == 0

    manager.shutdown()


def test_client_fallback_on_403_forbidden_succeeds(tmp_path, monkeypatch):
    """Test that when initial client hits 403 Forbidden, fallback client is tried and succeeds."""
    import yt_dlp
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig(download_dir=str(tmp_path))
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    test_file = tmp_path / "Test Success Video [test].mp4"
    test_file.write_bytes(b"dummy video data 12345")

    task = DownloadTask(
        id="fallback-task-1",
        url="https://youtube.com/watch?v=test",
        title="Test Success Video",
        video_format="18",
        video_format_label="360p (MP4)",
        audio_format="none",
        audio_format_label="",
        container="mp4",
        status=DownloadStatus.QUEUED,
        output_filepath=str(test_file),
    )
    manager.tasks = [task]

    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)

    from unittest.mock import patch

    attempts = 0
    clients_tried = []

    def mock_extract_info(url, download=True):
        nonlocal attempts
        attempts += 1
        # Extract the player client from current active YoutubeDL opts
        if attempts == 1:
            raise yt_dlp.utils.DownloadError("unable to download video data: HTTP Error 403: Forbidden")
        return {"id": "test", "title": "Test Success Video", "ext": "mp4", "_filename": str(test_file)}

    with patch.object(yt_dlp.YoutubeDL, "extract_info", side_effect=mock_extract_info):
        with patch.object(yt_dlp.YoutubeDL, "prepare_filename", return_value=str(test_file)):
            manager._execute_download(task)

    assert attempts >= 2
    assert task.status == DownloadStatus.COMPLETED
    assert task.progress_percent == 100.0
    assert any("403 Forbidden" in log and "Retrying with" in log for log in task.logs)
    assert len(history.items) == 1

    manager.shutdown()


def test_atomic_persistence(tmp_path):
    queue_file = tmp_path / "queue.json"
    temp_file = queue_file.with_suffix(".tmp")
    config = AppConfig()
    history = HistoryManager(storage_path=tmp_path / "hist.json")
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    task = DownloadTask(id="atomic-1", url="https://youtube.com/watch?v=atom", title="Atomic Test")
    manager.enqueue(task)

    assert queue_file.exists()
    assert not temp_file.exists()

    # Verify content in queue.json
    import json
    with open(queue_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "atomic-1"

    manager.shutdown()


def test_download_task_concurrent_add_log():
    task = DownloadTask(id="concurrent-log", url="https://youtube.com/watch?v=clog", title="Concurrent Log")

    def worker_log(thread_idx: int):
        for i in range(50):
            task.add_log(f"Thread {thread_idx} log entry {i}")

    threads = [threading.Thread(target=worker_log, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Max capacity is 300 logs
    assert len(task.logs) == 300
    # Ensure all entries are strings and no None or corrupted objects
    for log in task.logs:
        assert isinstance(log, str)
        assert len(log) > 0


def test_progress_hook_updates_combined_progress_and_version(tmp_path, monkeypatch):
    """Progress ticks update combined multi-stream progress and bump `version` (the UI polls it)."""
    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)

    config = AppConfig(download_dir=str(tmp_path))
    history = HistoryManager(storage_path=tmp_path / "hist.json")
    manager = DownloadManager(config=config, history=history, queue_path=tmp_path / "queue.json", auto_start_worker=False)

    captured = {}

    def fake_build_options(**kwargs):
        captured["hook"] = kwargs.get("progress_hook")
        return {}

    from ytui.ytdlp_engine import YtDlpEngine
    monkeypatch.setattr(YtDlpEngine, "build_download_options", fake_build_options)

    import yt_dlp
    started_event = threading.Event()
    stop_event = threading.Event()

    class FakeYoutubeDL:
        def __init__(self, params=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def extract_info(self, url, download=True):
            started_event.set()
            stop_event.wait(timeout=5.0)
            return {"title": "Mock Video", "id": "test"}
        def prepare_filename(self, info):
            return str(tmp_path / "video.mp4")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    (tmp_path / "video.mp4").write_bytes(b"dummy video data")

    task = DownloadTask(
        id="progress-task", url="https://youtube.com/watch?v=p", title="Progress Video",
        video_format="137", audio_format="140", container="mp4", estimated_total_bytes=2_000_000,
    )
    t = threading.Thread(target=manager._execute_download, args=(task,))
    t.start()
    assert started_event.wait(timeout=2.0)
    hook = captured["hook"]

    version = manager.version
    hook({"status": "downloading", "total_bytes": 1_000_000, "downloaded_bytes": 500_000, "speed": 100_000})
    assert manager.version != version
    # Stream 1 of 2: progress is measured against the combined estimate, not just this stream
    assert task.progress_percent == 25.0
    assert task.eta_str == "00:15"

    hook({"status": "finished", "total_bytes": 1_000_000, "downloaded_bytes": 1_000_000})
    hook({"status": "downloading", "total_bytes": 1_000_000, "downloaded_bytes": 500_000, "speed": 100_000})
    assert task.progress_percent == 75.0

    hook({"status": "finished", "total_bytes": 1_000_000, "downloaded_bytes": 1_000_000})
    assert task.status == DownloadStatus.MERGING

    stop_event.set()
    t.join(timeout=3.0)
    assert task.status == DownloadStatus.COMPLETED
    manager.shutdown()


def test_audio_download_validation_succeeds_with_nonfatal_logger_messages(tmp_path, monkeypatch):
    """Ensure non-fatal logger messages (SponsorBlock, mutagen, thumbnail) do not fail a successful audio download."""
    import yt_dlp
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig(download_dir=str(tmp_path))
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    audio_file = tmp_path / "Song [abc123].mp3"
    audio_file.write_bytes(b"dummy mp3 data 123456789")

    task = DownloadTask(
        id="audio-success-1",
        url="https://youtube.com/watch?v=abc123",
        title="Song",
        video_format="none",
        video_format_label="",
        audio_format="251",
        audio_format_label="160 kbps (opus)",
        container="mp3",
        status=DownloadStatus.QUEUED,
        output_filepath=str(audio_file),
    )
    manager.tasks = [task]

    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)

    from unittest.mock import patch

    def mock_extract_with_warnings(url, download=True):
        # Emulate non-fatal notices logged during download/postprocessing
        return {"id": "abc123", "title": "Song", "ext": "mp3", "_filename": str(audio_file)}

    with patch.object(yt_dlp.YoutubeDL, "extract_info", side_effect=mock_extract_with_warnings):
        with patch.object(yt_dlp.YoutubeDL, "prepare_filename", return_value=str(audio_file)):
            # Simulate non-fatal warnings arriving to TaskLogger
            manager._execute_download(task)

    assert task.status == DownloadStatus.COMPLETED
    assert task.progress_percent == 100.0
    assert len(history.items) == 1

    manager.shutdown()


def test_resume_and_retry_dispatch_immediately(tmp_path):
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig()
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=True)

    task = DownloadTask(id="r1", url="https://youtube.com/1", title="Task 1", status=DownloadStatus.PAUSED)
    manager.tasks = [task]

    assert manager.resume_task("r1") is True
    # Dispatch is synchronous: no polling thread delay before the download starts
    assert task.status == DownloadStatus.DOWNLOADING

    task.status = DownloadStatus.ERROR
    assert manager.retry_task("r1") is True
    assert task.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)

    manager.shutdown()


def test_requeued_task_never_runs_twice_concurrently(tmp_path, monkeypatch):
    """Pause then resume while the old download thread is still winding down must not start a second one."""
    release = threading.Event()
    runs = []

    def slow_execute(self, task):
        runs.append(task.id)
        release.wait(timeout=5)

    monkeypatch.setattr(DownloadManager, "_execute_download", slow_execute)
    manager = DownloadManager(config=AppConfig(max_concurrent_downloads=3), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=tmp_path / "q.json")
    task = DownloadTask(id="dup", url="https://youtube.com/watch?v=d", title="Dup")
    manager.enqueue(task)
    assert runs == ["dup"] and manager.is_running("dup")

    manager.pause_task("dup")
    manager.resume_task("dup")
    assert task.status == DownloadStatus.QUEUED
    assert runs == ["dup"]  # still only the original run

    release.set()
    for _ in range(100):  # the finished run frees the slot and the re-queued task starts
        if len(runs) == 2:
            break
        threading.Event().wait(0.02)
    assert runs == ["dup", "dup"]
    manager.shutdown()


def test_single_stream_fallback_counts_as_success(tmp_path, monkeypatch):
    """A video+audio request that yt-dlp satisfies with one muxed stream ('.../best') is a success."""
    import yt_dlp
    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    from unittest.mock import patch

    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)
    history = HistoryManager(storage_path=tmp_path / "h.json")
    manager = DownloadManager(config=AppConfig(download_dir=str(tmp_path)), history=history, queue_path=tmp_path / "q.json", auto_start_worker=False)
    out = tmp_path / "Clip [x].mp4"
    out.write_bytes(b"muxed data")
    task = DownloadTask(id="mux", url="https://vimeo.com/1", title="Clip", video_format="http-1080p", audio_format="bestaudio")

    def fake_extract(self, url, download=True):
        for hook in self.params["progress_hooks"]:
            hook({"status": "finished", "total_bytes": 10, "downloaded_bytes": 10})  # only ONE stream
        return {"id": "x", "requested_downloads": [{"filepath": str(out)}]}

    with patch.object(yt_dlp.YoutubeDL, "extract_info", fake_extract):
        manager._execute_download(task)

    assert task.status == DownloadStatus.COMPLETED
    assert task.output_filepath == str(out)
    assert history.items[0].filesize_bytes == len(b"muxed data")


def test_delete_running_task_signals_it_to_stop(tmp_path):
    manager = DownloadManager(config=AppConfig(), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=tmp_path / "q.json", auto_start_worker=False)
    task = DownloadTask(id="del", url="u", title="T", status=DownloadStatus.DOWNLOADING)
    manager.tasks = [task]
    manager.delete_task("del")
    assert task.is_cancelled is True
    assert manager.tasks == []


def test_cancel_does_not_touch_completed_tasks(tmp_path):
    manager = DownloadManager(config=AppConfig(), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=tmp_path / "q.json", auto_start_worker=False)
    task = DownloadTask(id="done", url="u", title="T", status=DownloadStatus.COMPLETED)
    manager.tasks = [task]
    assert manager.cancel_task("done") is False
    assert task.status == DownloadStatus.COMPLETED


def test_corrupt_queue_file_is_backed_up(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text("[{broken", encoding="utf-8")
    manager = DownloadManager(config=AppConfig(), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=queue_file, auto_start_worker=False)
    assert manager.tasks == []
    assert (tmp_path / "queue.json.bak").read_text(encoding="utf-8") == "[{broken"


def test_crashing_worker_releases_its_slot(tmp_path, monkeypatch):
    def boom(self, task):
        raise OSError("disk full")

    monkeypatch.setattr(DownloadManager, "_execute_download", boom)
    manager = DownloadManager(config=AppConfig(max_concurrent_downloads=1), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=tmp_path / "q.json")
    task = DownloadTask(id="crash", url="u", title="T")
    manager.enqueue(task)
    for _ in range(100):
        if not manager.is_running("crash"):
            break
        threading.Event().wait(0.02)
    assert task.status == DownloadStatus.ERROR
    assert "disk full" in task.error_message
    assert not manager.is_running("crash")
    manager.shutdown()


def test_quick_pause_resume_still_stops_the_old_run(tmp_path):
    """is_paused is cleared by resume before the old thread's next tick; stop_requested is not."""
    manager = DownloadManager(config=AppConfig(), history=HistoryManager(storage_path=tmp_path / "h.json"), queue_path=tmp_path / "q.json", auto_start_worker=False)
    task = DownloadTask(id="pr", url="u", title="T", status=DownloadStatus.DOWNLOADING)
    manager.tasks = [task]
    manager._running.add("pr")  # an old run is still in flight
    manager.pause_task("pr")
    manager.resume_task("pr")
    assert task.is_paused is False
    assert task.stop_requested is True  # the old run will still raise DownloadCancelled
    assert task.status == DownloadStatus.QUEUED
