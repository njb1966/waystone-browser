"""BookmarksBar — horizontal toolbar of bookmarks shown below the header bar.

Only bookmarks explicitly placed in the folder named BAR_FOLDER appear here.
All other bookmarks remain as regular bookmarks and are never shown automatically.
"""

from typing import Callable
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from . import async_utils
from .bookmark_service import BookmarkService

# The reserved folder name whose contents appear in the bar.
# Users move bookmarks here via the bookmark dialog's "Move ▾" menu.
BAR_FOLDER = "Bookmarks Bar"

_MAX_LABEL = 30


def _truncate(text: str, n: int = _MAX_LABEL) -> str:
    return text[:n] + "…" if len(text) > n else text


class BookmarksBar(Gtk.Box):
    """
    Flat-button toolbar showing only bookmarks in the 'Bookmarks Bar' folder.
    Call refresh() after any bookmark change to repopulate.
    """

    def __init__(
        self,
        service: BookmarkService,
        open_url_cb: Callable[[str], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._service = service
        self._open_url_cb = open_url_cb

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        async_utils.run(self._load_async())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _load_async(self) -> None:
        all_bookmarks = await self._service.list_all()
        bar_bookmarks = [b for b in all_bookmarks if b.get("folder") == BAR_FOLDER]
        GLib.idle_add(self._rebuild, bar_bookmarks)

    def _rebuild(self, bookmarks: list[dict]) -> None:
        while child := self.get_first_child():
            self.remove(child)

        for bm in bookmarks:
            self._add_bookmark_btn(bm)

    def _add_bookmark_btn(self, bm: dict) -> None:
        label = bm["title"] or bm["url"]
        btn = Gtk.Button(label=_truncate(label))
        btn.set_has_frame(False)
        btn.set_tooltip_text(
            f"{bm['title']}\n{bm['url']}" if bm["title"] else bm["url"]
        )
        url = bm["url"]
        btn.connect("clicked", lambda _, u=url: self._open_url_cb(u))
        self.append(btn)
