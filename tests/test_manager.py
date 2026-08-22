import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from config import AppConfig
from history import HistoryManager
from manager import DownloadManager, DownloadStatus, DownloadTask


@pytest.fixture(autouse=True)
def reset_manager_singleton():
    if DownloadManager._instance:
        DownloadManager._instance.shutdown()
        DownloadManager._instance = None
    yield
    if DownloadManager._instance:
        DownloadManager._instance.shutdown()
        DownloadManager._instance = None


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
    from manager import TaskLogger
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
    import manager as manager_module

    with patch.object(manager_module.yt_dlp.YoutubeDL, "extract_info", side_effect=yt_dlp.utils.DownloadError("unable to download video data: HTTP Error 403: Forbidden")):
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

    from unittest.mock import MagicMock, patch
    import manager as manager_module

    attempts = 0
    clients_tried = []

    def mock_extract_info(url, download=True):
        nonlocal attempts
        attempts += 1
        # Extract the player client from current active YoutubeDL opts
        if attempts == 1:
            raise yt_dlp.utils.DownloadError("unable to download video data: HTTP Error 403: Forbidden")
        return {"id": "test", "title": "Test Success Video", "ext": "mp4", "_filename": str(test_file)}

    with patch.object(manager_module.yt_dlp.YoutubeDL, "extract_info", side_effect=mock_extract_info):
        with patch.object(manager_module.yt_dlp.YoutubeDL, "prepare_filename", return_value=str(test_file)):
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


def test_progress_hook_event_loop_throttling(tmp_path, monkeypatch):
    import time
    from unittest.mock import MagicMock
    from tests.conftest import ORIGINAL_EXECUTE_DOWNLOAD
    monkeypatch.setattr(DownloadManager, "_execute_download", ORIGINAL_EXECUTE_DOWNLOAD)

    queue_file = tmp_path / "queue.json"
    config = AppConfig(download_dir=str(tmp_path))
    history = HistoryManager(storage_path=tmp_path / "hist.json")
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=False)

    notify_mock = MagicMock()
    manager.add_listener(notify_mock)

    captured_progress_hook = None
    started_event = threading.Event()
    stop_event = threading.Event()

    def fake_build_options(**kwargs):
        nonlocal captured_progress_hook
        captured_progress_hook = kwargs.get("progress_hook")
        return {}

    from ytdlp_engine import YtDlpEngine
    monkeypatch.setattr(YtDlpEngine, "build_download_options", fake_build_options)

    import yt_dlp

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

    # Create dummy output file so completion verification passes
    (tmp_path / "video.mp4").write_bytes(b"dummy video data")

    task = DownloadTask(
        id="throttle-task",
        url="https://youtube.com/watch?v=throttle",
        title="Throttle Video",
        video_format="137",
        audio_format="140",
        container="mp4",
        status=DownloadStatus.QUEUED,
    )

    # Start download in a thread to test progress hook throttling
    t = threading.Thread(target=manager._execute_download, args=(task,))
    t.start()

    # Wait for extract_info to start
    started_event.wait(timeout=2.0)
    assert captured_progress_hook is not None

    # Reset notify mock calls
    notify_mock.reset_mock()

    # Call downloading hook rapidly 10 times with no sleep
    for i in range(10):
        captured_progress_hook({
            "status": "downloading",
            "total_bytes": 1000000,
            "downloaded_bytes": 1000 * (i + 1),
            "speed": 50000,
            "eta": 10,
        })

    # Due to ~125ms throttling, 10 instant calls should only invoke notify once
    assert notify_mock.call_count == 1

    # Sleep past throttle duration (150ms)
    time.sleep(0.15)

    # Calling downloading hook again should now notify
    captured_progress_hook({
        "status": "downloading",
        "total_bytes": 1000000,
        "downloaded_bytes": 20000,
        "speed": 50000,
        "eta": 9,
    })
    assert notify_mock.call_count == 2

    # Significant state change: "finished" should notify immediately without throttling
    captured_progress_hook({
        "status": "finished",
        "total_bytes": 500000,
        "downloaded_bytes": 500000,
    })
    assert notify_mock.call_count == 3

    # Release extract_info and wait for thread to join
    stop_event.set()
    t.join(timeout=3.0)
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
    import manager as manager_module

    def mock_extract_with_warnings(url, download=True):
        # Emulate non-fatal notices logged during download/postprocessing
        return {"id": "abc123", "title": "Song", "ext": "mp3", "_filename": str(audio_file)}

    with patch.object(manager_module.yt_dlp.YoutubeDL, "extract_info", side_effect=mock_extract_with_warnings):
        with patch.object(manager_module.yt_dlp.YoutubeDL, "prepare_filename", return_value=str(audio_file)):
            # Simulate non-fatal warnings arriving to TaskLogger
            manager._execute_download(task)

    assert task.status == DownloadStatus.COMPLETED
    assert task.progress_percent == 100.0
    assert len(history.items) == 1

    manager.shutdown()


def test_resume_and_retry_auto_starts_worker(tmp_path):
    storage = tmp_path / "hist.json"
    queue_file = tmp_path / "queue.json"
    config = AppConfig()
    history = HistoryManager(storage_path=storage)
    manager = DownloadManager(config=config, history=history, queue_path=queue_file, auto_start_worker=True)

    task = DownloadTask(id="r1", url="https://youtube.com/1", title="Task 1", status=DownloadStatus.PAUSED)
    manager.tasks = [task]

    manager.resume_task("r1")
    assert task.status == DownloadStatus.QUEUED
    assert manager._worker_thread is not None
    assert manager._worker_thread.is_alive()

    task.status = DownloadStatus.ERROR
    manager.retry_task("r1")
    assert task.status == DownloadStatus.QUEUED
    assert manager._worker_thread.is_alive()

    manager.shutdown()




