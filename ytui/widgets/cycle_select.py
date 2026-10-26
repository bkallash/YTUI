"""Inline option cycler: a lightweight alternative to Select without an overlay."""

from typing import List, Optional, Tuple

from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from ..rtl_utils import escape_markup


class CycleSelect(Static):
    """Cycles through (label, value) options with ←/→, Enter, Space or a click."""

    can_focus = True

    class Changed(Message):
        """Posted when the user changes the selected option."""

        def __init__(self, select: "CycleSelect", value: str):
            super().__init__()
            self.select = select
            self.value = value

    DEFAULT_CSS = """
    CycleSelect {
        width: 1fr;
        height: 1;
        background: transparent;
        color: $foreground;
        padding: 0 1;
        border: none;
    }
    CycleSelect:focus {
        background: $boost;
        color: $primary;
        text-style: bold;
    }
    """

    def __init__(self, options: List[Tuple[str, str]], value: str, id: Optional[str] = None, **kwargs):
        super().__init__(id=id, **kwargs)
        self.options = options
        self._current_idx = next((i for i, (_, val) in enumerate(options) if val == value), 0)

    @property
    def value(self) -> str:
        return self.options[self._current_idx][1] if self.options else ""

    @value.setter
    def value(self, new_val: str) -> None:
        for i, (_, val) in enumerate(self.options):
            if val == new_val:
                self._current_idx = i
                self._update_display()
                return

    def on_mount(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        label = escape_markup(self.options[self._current_idx][0]) if self.options else "None"
        self.update(f"◀  [bold]{label}[/]  ▶")

    def _cycle(self, step: int) -> None:
        if self.options:
            self._current_idx = (self._current_idx + step) % len(self.options)
            self._update_display()
            self.post_message(self.Changed(self, self.value))

    def cycle_next(self) -> None:
        self._cycle(1)

    def cycle_prev(self) -> None:
        self._cycle(-1)

    def on_click(self) -> None:
        self.cycle_next()

    def on_key(self, event: Key) -> None:
        if event.key in ("right", "enter", "space", "l"):
            self.cycle_next()
        elif event.key in ("left", "h"):
            self.cycle_prev()
        else:
            return
        event.prevent_default()
        event.stop()
