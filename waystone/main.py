import os
import sys
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, Gio, GLib

from . import async_utils

# Tab icon — prefer the PNG in data/ next to this package; fall back to themed icon.
_ICON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "waystone-icon.png")
)

def _tab_icon() -> "Gio.Icon":
    if os.path.exists(_ICON_PATH):
        return Gio.FileIcon.new(Gio.File.new_for_path(_ICON_PATH))
    return Gio.ThemedIcon.new("com.waystone.browser")
from .navigation import normalize_url, detect_scheme, Scheme
from .tab import Tab, TabKind
from .db import Database
from .bookmark_service import BookmarkService
from .history_service import HistoryService
from .tofu_store import TOFUStore
from .bookmark_dialog import BookmarkDialog
from .bookmarks_bar import BookmarksBar
from .history_dialog import HistoryDialog
from .settings_dialog import SettingsDialog
from .settings_service import SettingsService


class BrowserWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        bookmark_service: BookmarkService,
        history_service: HistoryService,
        tofu_store: TOFUStore,
        settings: SettingsService,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.set_title("Waystone")
        self.set_default_size(1280, 800)
        self.set_icon_name("com.waystone.browser")
        self.connect("close-request", self._on_close_request)

        self._bookmarks = bookmark_service
        self._history = history_service
        self._tofu = tofu_store
        self._settings = settings
        self._tabs: dict[object, Tab] = {}

        self._build_ui()
        self._register_actions()
        self._restore_or_new_tab()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        self.tab_view = Adw.TabView()
        self.tab_view.set_vexpand(True)
        self.tab_view.connect("notify::selected-page", self._on_tab_selected)
        self.tab_view.connect("close-page", self._on_tab_close)

        tab_bar = Adw.TabBar()
        tab_bar.set_view(self.tab_view)
        tab_bar.set_autohide(False)

        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_forward = Gtk.Button(icon_name="go-next-symbolic")
        self.btn_reload = Gtk.Button(icon_name="view-refresh-symbolic")
        self.btn_back.set_tooltip_text("Back")
        self.btn_forward.set_tooltip_text("Forward")
        self.btn_reload.set_tooltip_text("Reload")
        self.btn_back.connect("clicked", lambda _: self._active_tab_action("back"))
        self.btn_forward.connect("clicked", lambda _: self._active_tab_action("forward"))
        self.btn_reload.connect("clicked", lambda _: self._active_tab_action("reload"))

        self.address_bar = Gtk.Entry()
        self.address_bar.set_placeholder_text("Enter URL…")
        self.address_bar.set_hexpand(True)
        self.address_bar.connect("activate", self._on_navigate)

        self.btn_bookmark = Gtk.Button(icon_name="bookmark-new-symbolic")
        self.btn_bookmark.set_tooltip_text("Bookmark this page")
        self.btn_bookmark.connect("clicked", self._on_bookmark_clicked)

        btn_new_tab = Gtk.Button(icon_name="tab-new-symbolic")
        btn_new_tab.set_tooltip_text("New Tab")
        btn_new_tab.connect("clicked", lambda _: self._open_new_tab())

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Menu")
        menu_btn.set_menu_model(self._build_menu())

        header = Adw.HeaderBar()
        header.pack_start(self.btn_back)
        header.pack_start(self.btn_forward)
        header.pack_start(self.btn_reload)
        header.set_title_widget(self.address_bar)
        header.pack_end(menu_btn)
        header.pack_end(btn_new_tab)
        header.pack_end(self.btn_bookmark)

        self._bookmarks_bar = BookmarksBar(
            service=self._bookmarks,
            open_url_cb=self._open_url_from_dialog,
        )
        self._bookmarks_bar.set_visible(self._settings.show_bookmarks_bar)

        self._find_bar = self._build_find_bar()

        root.append(header)
        root.append(self._bookmarks_bar)
        root.append(tab_bar)
        root.append(self._find_bar)
        root.append(self.tab_view)

        self._update_nav_buttons(None)

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Bookmarks…",     "win.show-bookmarks")
        menu.append("History…",       "win.show-history")
        menu.append("Settings…",      "win.show-settings")
        menu.append("About Waystone", "win.show-about")
        return menu

    def _register_actions(self):
        for name, cb in [
            # Dialogs / UI toggles
            ("show-bookmarks",       lambda *_: self._show_bookmarks()),
            ("show-history",         lambda *_: self._show_history()),
            ("show-settings",        lambda *_: self._show_settings()),
            ("toggle-bookmarks-bar", lambda *_: self._toggle_bookmarks_bar()),
            ("toggle-bookmark",      lambda *_: self._on_bookmark_clicked(None)),
            # Address bar / tabs
            ("focus-address-bar",    lambda *_: self.address_bar.grab_focus()),
            ("new-tab",              lambda *_: self._open_new_tab()),
            ("close-tab",            lambda *_: self._close_current_tab()),
            ("next-tab",             lambda *_: self._next_tab()),
            ("prev-tab",             lambda *_: self._prev_tab()),
            # Navigation
            ("go-back",              lambda *_: self._active_tab_action("back")),
            ("go-forward",           lambda *_: self._active_tab_action("forward")),
            ("reload",               lambda *_: self._active_tab_action("reload")),
            ("reload-hard",          lambda *_: self._active_tab_action("reload-hard")),
            # Zoom
            ("zoom-in",              lambda *_: self._active_tab_action("zoom-in")),
            ("zoom-out",             lambda *_: self._active_tab_action("zoom-out")),
            ("zoom-reset",           lambda *_: self._active_tab_action("zoom-reset")),
            # Find / Print / About
            ("find",                 lambda *_: self._show_find()),
            ("find-next",            lambda *_: self._find_next()),
            ("find-prev",            lambda *_: self._find_prev()),
            ("print",                lambda *_: self._print_page()),
            ("show-about",           lambda *_: self._show_about()),
            # Duplicate tab
            ("duplicate-tab",        lambda *_: self._duplicate_tab()),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

        app = self.get_application()
        # Address bar / tabs
        app.set_accels_for_action("win.focus-address-bar",    ["<Control>l"])
        app.set_accels_for_action("win.new-tab",              ["<Control>t"])
        app.set_accels_for_action("win.close-tab",            ["<Control>w"])
        app.set_accels_for_action("win.next-tab",             ["<Control>Tab"])
        app.set_accels_for_action("win.prev-tab",             ["<Control><Shift>Tab"])
        # Bookmarks
        app.set_accels_for_action("win.toggle-bookmarks-bar", ["<Control><Shift>b"])
        app.set_accels_for_action("win.toggle-bookmark",      ["<Control>d"])
        # Navigation
        app.set_accels_for_action("win.go-back",              ["<Alt>Left"])
        app.set_accels_for_action("win.go-forward",           ["<Alt>Right"])
        app.set_accels_for_action("win.reload",               ["F5", "<Control>r"])
        app.set_accels_for_action("win.reload-hard",          ["<Control><Shift>r"])
        # Zoom
        app.set_accels_for_action("win.zoom-in",              ["<Control>equal", "<Control>plus"])
        app.set_accels_for_action("win.zoom-out",             ["<Control>minus"])
        app.set_accels_for_action("win.zoom-reset",           ["<Control>0"])
        # Find / Print / Duplicate
        app.set_accels_for_action("win.find",                 ["<Control>f"])
        app.set_accels_for_action("win.find-next",            ["F3", "<Control>g"])
        app.set_accels_for_action("win.find-prev",            ["<Shift>F3", "<Control><Shift>g"])
        app.set_accels_for_action("win.print",                ["<Control>p"])
        app.set_accels_for_action("win.duplicate-tab",        ["<Control><Shift>t"])

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _open_new_tab(self, url: str = ""):
        # If no URL given and a homepage is configured, navigate there instead.
        if not url and self._settings.homepage:
            url = normalize_url(self._settings.homepage)

        kind = self._kind_for_url(url) if url else TabKind.WEB
        tab = Tab(
            kind=kind,
            url=url,
            js_enabled=self._settings.js_enabled,
            tofu_store=self._tofu,
            tofu_prompt_cb=self._prompt_tofu,
            input_prompt_cb=self._prompt_input,
            save_as_cb=self._save_as,
            open_url_cb=self._open_new_tab,
            on_title_changed=self._on_tab_title_changed,
            on_uri_changed=self._on_tab_uri_changed,
            on_nav_state_changed=self._on_tab_nav_state_changed,
            on_load_started=self._on_tab_load_started,
            on_load_finished=self._on_tab_load_finished,
            on_favicon_changed=self._on_tab_favicon_changed,
        )
        page = self.tab_view.append(tab.widget)
        page.set_title("New Tab")
        page.set_icon(_tab_icon())
        self._tabs[page] = tab
        self.tab_view.set_selected_page(page)

        if url:
            self.address_bar.set_text(url)
        else:
            self.address_bar.set_text("")
            self.address_bar.grab_focus()

        return tab

    def _kind_for_url(self, url: str) -> TabKind:
        return {
            Scheme.HTTP:   TabKind.WEB,
            Scheme.HTTPS:  TabKind.WEB,
            Scheme.GEMINI: TabKind.GEMINI,
            Scheme.GOPHER: TabKind.GOPHER,
        }.get(detect_scheme(url), TabKind.WEB)

    def _active_tab(self) -> Tab | None:
        page = self.tab_view.get_selected_page()
        return self._tabs.get(page) if page else None

    def _active_tab_action(self, action: str):
        tab = self._active_tab()
        if not tab:
            return
        {
            "back":        tab.go_back,
            "forward":     tab.go_forward,
            "reload":      tab.reload,
            "reload-hard": tab.reload_hard,
            "zoom-in":     tab.zoom_in,
            "zoom-out":    tab.zoom_out,
            "zoom-reset":  tab.zoom_reset,
        }[action]()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_navigate(self, entry):
        raw = entry.get_text().strip()
        if not raw:
            return
        url = normalize_url(raw)
        tab = self._active_tab()
        if tab is None:
            return
        if self._kind_for_url(url) != tab.kind:
            self._open_new_tab(url)
        else:
            tab.navigate(url)
            entry.set_text(url)

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def _on_bookmark_clicked(self, _btn):
        tab = self._active_tab()
        if not tab:
            return
        url = tab.get_uri()
        title = tab.get_title()
        async_utils.run(self._toggle_bookmark_async(url, title))

    async def _toggle_bookmark_async(self, url: str, title: str):
        if not url or url == "about:blank":
            return
        if await self._bookmarks.is_bookmarked(url):
            await self._bookmarks.remove(url)
            GLib.idle_add(self._set_bookmark_icon, False)
        else:
            await self._bookmarks.add(url, title)
            GLib.idle_add(self._set_bookmark_icon, True)
        GLib.idle_add(self._bookmarks_bar.refresh)

    async def _refresh_bookmark_star_async(self, url: str):
        if not url or url == "about:blank":
            GLib.idle_add(self._set_bookmark_icon, False)
            return
        bookmarked = await self._bookmarks.is_bookmarked(url)
        GLib.idle_add(self._set_bookmark_icon, bookmarked)

    def _set_bookmark_icon(self, bookmarked: bool):
        self.btn_bookmark.set_icon_name(
            "starred-symbolic" if bookmarked else "bookmark-new-symbolic"
        )

    def _show_bookmarks(self):
        dlg = BookmarkDialog(
            parent=self,
            service=self._bookmarks,
            open_url_cb=self._open_url_from_dialog,
            on_change_cb=self._bookmarks_bar.refresh,
        )
        dlg.present()

    def _toggle_bookmarks_bar(self) -> None:
        visible = not self._bookmarks_bar.get_visible()
        self._bookmarks_bar.set_visible(visible)
        self._settings.show_bookmarks_bar = visible

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _show_history(self):
        HistoryDialog(
            parent=self,
            service=self._history,
            open_url_cb=self._open_url_from_dialog,
        ).present()

    def _show_settings(self):
        SettingsDialog(
            parent=self,
            settings=self._settings,
            tofu_store=self._tofu,
        )

    # ------------------------------------------------------------------
    # Save As dialog (called from async thread; dialog on GTK thread)
    # ------------------------------------------------------------------

    async def _save_as(self, filename: str) -> "Optional[str]":
        loop = async_utils.get_loop()
        future = loop.create_future()

        def show():
            dlg = Gtk.FileDialog()
            dlg.set_initial_name(filename)

            def on_done(d, result):
                try:
                    f = d.save_finish(result)
                    loop.call_soon_threadsafe(future.set_result, f.get_path())
                except Exception:
                    loop.call_soon_threadsafe(future.set_result, None)

            dlg.save(self, None, on_done)

        GLib.idle_add(show)
        return await future

    def _open_url_from_dialog(self, url: str):
        tab = self._active_tab()
        if tab and tab.kind == self._kind_for_url(url):
            tab.navigate(url)
            self.address_bar.set_text(url)
        else:
            self._open_new_tab(url)

    # ------------------------------------------------------------------
    # Input prompt (Gemini 1x / Gopher type-7 search)
    # Called from async thread; dialog shown on GTK thread.
    # ------------------------------------------------------------------

    async def _prompt_input(self, prompt: str, sensitive: bool) -> "Optional[str]":
        loop = async_utils.get_loop()
        future = loop.create_future()

        def show():
            entry = Gtk.Entry()
            entry.set_activates_default(True)
            entry.set_margin_top(8)
            if sensitive:
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)

            dlg = Adw.AlertDialog(heading="Input Required", body=prompt)
            dlg.set_extra_child(entry)
            dlg.add_response("cancel", "Cancel")
            dlg.add_response("ok", "OK")
            dlg.set_default_response("ok")
            dlg.set_close_response("cancel")
            dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

            def on_response(_d, resp):
                value = entry.get_text() if resp == "ok" else None
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, value)

            dlg.connect("response", on_response)
            dlg.present(self)

        GLib.idle_add(show)
        return await future

    # ------------------------------------------------------------------
    # TOFU prompt (called from async thread; dialog shown on GTK thread)
    # ------------------------------------------------------------------

    async def _prompt_tofu(self, host: str, port: int, fingerprint: str, changed: bool) -> bool:
        loop = async_utils.get_loop()
        future = loop.create_future()

        def show():
            heading = "Certificate Changed" if changed else "New Certificate"
            lines = []
            if changed:
                lines.append(
                    "⚠ The certificate for this host has changed.\n"
                    "This may indicate a server reconfiguration or a MITM attack."
                )
            lines += [
                f"Host:     {host}",
                f"Port:     {port}",
                f"SHA-256:  {fingerprint[:16]}…{fingerprint[-8:]}",
            ]
            dlg = Adw.AlertDialog(heading=heading, body="\n".join(lines))
            dlg.add_response("deny", "Deny")
            dlg.add_response("trust", "Trust")
            dlg.set_default_response("deny")
            dlg.set_close_response("deny")
            dlg.set_response_appearance(
                "trust",
                Adw.ResponseAppearance.DESTRUCTIVE
                if changed
                else Adw.ResponseAppearance.SUGGESTED,
            )

            def on_response(_d, resp):
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, resp == "trust")

            dlg.connect("response", on_response)
            dlg.present(self)

        GLib.idle_add(show)
        return await future

    # ------------------------------------------------------------------
    # Tab view signals
    # ------------------------------------------------------------------

    def _on_tab_selected(self, _tv, _param):
        tab = self._active_tab()
        if not tab:
            self.address_bar.set_text("")
            self._update_nav_buttons(None)
            self._set_bookmark_icon(False)
            return
        uri = tab.get_uri()
        self.address_bar.set_text(uri)
        self._update_nav_buttons(tab)
        async_utils.run(self._refresh_bookmark_star_async(uri))
        self._update_window_title(tab)
        self._run_find()

    def _close_current_tab(self):
        page = self.tab_view.get_selected_page()
        if page:
            self.tab_view.close_page(page)

    def _next_tab(self):
        page = self.tab_view.get_selected_page()
        if page is None:
            return
        n = self.tab_view.get_n_pages()
        if n > 1:
            pos = self.tab_view.get_page_position(page)
            self.tab_view.set_selected_page(self.tab_view.get_nth_page((pos + 1) % n))

    def _prev_tab(self):
        page = self.tab_view.get_selected_page()
        if page is None:
            return
        n = self.tab_view.get_n_pages()
        if n > 1:
            pos = self.tab_view.get_page_position(page)
            self.tab_view.set_selected_page(self.tab_view.get_nth_page((pos - 1) % n))

    def _on_tab_close(self, tab_view, page):
        self._tabs.pop(page, None)
        tab_view.close_page_finish(page, True)
        return True

    # ------------------------------------------------------------------
    # Tab callbacks (all called on GTK thread)
    # ------------------------------------------------------------------

    def _on_tab_title_changed(self, tab: Tab, title: str):
        page = self._page_for_tab(tab)
        if page:
            page.set_title(title or "New Tab")
        if tab is self._active_tab():
            self._update_window_title(tab)

    def _on_tab_uri_changed(self, tab: Tab, uri: str):
        if tab is self._active_tab():
            self.address_bar.set_text(uri)
            async_utils.run(self._refresh_bookmark_star_async(uri))

    def _on_tab_nav_state_changed(self, tab: Tab):
        if tab is self._active_tab():
            self._update_nav_buttons(tab)

    def _on_tab_load_started(self, tab: Tab):
        if tab is self._active_tab():
            self.btn_reload.set_icon_name("process-stop-symbolic")

    def _on_tab_load_finished(self, tab: Tab):
        if tab is self._active_tab():
            self.btn_reload.set_icon_name("view-refresh-symbolic")
            self._run_find()
        uri = tab.get_uri()
        title = tab.get_title()
        if uri and uri != "about:blank":
            async_utils.run(self._history.record(uri, title))

    # ------------------------------------------------------------------
    # Find bar
    # ------------------------------------------------------------------

    def _build_find_bar(self) -> Gtk.SearchBar:
        bar = Gtk.SearchBar()
        bar.set_show_close_button(True)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self._find_entry = Gtk.SearchEntry()
        self._find_entry.set_hexpand(True)
        self._find_entry.set_placeholder_text("Find in page…")
        self._find_entry.connect("search-changed", self._on_find_changed)
        self._find_entry.connect("activate", lambda _: self._find_next())

        btn_prev = Gtk.Button(icon_name="go-up-symbolic")
        btn_prev.set_tooltip_text("Previous match (Shift+F3)")
        btn_prev.add_css_class("flat")
        btn_prev.connect("clicked", lambda _: self._find_prev())

        btn_next = Gtk.Button(icon_name="go-down-symbolic")
        btn_next.set_tooltip_text("Next match (F3)")
        btn_next.add_css_class("flat")
        btn_next.connect("clicked", lambda _: self._find_next())

        self._find_count_label = Gtk.Label(label="")
        self._find_count_label.add_css_class("dim-label")
        self._find_count_label.set_width_chars(14)
        self._find_count_label.set_xalign(0.0)

        row.append(self._find_entry)
        row.append(btn_prev)
        row.append(btn_next)
        row.append(self._find_count_label)

        bar.set_child(row)
        bar.connect_entry(self._find_entry)
        bar.connect("notify::search-mode-enabled", self._on_find_bar_toggled)
        return bar

    def _show_find(self):
        self._find_bar.set_search_mode(True)
        self._find_entry.grab_focus()

    def _on_find_changed(self, _entry):
        self._run_find()

    def _run_find(self):
        if not hasattr(self, "_find_bar") or not hasattr(self, "_find_entry"):
            return
        text = self._find_entry.get_text()
        tab = self._active_tab()
        if not tab:
            self._find_count_label.set_label("")
            return
        if self._find_bar.get_search_mode() and text:
            count = tab.find(text)
            if isinstance(count, int):
                if count == 0:
                    self._find_count_label.set_label("No matches")
                else:
                    self._find_count_label.set_label(
                        f"{count} match{'es' if count != 1 else ''}"
                    )
            else:
                self._find_count_label.set_label("")
        else:
            tab.find_clear()
            self._find_count_label.set_label("")

    def _find_next(self):
        tab = self._active_tab()
        if tab:
            tab.find_next()

    def _find_prev(self):
        tab = self._active_tab()
        if tab:
            tab.find_prev()

    def _on_find_bar_toggled(self, bar, _param):
        if not bar.get_search_mode():
            tab = self._active_tab()
            if tab:
                tab.find_clear()
            self._find_count_label.set_label("")

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------

    def _print_page(self):
        tab = self._active_tab()
        if tab:
            tab.print_page(self)

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def _show_about(self):
        Adw.AboutDialog(
            application_name="Waystone",
            application_icon="com.waystone.browser",
            developer_name="Nick Burchett",
            version="0.1.0",
            website="https://github.com/njb1966/waystone-browser",
            issue_url="https://github.com/njb1966/waystone-browser/issues",
            license_type=Gtk.License.MIT_X11,
            developers=["Nick Burchett"],
            comments="A multi-protocol browser for Linux supporting "
                     "HTTP/HTTPS, Gemini, and Gopher.",
        ).present(self)

    # ------------------------------------------------------------------
    # Window title
    # ------------------------------------------------------------------

    def _update_window_title(self, tab: "Tab | None" = None):
        if tab is None:
            tab = self._active_tab()
        if tab:
            title = tab.get_title()
            if title and title != "New Tab":
                self.set_title(f"{title} — Waystone")
                return
        self.set_title("Waystone")

    # ------------------------------------------------------------------
    # Favicon
    # ------------------------------------------------------------------

    def _on_tab_favicon_changed(self, tab: "Tab", icon: "Optional[Gio.Icon]"):
        page = self._page_for_tab(tab)
        if page:
            page.set_icon(icon if icon is not None else _tab_icon())

    # ------------------------------------------------------------------
    # Duplicate tab
    # ------------------------------------------------------------------

    def _duplicate_tab(self):
        tab = self._active_tab()
        if tab:
            url = tab.get_uri()
            if url and url != "about:blank":
                self._open_new_tab(url)

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _restore_or_new_tab(self):
        """Open the previous session's tabs, or a single new tab if none saved."""
        urls = self._settings.session_urls
        if urls:
            for url in urls:
                self._open_new_tab(url)
        else:
            self._open_new_tab()

    def _on_close_request(self, _win) -> bool:
        """Save open tab URLs so they can be restored next launch."""
        urls = []
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            tab = self._tabs.get(page)
            if tab:
                url = tab.get_uri()
                if url and url != "about:blank":
                    urls.append(url)
        self._settings.session_urls = urls
        return False  # allow the window to close

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_nav_buttons(self, tab: Tab | None):
        self.btn_back.set_sensitive(tab.can_go_back() if tab else False)
        self.btn_forward.set_sensitive(tab.can_go_forward() if tab else False)
        self.btn_reload.set_sensitive(tab is not None)

    def _page_for_tab(self, tab: Tab) -> object | None:
        for page, t in self._tabs.items():
            if t is tab:
                return page
        return None


class WaystoneApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.waystone.browser")
        self._db = Database()
        self._settings = SettingsService()
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_activate(self, app):
        self.hold()  # prevent app from quitting before window is ready
        fut = async_utils.run(self._async_init(app))
        fut.add_done_callback(self._on_init_done)

    def _on_init_done(self, fut):
        exc = fut.exception()
        if exc:
            import traceback
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            GLib.idle_add(self.release)
            GLib.idle_add(self.quit)

    async def _async_init(self, app):
        await self._db.connect()
        bookmarks = BookmarkService(self._db)
        history = HistoryService(self._db)
        tofu = TOFUStore(self._db)
        GLib.idle_add(self._create_window, app, bookmarks, history, tofu)

    def _create_window(self, app, bookmarks, history, tofu):
        # Apply saved color scheme before presenting the window
        _scheme_map = {
            "default": Adw.ColorScheme.DEFAULT,
            "light":   Adw.ColorScheme.FORCE_LIGHT,
            "dark":    Adw.ColorScheme.FORCE_DARK,
        }
        Adw.StyleManager.get_default().set_color_scheme(
            _scheme_map.get(self._settings.color_scheme, Adw.ColorScheme.DEFAULT)
        )

        win = BrowserWindow(
            bookmark_service=bookmarks,
            history_service=history,
            tofu_store=tofu,
            settings=self._settings,
            application=app,
        )
        win.present()
        self.release()  # balance hold() from _on_activate

    def _on_shutdown(self, _app):
        fut = async_utils.run(self._db.close())
        try:
            fut.result(timeout=2.0)
        except Exception:
            pass
        async_utils.stop()


def main():
    async_utils.start()
    app = WaystoneApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
