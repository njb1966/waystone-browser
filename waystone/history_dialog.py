"""History viewer dialog."""

from datetime import datetime
from . import async_utils

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from .history_service import HistoryService


def _fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")
    except Exception:
        return ""


class HistoryDialog(Adw.Dialog):
    def __init__(self, parent: Gtk.Window, service: HistoryService, open_url_cb):
        super().__init__()
        self.set_title("History")
        self.set_content_width(660)
        self.set_content_height(560)

        self._service = service
        self._open_url_cb = open_url_cb
        self._all_history: list[dict] = []

        self._build_ui()
        self.present(parent)
        async_utils.run(self._load())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()

        btn_clear = Gtk.Button(label="Clear All")
        btn_clear.add_css_class("destructive-action")
        btn_clear.connect("clicked", lambda _: async_utils.run(self._do_clear()))
        header.pack_end(btn_clear)

        toolbar_view.add_top_bar(header)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search history…")
        self._search.connect("search-changed", self._on_search_changed)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")

        self._empty_label = Gtk.Label(label="No history yet.")
        self._empty_label.add_css_class("dim-label")
        self._empty_label.set_margin_top(48)
        self._empty_label.set_visible(False)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._list_box)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.append(self._search)
        content.append(self._empty_label)
        content.append(scroll)

        toolbar_view.set_content(content)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    async def _load(self):
        history = await self._service.list_recent()
        GLib.idle_add(self._populate, history)

    def _populate(self, history: list[dict]):
        self._all_history = history
        self._rebuild_list(history)

    def _rebuild_list(self, history: list[dict]):
        while (child := self._list_box.get_first_child()):
            self._list_box.remove(child)

        self._empty_label.set_visible(len(history) == 0)

        for entry in history:
            self._list_box.append(self._make_row(entry))

    def _make_row(self, entry: dict) -> Adw.ActionRow:
        row = Adw.ActionRow()
        title = entry["title"] or entry["url"]
        row.set_title(GLib.markup_escape_text(title))
        row.set_subtitle(GLib.markup_escape_text(entry["url"]))
        row.set_title_lines(1)
        row.set_subtitle_lines(1)

        time_label = Gtk.Label(label=_fmt_time(entry["visited_at"]))
        time_label.add_css_class("dim-label")
        time_label.set_valign(Gtk.Align.CENTER)

        url = entry["url"]
        btn_open = Gtk.Button(label="Open")
        btn_open.set_valign(Gtk.Align.CENTER)
        btn_open.add_css_class("suggested-action")
        btn_open.connect("clicked", lambda _: self._do_open(url))

        suffix = Gtk.Box(spacing=8)
        suffix.set_valign(Gtk.Align.CENTER)
        suffix.append(time_label)
        suffix.append(btn_open)
        row.add_suffix(suffix)

        return row

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_open(self, url: str):
        self._open_url_cb(url)
        self.close()

    async def _do_clear(self):
        await self._service.clear()
        self._all_history = []
        GLib.idle_add(self._rebuild_list, [])

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search_changed(self, entry):
        query = entry.get_text().lower().strip()
        if not query:
            self._rebuild_list(self._all_history)
            return
        filtered = [
            h for h in self._all_history
            if query in h["url"].lower() or query in (h["title"] or "").lower()
        ]
        self._rebuild_list(filtered)
