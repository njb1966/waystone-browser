"""Bookmark manager dialog with folder support."""

from typing import Optional
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, Gdk, Pango, GLib

from . import async_utils
from .bookmark_service import BookmarkService

# Folder-selection sentinels
_ALL     = "__all__"    # show every bookmark
_UNFILED = "__none__"   # show only bookmarks with folder = NULL


class BookmarkDialog(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        service: BookmarkService,
        open_url_cb,
        on_change_cb=None,
    ) -> None:
        super().__init__()
        self.set_title("Bookmarks")
        self.set_default_size(760, 560)
        self.set_transient_for(parent)
        self.set_modal(True)

        self._service         = service
        self._open_url_cb     = open_url_cb
        self._on_change_cb    = on_change_cb  # called after any mutation
        self._all_bookmarks:  list[dict] = []
        self._folders:        list[str]  = []
        self._selected_folder: str       = _ALL
        self._folder_rows:    dict[str, Gtk.ListBoxRow] = {}

        self._build_ui()
        async_utils.run(self._load())

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self._new_folder_btn = Gtk.Button(icon_name="folder-new-symbolic")
        self._new_folder_btn.set_tooltip_text("New Folder")
        self._new_folder_btn.connect("clicked", lambda _: self._prompt_new_folder_empty())
        header.pack_end(self._new_folder_btn)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search bookmarks…")
        self._search.set_hexpand(True)
        self._search.connect("search-changed", lambda _: self._rebuild_bm_list())
        header.set_title_widget(self._search)

        # Two-pane layout
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(200)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_vexpand(True)
        toolbar_view.set_content(paned)

        # ── Sidebar ────────────────────────────────────────────────────
        self._folder_list = Gtk.ListBox()
        self._folder_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._folder_list.add_css_class("navigation-sidebar")
        self._folder_list.connect("row-selected", self._on_folder_selected)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)
        sidebar_scroll.set_min_content_width(160)
        sidebar_scroll.set_child(self._folder_list)
        paned.set_start_child(sidebar_scroll)

        # ── Content ────────────────────────────────────────────────────
        self._bm_list = Gtk.ListBox()
        self._bm_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._bm_list.add_css_class("boxed-list")

        self._empty_label = Gtk.Label(label="No bookmarks here yet.")
        self._empty_label.add_css_class("dim-label")
        self._empty_label.set_margin_top(48)
        self._empty_label.set_visible(False)

        bm_scroll = Gtk.ScrolledWindow()
        bm_scroll.set_vexpand(True)
        bm_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        bm_scroll.set_child(self._bm_list)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_margin_top(8)
        content_box.set_margin_bottom(8)
        content_box.set_margin_start(8)
        content_box.set_margin_end(8)
        content_box.append(self._empty_label)
        content_box.append(bm_scroll)
        paned.set_end_child(content_box)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        bookmarks = await self._service.list_all()
        GLib.idle_add(self._populate, bookmarks)

    def _populate(self, bookmarks: list[dict]) -> None:
        self._all_bookmarks = bookmarks
        seen: list[str] = []
        for b in bookmarks:
            f = b.get("folder")
            if f and f not in seen:
                seen.append(f)
        self._folders = sorted(seen)
        self._rebuild_sidebar()
        self._rebuild_bm_list()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _rebuild_sidebar(self) -> None:
        while child := self._folder_list.get_first_child():
            self._folder_list.remove(child)
        self._folder_rows.clear()

        all_row    = self._make_sidebar_row("All Bookmarks", "bookmark-collection-symbolic", _ALL)
        unfiled_row = self._make_sidebar_row("Unfiled",       "folder-symbolic",              _UNFILED)
        self._folder_rows[_ALL]     = all_row
        self._folder_rows[_UNFILED] = unfiled_row
        self._folder_list.append(all_row)
        self._folder_list.append(unfiled_row)

        for folder_name in self._folders:
            row = self._make_sidebar_row(folder_name, "folder-symbolic", folder_name)
            self._folder_rows[folder_name] = row
            self._folder_list.append(row)

        target = self._folder_rows.get(self._selected_folder,
                                       self._folder_rows[_ALL])
        self._folder_list.select_row(target)

    def _make_sidebar_row(self, label: str, icon: str, folder_key: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._folder_key = folder_key  # type: ignore[attr-defined]

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        img = Gtk.Image.new_from_icon_name(icon)
        lbl = Gtk.Label(label=label, xalign=0.0)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(img)
        box.append(lbl)
        row.set_child(box)

        # Right-click menu for named folders (rename / delete)
        if folder_key not in (_ALL, _UNFILED):
            gesture = Gtk.GestureClick()
            gesture.set_button(3)
            gesture.connect(
                "pressed",
                lambda g, n, x, y, r=row, fk=folder_key: self._show_folder_context(r, fk),
            )
            row.add_controller(gesture)

        return row

    def _on_folder_selected(self, _listbox, row) -> None:
        if row is None:
            return
        self._selected_folder = row._folder_key  # type: ignore[attr-defined]
        self._rebuild_bm_list()

    # ------------------------------------------------------------------
    # Folder context menu (right-click): rename / delete
    # ------------------------------------------------------------------

    def _show_folder_context(self, row: Gtk.ListBoxRow, folder_name: str) -> None:
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        rename_row = self._popover_text_row("Rename…")
        delete_row = self._popover_text_row("Delete Folder")
        listbox.append(rename_row)
        listbox.append(delete_row)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        inner.set_margin_top(4)
        inner.set_margin_bottom(4)
        inner.set_margin_start(4)
        inner.set_margin_end(4)
        inner.append(listbox)

        popover = Gtk.Popover()
        popover.set_child(inner)
        popover.set_parent(row)
        popover.set_has_arrow(False)

        def on_activated(_lb, r, p=popover, fn=folder_name):
            p.popdown()
            if r.get_index() == 0:
                self._prompt_rename_folder(fn)
            else:
                self._confirm_delete_folder(fn)

        listbox.connect("row-activated", on_activated)
        popover.popup()

    # ------------------------------------------------------------------
    # Folder dialogs: new / rename / delete
    # ------------------------------------------------------------------

    def _prompt_new_folder_empty(self) -> None:
        """Create an empty placeholder folder in the sidebar."""
        entry = Gtk.Entry()
        entry.set_placeholder_text("Folder name")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        dlg = Adw.AlertDialog(heading="New Folder",
                              body="Enter a name for the new folder:")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("create", "Create")
        dlg.set_default_response("create")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp):
            name = entry.get_text().strip()
            if resp == "create" and name and name not in self._folders:
                self._folders.append(name)
                self._folders.sort()
                self._rebuild_sidebar()

        dlg.connect("response", on_response)
        dlg.present(self)

    def _prompt_new_folder(self, url: str) -> None:
        """Prompt for a new folder name and move url into it."""
        entry = Gtk.Entry()
        entry.set_placeholder_text("Folder name")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        dlg = Adw.AlertDialog(heading="New Folder",
                              body="Enter a name for the new folder:")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("create", "Create")
        dlg.set_default_response("create")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp, u=url):
            name = entry.get_text().strip()
            if resp == "create" and name:
                async_utils.run(self._do_move(u, name))

        dlg.connect("response", on_response)
        dlg.present(self)

    def _prompt_rename_folder(self, old_name: str) -> None:
        entry = Gtk.Entry()
        entry.set_text(old_name)
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        dlg = Adw.AlertDialog(heading="Rename Folder",
                              body=f'Rename "{old_name}" to:')
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("rename", "Rename")
        dlg.set_default_response("rename")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp, o=old_name):
            new_name = entry.get_text().strip()
            if resp == "rename" and new_name and new_name != o:
                async_utils.run(self._do_rename_folder(o, new_name))

        dlg.connect("response", on_response)
        dlg.present(self)

    def _confirm_delete_folder(self, folder_name: str) -> None:
        dlg = Adw.AlertDialog(
            heading="Delete Folder",
            body=f'Delete "{folder_name}"? All bookmarks will be moved to Unfiled.',
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, resp, fn=folder_name):
            if resp == "delete":
                async_utils.run(self._do_delete_folder(fn))

        dlg.connect("response", on_response)
        dlg.present(self)

    # ------------------------------------------------------------------
    # Bookmark list
    # ------------------------------------------------------------------

    def _filtered_bookmarks(self) -> list[dict]:
        query = self._search.get_text().lower().strip()

        if self._selected_folder == _ALL:
            items = self._all_bookmarks
        elif self._selected_folder == _UNFILED:
            items = [b for b in self._all_bookmarks if not b.get("folder")]
        else:
            items = [b for b in self._all_bookmarks
                     if b.get("folder") == self._selected_folder]

        if query:
            items = [b for b in items
                     if query in (b["title"] or "").lower()
                     or query in b["url"].lower()]

        return items

    def _rebuild_bm_list(self) -> None:
        while child := self._bm_list.get_first_child():
            self._bm_list.remove(child)

        visible = self._filtered_bookmarks()
        self._empty_label.set_visible(len(visible) == 0)

        for bm in visible:
            self._bm_list.append(self._make_bm_row(bm))

    def _make_bm_row(self, bm: dict) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(bm["title"] or bm["url"]))
        row.set_subtitle(GLib.markup_escape_text(bm["url"]))
        row.set_title_lines(1)
        row.set_subtitle_lines(1)

        url = bm["url"]

        btn_open = Gtk.Button(label="Open")
        btn_open.set_valign(Gtk.Align.CENTER)
        btn_open.add_css_class("suggested-action")
        btn_open.connect("clicked", lambda _: self._do_open(url))

        btn_move = Gtk.MenuButton(icon_name="folder-symbolic")
        btn_move.set_valign(Gtk.Align.CENTER)
        btn_move.set_has_frame(False)
        btn_move.set_tooltip_text("Move to folder")
        btn_move.set_popover(self._make_move_popover(url))

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.set_valign(Gtk.Align.CENTER)
        btn_del.add_css_class("destructive-action")
        btn_del.connect("clicked",
                        lambda _, r=row, u=url: async_utils.run(self._do_delete(u, r)))

        suffix = Gtk.Box(spacing=4)
        suffix.set_valign(Gtk.Align.CENTER)
        suffix.append(btn_open)
        suffix.append(btn_move)
        suffix.append(btn_del)
        row.add_suffix(suffix)

        return row

    # ------------------------------------------------------------------
    # Move-to-folder popover
    # ------------------------------------------------------------------

    def _make_move_popover(self, url: str) -> Gtk.Popover:
        """Build the 'Move to folder' popover. Folders are snapshotted at creation."""
        snapshot = list(self._folders)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        listbox.append(self._popover_text_row("Unfiled"))
        for fname in snapshot:
            listbox.append(self._popover_text_row(fname))
        listbox.append(self._popover_text_row("New Folder…"))

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        inner.set_margin_top(6)
        inner.set_margin_bottom(6)
        inner.set_margin_start(6)
        inner.set_margin_end(6)
        inner.append(listbox)

        popover = Gtk.Popover()
        popover.set_child(inner)

        def on_activated(_lb, row, p=popover, u=url, folders=snapshot):
            idx = row.get_index()
            p.popdown()
            if idx == 0:
                async_utils.run(self._do_move(u, None))
            elif 1 <= idx <= len(folders):
                async_utils.run(self._do_move(u, folders[idx - 1]))
            else:
                self._prompt_new_folder(u)

        listbox.connect("row-activated", on_activated)
        return popover

    def _popover_text_row(self, label: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        lbl = Gtk.Label(label=label, xalign=0.0)
        lbl.set_margin_start(8)
        lbl.set_margin_end(8)
        lbl.set_margin_top(4)
        lbl.set_margin_bottom(4)
        row.set_child(lbl)
        return row

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _notify_change(self) -> None:
        if self._on_change_cb:
            GLib.idle_add(self._on_change_cb)

    def _do_open(self, url: str) -> None:
        self._open_url_cb(url)
        self.close()

    async def _do_delete(self, url: str, row: Adw.ActionRow) -> None:
        await self._service.remove(url)
        self._all_bookmarks = [b for b in self._all_bookmarks if b["url"] != url]
        used = {b.get("folder") for b in self._all_bookmarks if b.get("folder")}
        self._folders = [f for f in self._folders if f in used]
        GLib.idle_add(self._bm_list.remove, row)
        GLib.idle_add(
            self._empty_label.set_visible,
            len(self._filtered_bookmarks()) == 0,
        )
        GLib.idle_add(self._rebuild_sidebar)
        self._notify_change()

    async def _do_move(self, url: str, folder: Optional[str]) -> None:
        await self._service.set_folder(url, folder)
        for b in self._all_bookmarks:
            if b["url"] == url:
                b["folder"] = folder
                break
        seen: list[str] = []
        for b in self._all_bookmarks:
            f = b.get("folder")
            if f and f not in seen:
                seen.append(f)
        self._folders = sorted(seen)
        GLib.idle_add(self._rebuild_sidebar)
        GLib.idle_add(self._rebuild_bm_list)
        self._notify_change()

    async def _do_rename_folder(self, old_name: str, new_name: str) -> None:
        await self._service.rename_folder(old_name, new_name)
        for b in self._all_bookmarks:
            if b.get("folder") == old_name:
                b["folder"] = new_name
        if old_name in self._folders:
            idx = self._folders.index(old_name)
            self._folders[idx] = new_name
            self._folders.sort()
        if self._selected_folder == old_name:
            self._selected_folder = new_name
        GLib.idle_add(self._rebuild_sidebar)
        GLib.idle_add(self._rebuild_bm_list)
        self._notify_change()

    async def _do_delete_folder(self, folder_name: str) -> None:
        await self._service.rename_folder(folder_name, None)
        for b in self._all_bookmarks:
            if b.get("folder") == folder_name:
                b["folder"] = None
        self._folders = [f for f in self._folders if f != folder_name]
        if self._selected_folder == folder_name:
            self._selected_folder = _ALL
        GLib.idle_add(self._rebuild_sidebar)
        GLib.idle_add(self._rebuild_bm_list)
        self._notify_change()
