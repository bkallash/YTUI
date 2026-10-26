"""Selectable column of format options (video or audio) used by the format and playlist screens."""

from typing import List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..formats import FormatOption
from ..rtl_utils import fix_rtl


class FormatItemWidget(ListItem):
    """One selectable format row."""

    def __init__(self, option: FormatOption, is_selected: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.option = option
        self.is_selected = is_selected
        self._label_text = fix_rtl(option.label)
        self._note_text = f"  ({fix_rtl(option.note)})" if option.note and not option.is_special else ""

    def _render_line(self) -> Text:
        t = Text()
        if self.is_selected:
            t.append("[●] ", style="bold green")
            t.append(self._label_text, style="bold")
        else:
            t.append("[ ] ", style="dim")
            t.append(self._label_text)
        if self._note_text:
            t.append(self._note_text, style="dim")
        return t

    def compose(self) -> ComposeResult:
        yield Label(self._render_line(), classes="format-item-line")

    def set_selected(self, selected: bool) -> None:
        if selected == self.is_selected:
            return
        self.is_selected = selected
        if self.is_mounted:
            self.query_one(Label).update(self._render_line())


class FormatColumnView(Vertical):
    """A titled, scrollable list of format choices with a single selected item."""

    class SelectedChanged(Message):
        """Posted when the selection changes. is_double_enter: the selected item was clicked again."""

        def __init__(self, column_type: str, option: FormatOption, is_double_enter: bool = False):
            super().__init__()
            self.column_type = column_type  # 'video' or 'audio'
            self.option = option
            self.is_double_enter = is_double_enter

    def __init__(self, title: str, column_type: str, options: List[FormatOption], default_idx: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.column_title = title
        self.column_type = column_type
        self.options = options
        self.selected_idx = default_idx if 0 <= default_idx < len(options) else 0
        self._items: List[FormatItemWidget] = []
        self._silent_idx: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label(f"[bold]{self.column_title}[/]", classes="column-header")
        self._items = [
            FormatItemWidget(option=opt, is_selected=(i == self.selected_idx), id=f"opt-{self.column_type}-{i}")
            for i, opt in enumerate(self.options)
        ]
        yield ListView(*self._items, id=f"list-{self.column_type}", classes="format-list-view", initial_index=self.selected_idx)

    def on_key(self, event: Key) -> None:
        # Enter downloads; ListView.Selected (Enter's default) is reserved for mouse clicks.
        if event.key == "enter" and hasattr(self.screen, "action_start_download"):
            event.prevent_default()
            event.stop()
            self.screen.action_start_download()

    def _select(self, idx: Optional[int]) -> bool:
        """Move the selection mark. Returns False for invalid indexes."""
        if idx is None or not 0 <= idx < len(self._items):
            return False
        self._items[self.selected_idx].set_selected(False)
        self._items[idx].set_selected(True)
        self.selected_idx = idx
        return True

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        idx = event.list_view.index
        if idx == self._silent_idx:  # programmatic move already handled by the screen
            self._silent_idx = None
            return
        if self._select(idx):
            self.post_message(self.SelectedChanged(self.column_type, self.options[idx]))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        idx = event.list_view.index
        is_double = idx == self.selected_idx
        if self._select(idx):
            self.post_message(self.SelectedChanged(self.column_type, self.options[idx], is_double_enter=is_double))

    def set_selected_index(self, idx: int) -> Optional[FormatOption]:
        """Select an index programmatically without posting SelectedChanged."""
        if not self._select(idx):
            return None
        list_view = self.query_one(ListView)
        if list_view.index != idx:
            self._silent_idx = idx
            list_view.index = idx
        return self.options[idx]

    def get_selected_option(self) -> Optional[FormatOption]:
        return self.options[self.selected_idx] if 0 <= self.selected_idx < len(self.options) else None
