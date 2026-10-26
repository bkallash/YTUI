"""Persistent library of completed downloads."""

import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Optional

from .config import atomic_json_save, get_config_dir, load_json_or_backup
from .formats import format_bytes

MAX_HISTORY_ITEMS = 500


@dataclass
class HistoryItem:
    """A successfully downloaded item."""

    id: str
    title: str
    url: str
    channel: str
    duration_str: str
    filepath: str
    filesize_bytes: int
    format_note: str
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def formatted_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.filesize_bytes)

    @property
    def search_text(self) -> str:
        """Casefolded haystack for filtering, built once per item."""
        cached = self.__dict__.get("_search_text")
        if cached is None:
            cached = f"{self.title} {self.channel} {self.format_note} {self.url} {self.filepath} {self.formatted_time}".casefold()
            self.__dict__["_search_text"] = cached
        return cached


class HistoryManager:
    """Thread-safe persistent download history. `version` changes whenever items change."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (get_config_dir() / "history.json")
        self.items: List[HistoryItem] = []
        self.version = 0
        self._lock = threading.Lock()
        self.load()

    def load(self) -> List[HistoryItem]:
        data = load_json_or_backup(self.storage_path)
        names = {f.name for f in fields(HistoryItem)}
        items: List[HistoryItem] = []
        seen = set()
        for raw in data if isinstance(data, list) else []:
            try:
                item = HistoryItem(**{k: v for k, v in raw.items() if k in names})
            except (TypeError, AttributeError):
                continue  # skip one malformed entry instead of losing the whole history
            if item.id not in seen:
                seen.add(item.id)
                items.append(item)
        with self._lock:
            self.items = items
            self.version += 1
        return self.items

    def save(self) -> None:
        with self._lock:
            data = [asdict(item) for item in self.items]
        try:
            atomic_json_save(self.storage_path, data)
        except Exception as e:
            print(f"Warning: Could not save history: {e}", file=sys.stderr)

    def _commit(self, items: List[HistoryItem]) -> None:
        with self._lock:
            self.items = items
            self.version += 1
        self.save()

    def add(self, item: HistoryItem) -> None:
        """Insert at the top, replacing entries with the same id or file path."""
        kept = [i for i in self.items if i.id != item.id and (not item.filepath or i.filepath != item.filepath)]
        self._commit([item] + kept[: MAX_HISTORY_ITEMS - 1])

    def remove(self, item_id: str) -> None:
        self._commit([item for item in self.items if item.id != item_id])

    def clear(self) -> None:
        self._commit([])

    def filter(self, query: str) -> List[HistoryItem]:
        """Items matching every whitespace-separated token, case-insensitively, across all fields."""
        tokens = (query or "").casefold().split()
        items = list(self.items)
        if not tokens:
            return items
        return [item for item in items if all(tok in item.search_text for tok in tokens)]

    @staticmethod
    def open_file(filepath: str) -> bool:
        """Open a file with the OS default application."""
        path = Path(filepath)
        if not filepath or not path.exists():
            return False
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
            return True
        except Exception:
            return False

    @staticmethod
    def open_folder(filepath: str) -> bool:
        """Reveal a file in the OS file manager, or open a directory."""
        if not filepath:
            return False
        path = Path(filepath).expanduser()
        is_file = path.is_file()
        target_dir = path.parent if is_file or (not path.is_dir() and path.suffix) else path
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{path.resolve()}"' if is_file else f'explorer "{target_dir.resolve()}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)] if is_file else ["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
            return True
        except Exception:
            return False
