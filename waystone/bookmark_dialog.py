"""Bookmark manager dialog with folder support."""

import html as _html_mod
import html.parser as _html_parser
import time
from typing import Optional
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, Gdk, Pango, GLib, Gio

from . import async_utils
from .bookmark_service import BookmarkService

# Folder-selection sentinels
_ALL       = "__all__"          # show every bookmark
_UNFILED   = "__none__"         # show only bookmarks with folder = NULL
_BAR_FOLDER = "Bookmarks Bar"   # reserved folder — always pinned in sidebar and Move popover


# ---------------------------------------------------------------------------
# Netscape HTML bookmark format helpers
# ---------------------------------------------------------------------------

class _NetscapeParser(_html_parser.HTMLParser):
    """Parses Netscape-format HTML bookmark files."""

    def __init__(self):
        super().__init__()
        self.bookmarks: list[dict] = []
        self._folder_stack: list[Optional[str]] = []
        self._current_folder: Optional[str] = None
        self._pending_folder: Optional[str] = None  # H3 text, activated on next <DL>
        self._in_a = False
        self._in_h3 = False
        self._pending_url: Optional[str] = None
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a":
            self._in_a = True
            self._pending_url = attrs_dict.get("href", "")
            self._buf = ""
        elif tag == "h3":
            self._in_h3 = True
            self._buf = ""
        elif tag == "dl":
            # Push parent folder; if an H3 preceded this DL, activate it now.
            self._folder_stack.append(self._current_folder)
            if self._pending_folder is not None:
                # Build a path-encoded name so hierarchy is preserved ("Parent/Child").
                if self._current_folder:
                    self._current_folder = f"{self._current_folder}/{self._pending_folder}"
                else:
                    self._current_folder = self._pending_folder
                self._pending_folder = None

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            self._in_a = False
            url = (self._pending_url or "").strip()
            if url:
                self.bookmarks.append({
                    "url": url,
                    "title": self._buf.strip(),
                    "folder": self._current_folder,
                })
            self._pending_url = None
            self._buf = ""
        elif tag == "h3" and self._in_h3:
            self._in_h3 = False
            # Don't activate yet — wait for the <DL> that follows.
            self._pending_folder = self._buf.strip() or None
            self._buf = ""
        elif tag == "dl" and self._folder_stack:
            # Restore parent folder when leaving a DL block.
            self._current_folder = self._folder_stack.pop()

    def handle_data(self, data):
        if self._in_a or self._in_h3:
            self._buf += data


def _build_netscape_html(bookmarks: list[dict]) -> str:
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Waystone Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]

    unfiled = [b for b in bookmarks if not b.get("folder")]
    by_folder: dict[str, list[dict]] = {}
    for b in bookmarks:
        f = b.get("folder")
        if f:
            by_folder.setdefault(f, []).append(b)

    for b in unfiled:
        title = _html_mod.escape(b["title"] or b["url"])
        url   = _html_mod.escape(b["url"])
        ts    = b.get("created_at", int(time.time()))
        lines.append(f'    <DT><A HREF="{url}" ADD_DATE="{ts}">{title}</A>')

    for folder_name in sorted(by_folder):
        lines.append(f'    <DT><H3>{_html_mod.escape(folder_name)}</H3>')
        lines.append("    <DL><p>")
        for b in by_folder[folder_name]:
            title = _html_mod.escape(b["title"] or b["url"])
            url   = _html_mod.escape(b["url"])
            ts    = b.get("created_at", int(time.time()))
            lines.append(f'        <DT><A HREF="{url}" ADD_DATE="{ts}">{title}</A>')
        lines.append("    </DL><p>")

    lines.append("</DL><p>")
    return "\n".join(lines)


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

        self._service         = service
        self._open_url_cb     = open_url_cb
        self._on_change_cb    = on_change_cb  # called after any mutation
        self._all_bookmarks:  list[dict] = []
        self._folders:        list[str]  = []
        self._selected_folder: str       = _ALL
        self._folder_rows:    dict[str, Gtk.ListBoxRow] = {}
        self._checked_folders: set[str]  = set()

        self._build_ui()
        self.present()
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

        btn_clear = Gtk.Button(icon_name="user-trash-symbolic")
        btn_clear.set_tooltip_text("Delete all bookmarks")
        btn_clear.add_css_class("destructive-action")
        btn_clear.connect("clicked", lambda _: self._confirm_clear_all())
        header.pack_end(btn_clear)

        self._btn_delete_selected = Gtk.Button(label="Delete Selected")
        self._btn_delete_selected.add_css_class("destructive-action")
        self._btn_delete_selected.connect("clicked", lambda _: self._confirm_delete_selected())
        self._btn_delete_selected.set_visible(False)
        header.pack_start(self._btn_delete_selected)

        btn_export = Gtk.Button(icon_name="document-send-symbolic")
        btn_export.set_tooltip_text("Export bookmarks to HTML")
        btn_export.connect("clicked", self._on_export_clicked)
        header.pack_end(btn_export)

        btn_import = Gtk.Button(icon_name="document-open-symbolic")
        btn_import.set_tooltip_text("Import bookmarks (HTML or .gmi)")
        btn_import.connect("clicked", self._on_import_clicked)
        header.pack_end(btn_import)

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
        seen: set[str] = set()
        for b in bookmarks:
            f = b.get("folder")
            if not f:
                continue
            # Include every ancestor path so intermediate folders remain visible
            # even when they have no bookmarks assigned directly.
            parts = f.split("/")
            for i in range(1, len(parts) + 1):
                seen.add("/".join(parts[:i]))
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
        self._checked_folders.clear()
        self._btn_delete_selected.set_visible(False)

        all_row    = self._make_sidebar_row("All Bookmarks", "bookmark-collection-symbolic", _ALL)
        unfiled_row = self._make_sidebar_row("Unfiled",       "folder-symbolic",              _UNFILED)
        bar_row     = self._make_sidebar_row("Bookmarks Bar", "starred-symbolic",             _BAR_FOLDER)
        self._folder_rows[_ALL]        = all_row
        self._folder_rows[_UNFILED]    = unfiled_row
        self._folder_rows[_BAR_FOLDER] = bar_row
        self._folder_list.append(all_row)
        self._folder_list.append(unfiled_row)
        self._folder_list.append(bar_row)

        for folder_name in self._folders:
            if folder_name == _BAR_FOLDER:
                continue  # already pinned above
            depth = folder_name.count("/")
            display = folder_name.rsplit("/", 1)[-1]
            row = self._make_sidebar_row(display, "folder-symbolic", folder_name, depth=depth)
            self._folder_rows[folder_name] = row
            self._folder_list.append(row)

        target = self._folder_rows.get(self._selected_folder,
                                       self._folder_rows[_ALL])
        self._folder_list.select_row(target)

    def _make_sidebar_row(self, label: str, icon: str, folder_key: str, depth: int = 0) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._folder_key = folder_key  # type: ignore[attr-defined]

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8 + depth * 16)
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

        if folder_key not in (_ALL, _UNFILED, _BAR_FOLDER):
            chk = Gtk.CheckButton()
            chk.set_valign(Gtk.Align.CENTER)
            chk.set_tooltip_text("Select for bulk delete")
            chk.connect("toggled", self._on_folder_checked, folder_key)
            box.append(chk)

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

        listbox.append(self._popover_text_row("Rename…"))
        listbox.append(self._popover_text_row("Move Under…"))
        listbox.append(self._popover_text_row("Delete Folder"))

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
            idx = r.get_index()
            if idx == 0:
                self._prompt_rename_folder(fn)
            elif idx == 1:
                self._prompt_move_folder_under(fn)
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

    def _prompt_move_folder_under(self, folder_name: str) -> None:
        """Show a dialog to pick a new parent for folder_name."""
        leaf = folder_name.rsplit("/", 1)[-1]

        # Candidate parents: Bookmarks Bar + all folders that are not the folder
        # itself and not already a descendant of it.
        candidates = [_BAR_FOLDER] + [
            f for f in self._folders
            if f != folder_name and not f.startswith(folder_name + "/")
            and f != _BAR_FOLDER
        ]

        string_list = Gtk.StringList.new(["(Top Level)"] + [c.replace("/", " › ") for c in candidates])
        dropdown = Gtk.DropDown(model=string_list)
        dropdown.set_margin_top(8)

        dlg = Adw.AlertDialog(
            heading="Move Folder Under…",
            body=f'Choose a parent for "{leaf}":',
        )
        dlg.set_extra_child(dropdown)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("move", "Move")
        dlg.set_default_response("move")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp, fn=folder_name, cands=candidates):
            if resp != "move":
                return
            idx = dropdown.get_selected()
            if idx == 0:
                # Top Level — strip any existing parent prefix
                new_path = fn.rsplit("/", 1)[-1]
            else:
                parent = cands[idx - 1]
                new_path = parent + "/" + fn.rsplit("/", 1)[-1]
            if new_path != fn:
                async_utils.run(self._do_move_folder(fn, new_path))

        dlg.connect("response", on_response)
        dlg.present(self)

    async def _do_move_folder(self, old_path: str, new_path: str) -> None:
        await self._service.move_folder(old_path, new_path)
        bookmarks = await self._service.list_all()
        GLib.idle_add(self._populate, bookmarks)
        self._notify_change()

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

        btn_move = Gtk.Button(icon_name="folder-symbolic")
        btn_move.set_valign(Gtk.Align.CENTER)
        btn_move.set_has_frame(False)
        btn_move.set_tooltip_text("Move to folder")
        btn_move.connect("clicked", lambda _, u=url: self._show_move_dialog(u))

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

    def _show_move_dialog(self, url: str) -> None:
        """Show an AlertDialog with a DropDown to move url to a folder."""
        snapshot = [f for f in self._folders if f != _BAR_FOLDER]

        folder_labels: list[str] = ["Unfiled", "Bookmarks Bar"]
        folder_values: list = [None, _BAR_FOLDER]
        for fname in snapshot:
            folder_labels.append(fname.replace("/", " › "))
            folder_values.append(fname)
        folder_labels.append("New Folder…")
        folder_values.append("__new__")

        current = next((b.get("folder") for b in self._all_bookmarks if b["url"] == url), None)
        try:
            sel = folder_values.index(current)
        except ValueError:
            sel = 0

        string_list = Gtk.StringList.new(folder_labels)
        dropdown = Gtk.DropDown(model=string_list)
        dropdown.set_selected(sel)
        dropdown.set_margin_top(8)

        dlg = Adw.AlertDialog(heading="Move to Folder", body="")
        dlg.set_extra_child(dropdown)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("move", "Move")
        dlg.set_default_response("move")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp):
            if resp != "move":
                return
            idx = dropdown.get_selected()
            if idx >= len(folder_values):
                return
            target = folder_values[idx]
            if target == "__new__":
                self._prompt_new_folder(url)
            else:
                async_utils.run(self._do_move(url, target))

        dlg.connect("response", on_response)
        dlg.present(self)

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
    # Bulk folder delete
    # ------------------------------------------------------------------

    def _on_folder_checked(self, chk: Gtk.CheckButton, folder_key: str) -> None:
        if chk.get_active():
            self._checked_folders.add(folder_key)
        else:
            self._checked_folders.discard(folder_key)
        n = len(self._checked_folders)
        self._btn_delete_selected.set_label(f"Delete Selected ({n})" if n else "Delete Selected")
        self._btn_delete_selected.set_visible(n > 0)

    def _confirm_delete_selected(self) -> None:
        folders = list(self._checked_folders)
        n = len(folders)
        if not n:
            return
        names = ", ".join(f'"{f}"' for f in sorted(folders))
        dlg = Adw.AlertDialog(
            heading=f"Delete {n} Folder{'s' if n != 1 else ''}",
            body=f"Delete {names}? Their bookmarks will be moved to Unfiled.",
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", f"Delete {n} Folder{'s' if n != 1 else ''}")
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect(
            "response",
            lambda _d, r, f=folders: async_utils.run(self._do_delete_selected(f)) if r == "delete" else None,
        )
        dlg.present(self)

    async def _do_delete_selected(self, folders: list[str]) -> None:
        for folder_name in folders:
            await self._service.rename_folder(folder_name, None)
            for b in self._all_bookmarks:
                if b.get("folder") == folder_name:
                    b["folder"] = None
        self._folders = [f for f in self._folders if f not in folders]
        if self._selected_folder in folders:
            self._selected_folder = _ALL
        GLib.idle_add(self._rebuild_sidebar)
        GLib.idle_add(self._rebuild_bm_list)
        self._notify_change()

    # ------------------------------------------------------------------
    # Clear all
    # ------------------------------------------------------------------

    def _confirm_clear_all(self) -> None:
        dlg = Adw.AlertDialog(
            heading="Delete All Bookmarks",
            body="This will permanently delete every bookmark. This cannot be undone.",
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete All")
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: async_utils.run(self._do_clear_all()) if r == "delete" else None)
        dlg.present(self)

    async def _do_clear_all(self) -> None:
        await self._service.clear_all()
        self._all_bookmarks = []
        self._folders = []
        self._selected_folder = _ALL
        GLib.idle_add(self._rebuild_sidebar)
        GLib.idle_add(self._rebuild_bm_list)
        self._notify_change()

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def _on_import_clicked(self, _btn) -> None:
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All Bookmark Files")
        all_filter.add_mime_type("text/html")
        all_filter.add_pattern("*.html")
        all_filter.add_pattern("*.htm")
        all_filter.add_pattern("*.gmi")

        html_filter = Gtk.FileFilter()
        html_filter.set_name("HTML Bookmark Files (*.html)")
        html_filter.add_mime_type("text/html")
        html_filter.add_pattern("*.html")
        html_filter.add_pattern("*.htm")

        gmi_filter = Gtk.FileFilter()
        gmi_filter.set_name("Gemini Files (*.gmi)")
        gmi_filter.add_pattern("*.gmi")

        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(all_filter)
        store.append(html_filter)
        store.append(gmi_filter)

        dialog = Gtk.FileDialog()
        dialog.set_title("Import Bookmarks")
        dialog.set_filters(store)
        dialog.set_initial_folder(Gio.File.new_for_path(GLib.get_home_dir()))
        dialog.open(self, None, self._on_import_chosen)

    def _on_import_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error as e:
            if "dismissed" not in str(e).lower() and "cancel" not in str(e).lower():
                err = Adw.AlertDialog(heading="Could Not Open File", body=str(e))
                err.add_response("ok", "OK")
                err.present(self)
            return
        if gfile:
            path = gfile.get_path()
            self._show_import_progress()
            if path.lower().endswith(".gmi"):
                async_utils.run(self._do_import_gmi(path))
            else:
                async_utils.run(self._do_import(path))

    def _show_import_progress(self) -> None:
        """Show a pulsing progress bar dialog while import runs."""
        bar = Gtk.ProgressBar()
        bar.set_pulse_step(0.1)
        bar.set_text("Importing bookmarks…")
        bar.set_show_text(True)
        bar.set_margin_top(8)
        bar.set_margin_bottom(4)

        self._import_progress_bar = bar
        self._import_pulse_id = GLib.timeout_add(80, self._pulse_import_bar)

        dlg = Adw.AlertDialog(heading="Importing…", body="")
        dlg.set_extra_child(bar)
        # No buttons — dismissed programmatically when done
        self._import_progress_dlg = dlg
        dlg.present(self)

    def _pulse_import_bar(self) -> bool:
        if hasattr(self, "_import_progress_bar"):
            self._import_progress_bar.pulse()
        return GLib.SOURCE_CONTINUE

    def _close_import_progress(self) -> None:
        if hasattr(self, "_import_pulse_id"):
            GLib.source_remove(self._import_pulse_id)
            del self._import_pulse_id
        if hasattr(self, "_import_progress_dlg"):
            self._import_progress_dlg.close()
            del self._import_progress_dlg
        if hasattr(self, "_import_progress_bar"):
            del self._import_progress_bar

    async def _do_import(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            GLib.idle_add(self._close_import_progress)
            GLib.idle_add(self._show_import_error)
            return

        parser = _NetscapeParser()
        parser.feed(content)

        count = 0
        batch: list[dict] = []
        BATCH = 50
        for bm in parser.bookmarks:
            if bm["url"]:
                await self._service.add(bm["url"], bm["title"], bm["folder"])
                count += 1
                batch.append(bm)
                if len(batch) >= BATCH:
                    # Refresh the visible list incrementally
                    bookmarks = await self._service.list_all()
                    GLib.idle_add(self._populate, bookmarks)
                    GLib.idle_add(self._notify_change)
                    batch.clear()

        bookmarks = await self._service.list_all()
        GLib.idle_add(self._close_import_progress)
        GLib.idle_add(self._populate, bookmarks)
        GLib.idle_add(self._notify_change)
        GLib.idle_add(self._show_import_done, count)

    async def _do_import_gmi(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            GLib.idle_add(self._close_import_progress)
            GLib.idle_add(self._show_import_error)
            return

        count = 0
        for line in lines:
            line = line.strip()
            if not line.startswith("=>"):
                continue
            rest = line[2:].strip()
            parts = rest.split(None, 1)
            if not parts:
                continue
            url = parts[0]
            title = parts[1].strip() if len(parts) > 1 else url
            if url:
                await self._service.add(url, title, None)
                count += 1

        bookmarks = await self._service.list_all()
        GLib.idle_add(self._close_import_progress)
        GLib.idle_add(self._populate, bookmarks)
        GLib.idle_add(self._notify_change)
        GLib.idle_add(self._show_import_done, count)

    def _show_import_error(self) -> None:
        dlg = Adw.AlertDialog(heading="Import Failed",
                              body="Could not read the selected file.")
        dlg.add_response("ok", "OK")
        dlg.present(self)

    def _show_import_done(self, count: int) -> None:
        dlg = Adw.AlertDialog(
            heading="Import Complete",
            body=f"Imported {count} bookmark{'s' if count != 1 else ''}.",
        )
        dlg.add_response("ok", "OK")
        dlg.present(self)

    def _on_export_clicked(self, _btn) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Export Bookmarks to HTML")
        dialog.set_initial_name("bookmarks.html")
        dialog.set_initial_folder(Gio.File.new_for_path(GLib.get_home_dir()))
        dialog.save(self, None, self._on_export_chosen)

    def _on_export_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as e:
            if "dismissed" not in str(e).lower() and "cancel" not in str(e).lower():
                err = Adw.AlertDialog(heading="Could Not Save File", body=str(e))
                err.add_response("ok", "OK")
                err.present(self)
            return
        if gfile:
            self._do_export(gfile.get_path())

    def _do_export(self, path: str) -> None:
        content = _build_netscape_html(self._all_bookmarks)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError:
            dlg = Adw.AlertDialog(heading="Export Failed",
                                  body="Could not write to the selected file.")
            dlg.add_response("ok", "OK")
            dlg.present(self)
            return
        dlg = Adw.AlertDialog(
            heading="Export Complete",
            body=f"Saved {len(self._all_bookmarks)} bookmark"
                 f"{'s' if len(self._all_bookmarks) != 1 else ''} to HTML.",
        )
        dlg.add_response("ok", "OK")
        dlg.present(self)

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
        seen: set[str] = set()
        for b in self._all_bookmarks:
            f = b.get("folder")
            if not f:
                continue
            parts = f.split("/")
            for i in range(1, len(parts) + 1):
                seen.add("/".join(parts[:i]))
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
