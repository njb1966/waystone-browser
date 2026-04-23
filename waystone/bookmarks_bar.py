"""BookmarksBar — horizontal toolbar of bookmarks shown below the header bar.

Bookmarks with folder == BAR_FOLDER appear as flat buttons.
Immediate sub-folders (folder == "Bookmarks Bar/<Name>") appear as dropdown
MenuButtons.  Deeper nesting is shown as labelled sections inside the dropdown.
"""

from typing import Callable
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from . import async_utils
from .bookmark_service import BookmarkService

BAR_FOLDER = "Bookmarks Bar"

_MAX_LABEL = 30


def _truncate(text: str, n: int = _MAX_LABEL) -> str:
    return text[:n] + "…" if len(text) > n else text


class BookmarksBar(Gtk.Box):
    """
    Flat-button toolbar.  Bookmarks directly in BAR_FOLDER show as buttons;
    immediate child folders show as dropdown MenuButtons.
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
        bookmarks = await self._service.list_bar_and_children(BAR_FOLDER)

        # Direct bar entries
        direct = [b for b in bookmarks if b.get("folder") == BAR_FOLDER]

        # Group the rest by their immediate child-folder name
        prefix = BAR_FOLDER + "/"
        child_folders: dict[str, list[dict]] = {}
        for b in bookmarks:
            folder = b.get("folder") or ""
            if folder.startswith(prefix):
                rest = folder[len(prefix):]
                top_name = rest.split("/")[0]
                child_folders.setdefault(top_name, []).append(b)

        GLib.idle_add(self._rebuild, direct, child_folders)

    def _rebuild(self, direct: list[dict], child_folders: dict[str, list[dict]]) -> None:
        while child := self.get_first_child():
            self.remove(child)

        for bm in direct:
            self._add_bookmark_btn(bm)

        for folder_name in sorted(child_folders.keys()):
            self._add_folder_btn(folder_name, child_folders[folder_name])

    # ------------------------------------------------------------------
    # Flat bookmark button
    # ------------------------------------------------------------------

    def _add_bookmark_btn(self, bm: dict) -> None:
        label = bm["title"] or bm["url"]
        btn = Gtk.Button(label=_truncate(label))
        btn.set_has_frame(False)
        btn.set_tooltip_text(
            f"{bm['title']}\n{bm['url']}" if bm["title"] else bm["url"]
        )
        url = bm["url"]
        btn.connect("clicked", lambda _, u=url: self._open_url_cb(u))

        gesture = Gtk.GestureClick()
        gesture.set_button(3)
        gesture.connect(
            "pressed",
            lambda g, _n, _x, _y, b=bm, w=btn: self._show_bm_context(b, w, g),
        )
        btn.add_controller(gesture)

        self.append(btn)

    # ------------------------------------------------------------------
    # Folder dropdown button
    # ------------------------------------------------------------------

    def _add_folder_btn(self, folder_name: str, bookmarks: list[dict]) -> None:
        full_path = BAR_FOLDER + "/" + folder_name

        btn = Gtk.MenuButton(label=_truncate(folder_name))
        btn.set_has_frame(False)
        btn.set_tooltip_text(folder_name)
        btn.set_popover(self._build_folder_popover(full_path, bookmarks))

        gesture = Gtk.GestureClick()
        gesture.set_button(3)
        gesture.connect(
            "pressed",
            lambda g, _n, _x, _y, fn=folder_name, fp=full_path, w=btn: (
                self._show_folder_context(fn, fp, w, g)
            ),
        )
        btn.add_controller(gesture)

        self.append(btn)

    def _build_folder_popover(self, full_path: str, bookmarks: list[dict]) -> Gtk.Popover:
        """Build a popover listing direct bookmarks then any sub-folder sections."""
        prefix = full_path + "/"
        direct = [b for b in bookmarks if b.get("folder") == full_path]

        # Group deeper items by their next path component
        sub_sections: dict[str, list[dict]] = {}
        for b in bookmarks:
            folder = b.get("folder") or ""
            if folder.startswith(prefix):
                rest = folder[len(prefix):]
                section_name = rest.split("/")[0]
                sub_sections.setdefault(section_name, []).append(b)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(4)
        outer.set_margin_bottom(4)
        outer.set_margin_start(4)
        outer.set_margin_end(4)

        popover = Gtk.Popover()
        popover.set_child(outer)

        def add_bm_row(bm: dict) -> None:
            url = bm["url"]
            label = _truncate(bm["title"] or url, 40)
            b = Gtk.Button(label=label)
            b.set_has_frame(False)
            b.set_tooltip_text(f"{bm['title']}\n{url}" if bm["title"] else url)
            b.connect("clicked", lambda _, u=url: (popover.popdown(), self._open_url_cb(u)))
            outer.append(b)

        for bm in direct:
            add_bm_row(bm)

        for section_name in sorted(sub_sections.keys()):
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_margin_top(4)
            sep.set_margin_bottom(2)
            outer.append(sep)

            hdr = Gtk.Label(label=section_name, xalign=0.0)
            hdr.add_css_class("dim-label")
            hdr.set_margin_start(6)
            hdr.set_margin_bottom(2)
            outer.append(hdr)

            for bm in sub_sections[section_name]:
                add_bm_row(bm)

        return popover

    # ------------------------------------------------------------------
    # Folder right-click context (move out of bar)
    # ------------------------------------------------------------------

    def _show_folder_context(
        self,
        folder_name: str,
        full_path: str,
        btn: Gtk.MenuButton,
        gesture: Gtk.GestureClick,
    ) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        btn_out = Gtk.Button(label="Move out of Bar")
        btn_out.add_css_class("flat")

        box.append(btn_out)

        popover = Gtk.Popover()
        popover.set_child(box)
        popover.set_parent(btn)
        popover.set_has_arrow(True)

        btn_out.connect(
            "clicked",
            lambda _: (
                popover.popdown(),
                async_utils.run(self._do_move_folder_out(full_path, folder_name)),
            ),
        )
        popover.popup()

    async def _do_move_folder_out(self, full_path: str, folder_name: str) -> None:
        """Move Bookmarks Bar/<name> → <name> (top-level folder)."""
        await self._service.move_folder(full_path, folder_name)
        GLib.idle_add(self.refresh)

    # ------------------------------------------------------------------
    # Bookmark right-click context (edit / remove)
    # ------------------------------------------------------------------

    def _show_bm_context(self, bm: dict, btn: Gtk.Button, gesture: Gtk.GestureClick) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        btn_edit = Gtk.Button(label="Edit…")
        btn_edit.add_css_class("flat")

        btn_remove = Gtk.Button(label="Remove from Bar")
        btn_remove.add_css_class("flat")
        btn_remove.add_css_class("destructive-action")

        box.append(btn_edit)
        box.append(btn_remove)

        popover = Gtk.Popover()
        popover.set_child(box)
        popover.set_parent(btn)
        popover.set_has_arrow(True)

        btn_edit.connect("clicked", lambda _: (popover.popdown(), self._prompt_edit(bm, btn)))
        btn_remove.connect("clicked", lambda _: (popover.popdown(), async_utils.run(self._do_remove(bm["url"]))))

        popover.popup()

    def _prompt_edit(self, bm: dict, anchor: Gtk.Widget) -> None:
        entry = Gtk.Entry()
        entry.set_text(bm["title"] or "")
        entry.set_placeholder_text("Bookmark title")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        parent = anchor.get_root()

        dlg = Adw.AlertDialog(heading="Edit Bookmark", body=bm["url"])
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("save", "Save")
        dlg.set_default_response("save")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp, u=bm["url"], folder=bm.get("folder")):
            if resp == "save":
                new_title = entry.get_text().strip()
                async_utils.run(self._do_edit(u, new_title, folder))

        dlg.connect("response", on_response)
        dlg.present(parent)

    async def _do_edit(self, url: str, new_title: str, folder) -> None:
        await self._service.add(url, new_title, folder)
        GLib.idle_add(self.refresh)

    async def _do_remove(self, url: str) -> None:
        await self._service.remove(url)
        GLib.idle_add(self.refresh)
