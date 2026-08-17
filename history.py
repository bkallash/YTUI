"""History manager for completed downloads."""

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import atomic_json_save, get_config_dir


@dataclass
class HistoryItem:
    """Represents a successfully downloaded item in the library."""

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
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def formatted_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))

    @property
    def formatted_size(self) -> str:
        size = float(self.filesize_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0 or unit == "TB":
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{self.filesize_bytes} B"


class HistoryManager:
    """Persistent download history manager."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (get_config_dir() / "history.json")
        self.items: List[HistoryItem] = []
        self.load()

    def load(self) -> List[HistoryItem]:
        if not self.storage_path.exists():
            self.items = []
            return self.items
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            seen_ids = set()
            unique_items = []
            for item_dict in data:
                item = HistoryItem(**item_dict)
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    unique_items.append(item)
            self.items = unique_items
        except Exception:
            self.items = []
        return self.items

    def save(self) -> None:
        try:
            atomic_json_save(self.storage_path, [asdict(item) for item in self.items], indent=2, file_mode=0o600, dir_mode=0o700)
        except Exception as e:
            print(f"Warning: Could not save history: {e}", file=sys.stderr)

    def add(self, item: HistoryItem) -> None:
        # Avoid duplicate entries for same id or filepath
        self.items = [i for i in self.items if i.id != item.id and (not item.filepath or i.filepath != item.filepath)]
        self.items.insert(0, item)
        # Cap history to 500 items
        if len(self.items) > 500:
            self.items = self.items[:500]
        self.save()

    def remove(self, item_id: str) -> None:
        self.items = [item for item in self.items if item.id != item_id]
        self.save()

    def clear(self) -> None:
        self.items = []
        self.save()

    def filter(self, query: str) -> List[HistoryItem]:
        """Return items matching the query case-insensitively across all metadata fields."""
        query_cf = (query or "").strip().casefold()
        if not query_cf:
            return list(self.items)

        tokens = query_cf.split()
        results = []
        for item in self.items:
            haystack = f"{item.title or ''} {item.channel or ''} {item.format_note or ''} {item.url or ''} {item.filepath or ''} {item.formatted_time}".casefold()
            if all(tok in haystack for tok in tokens):
                results.append(item)
        return results

    @staticmethod
    def open_file(filepath: str) -> bool:
        """Open the downloaded file in default OS media player / viewer."""
        path = Path(filepath)
        if not path.exists():
            return False
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return True
        except Exception:
            return False

    @staticmethod
    def open_folder(filepath: str) -> bool:
        """Open the directory containing the file in file explorer."""
        if not filepath:
            return False
        path = Path(filepath).expanduser()
        if path.is_file():
            target_dir = path.parent
        elif path.is_dir():
            target_dir = path
        elif path.suffix:
            target_dir = path.parent
        else:
            target_dir = path

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                if path.exists() and path.is_file():
                    subprocess.Popen(f'explorer /select,"{path.resolve()}"')
                else:
                    subprocess.Popen(f'explorer "{target_dir.resolve()}"')
            elif sys.platform == "darwin":
                if path.exists() and path.is_file():
                    subprocess.Popen(["open", "-R", str(path)])
                else:
                    subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
            return True
        except Exception:
            return False
