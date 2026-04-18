"""Tab: owns a renderer widget and exposes a uniform navigation interface."""

from enum import Enum, auto
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse, urljoin, quote

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit, GLib, Gio

from . import async_utils
from .gemini_client import fetch as gemini_fetch, GeminiError
from .gopher_client import (
    fetch as gopher_fetch, parse_menu, parse_url as gopher_parse_url,
    GopherError, BINARY_TYPES,
)
from .tofu_store import TOFUStore
from .text_viewer import TextViewer
from .themes import TextTheme, THEMES, DEFAULT_THEME_ID


class TabKind(Enum):
    WEB = auto()
    GEMINI = auto()
    GOPHER = auto()
    BLANK = auto()


class Tab:
    """
    One browser tab.  Owns its renderer widget.

    Callbacks set by BrowserWindow (always called on the GTK thread):
      on_title_changed(tab, title)
      on_uri_changed(tab, uri)
      on_nav_state_changed(tab)
      on_load_started(tab)
      on_load_finished(tab)

    For Gemini tabs also pass:
      tofu_store: TOFUStore
      tofu_prompt_cb: async (host, port, fingerprint, changed) -> bool

    For Gopher tabs also pass:
      save_as_cb:   async (filename: str) -> Optional[str]
      open_url_cb:  (url: str) -> None  — for h-type cross-scheme links

    js_enabled: whether to enable JavaScript in new WebKit views (default True)
    input_prompt_cb: async (prompt, sensitive) -> Optional[str]
    """

    def __init__(
        self,
        kind: TabKind,
        url: str = "",
        js_enabled: bool = True,
        tofu_store: Optional[TOFUStore] = None,
        tofu_prompt_cb: Optional[Callable] = None,
        input_prompt_cb: Optional[Callable] = None,
        save_as_cb: Optional[Callable] = None,
        open_url_cb: Optional[Callable] = None,
        on_title_changed: Optional[Callable] = None,
        on_uri_changed: Optional[Callable] = None,
        on_nav_state_changed: Optional[Callable] = None,
        on_load_started: Optional[Callable] = None,
        on_load_finished: Optional[Callable] = None,
        on_favicon_changed: Optional[Callable] = None,
        text_theme: Optional[TextTheme] = None,
    ):
        self.kind = kind
        self.current_url = url
        self._js_enabled = js_enabled
        self._zoom_level: float = 1.0
        self._spinner: Optional[Gtk.Spinner] = None
        self._page_title: str = ""
        self._tofu = tofu_store
        self._tofu_prompt_cb = tofu_prompt_cb
        self._input_prompt_cb = input_prompt_cb
        self._save_as_cb = save_as_cb
        self._open_url_cb = open_url_cb
        self._on_title_changed = on_title_changed
        self._on_uri_changed = on_uri_changed
        self._on_nav_state_changed = on_nav_state_changed
        self._on_load_started = on_load_started
        self._on_load_finished = on_load_finished
        self._on_favicon_changed = on_favicon_changed
        self._text_theme = text_theme or THEMES[DEFAULT_THEME_ID]

        # Back/forward stack for Gemini and Gopher
        self._nav_history: list[str] = []
        self._nav_pos: int = -1

        if kind == TabKind.WEB:
            self.widget = self._build_web_view(url)
        elif kind == TabKind.GEMINI:
            self.widget = self._build_gemini_view(url)
        elif kind == TabKind.GOPHER:
            self.widget = self._build_gopher_view(url)
        else:
            self.widget = self._build_placeholder("")

    # ------------------------------------------------------------------
    # Public navigation interface (called from GTK thread)
    # ------------------------------------------------------------------

    def navigate(self, url: str):
        self.current_url = url
        if self.kind == TabKind.WEB:
            self._web_view.load_uri(url)
        elif self.kind == TabKind.GEMINI:
            async_utils.run(self._gemini_navigate(url, push=True))
        elif self.kind == TabKind.GOPHER:
            async_utils.run(self._gopher_navigate(url, push=True))

    def go_back(self):
        if self.kind == TabKind.WEB:
            if self._web_view.can_go_back():
                self._web_view.go_back()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER) and self._nav_pos > 0:
            self._nav_pos -= 1
            url = self._nav_history[self._nav_pos]
            fn = self._gemini_navigate if self.kind == TabKind.GEMINI else self._gopher_navigate
            async_utils.run(fn(url, push=False))

    def go_forward(self):
        if self.kind == TabKind.WEB:
            if self._web_view.can_go_forward():
                self._web_view.go_forward()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER) and \
                self._nav_pos < len(self._nav_history) - 1:
            self._nav_pos += 1
            url = self._nav_history[self._nav_pos]
            fn = self._gemini_navigate if self.kind == TabKind.GEMINI else self._gopher_navigate
            async_utils.run(fn(url, push=False))

    def reload(self):
        if self.kind == TabKind.WEB:
            self._web_view.reload()
        elif self.kind == TabKind.GEMINI and self.current_url:
            async_utils.run(self._gemini_navigate(self.current_url, push=False))
        elif self.kind == TabKind.GOPHER and self.current_url:
            async_utils.run(self._gopher_navigate(self.current_url, push=False))

    def reload_hard(self):
        """Bypass cache for web tabs; same as reload for Gemini/Gopher."""
        if self.kind == TabKind.WEB:
            self._web_view.reload_bypass_cache()
        else:
            self.reload()

    def zoom_in(self):
        if self.kind == TabKind.WEB:
            self._zoom_level = min(3.0, round(self._zoom_level + 0.1, 1))
            self._web_view.set_zoom_level(self._zoom_level)

    def zoom_out(self):
        if self.kind == TabKind.WEB:
            self._zoom_level = max(0.25, round(self._zoom_level - 0.1, 1))
            self._web_view.set_zoom_level(self._zoom_level)

    def zoom_reset(self):
        if self.kind == TabKind.WEB:
            self._zoom_level = 1.0
            self._web_view.set_zoom_level(1.0)

    def can_go_back(self) -> bool:
        if self.kind == TabKind.WEB:
            return self._web_view.can_go_back()
        return self._nav_pos > 0

    def can_go_forward(self) -> bool:
        if self.kind == TabKind.WEB:
            return self._web_view.can_go_forward()
        return self._nav_pos < len(self._nav_history) - 1

    def get_title(self) -> str:
        if self.kind == TabKind.WEB:
            return self._web_view.get_title() or self.current_url or "New Tab"
        if self._page_title:
            return self._page_title
        parsed = urlparse(self.current_url)
        return (parsed.netloc + parsed.path) if parsed.netloc else (self.current_url or "New Tab")

    def get_uri(self) -> str:
        if self.kind == TabKind.WEB:
            return self._web_view.get_uri() or self.current_url
        return self.current_url

    # ------------------------------------------------------------------
    # Widget builders (called from GTK thread)
    # ------------------------------------------------------------------

    def _build_web_view(self, url: str) -> Gtk.Widget:
        self._web_view = WebKit.WebView()
        self._web_view.set_vexpand(True)
        self._web_view.set_hexpand(True)
        self._web_view.get_settings().set_enable_javascript(self._js_enabled)
        self._web_view.connect("notify::title",   self._on_wk_title)
        self._web_view.connect("notify::uri",     self._on_wk_uri)
        self._web_view.connect("notify::favicon", self._on_wk_favicon)
        self._web_view.connect("load-changed",    self._on_wk_load_changed)
        self._web_view.connect("decide-policy",   self._on_wk_decide_policy)
        self._web_view.connect("context-menu",    self._on_wk_context_menu)
        if url:
            self._web_view.load_uri(url)
        return self._web_view

    def _build_gemini_view(self, url: str) -> Gtk.Widget:
        self._viewer = TextViewer(navigate_cb=self._on_gemini_link_clicked)
        self._viewer.apply_theme(self._text_theme)
        overlay = self._make_spinner_overlay()
        if url:
            async_utils.run(self._gemini_navigate(url, push=True))
        return overlay

    def _build_gopher_view(self, url: str) -> Gtk.Widget:
        self._viewer = TextViewer(navigate_cb=self._on_gopher_link_clicked)
        self._viewer.apply_theme(self._text_theme)
        overlay = self._make_spinner_overlay()
        if url:
            async_utils.run(self._gopher_navigate(url, push=True))
        return overlay

    def _make_spinner_overlay(self) -> Gtk.Overlay:
        """Wrap self._viewer in an overlay that shows a spinner during loads."""
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(48, 48)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self._spinner.set_valign(Gtk.Align.CENTER)
        self._spinner.set_visible(False)

        overlay = Gtk.Overlay()
        overlay.set_vexpand(True)
        overlay.set_hexpand(True)
        overlay.set_child(self._viewer)
        overlay.add_overlay(self._spinner)
        return overlay

    def _build_placeholder(self, message: str) -> Gtk.Widget:
        label = Gtk.Label(label=message)
        label.set_vexpand(True)
        label.set_hexpand(True)
        return label

    # ------------------------------------------------------------------
    # Link click handlers (GTK thread → async thread)
    # ------------------------------------------------------------------

    def _on_gemini_link_clicked(self, url: str):
        async_utils.run(self._gemini_navigate(url, push=True))

    def _on_gopher_link_clicked(self, url: str):
        if url.startswith("http://") or url.startswith("https://"):
            # h-type HTML link — open in a Web tab via BrowserWindow callback
            if self._open_url_cb:
                self._open_url_cb(url)
        else:
            async_utils.run(self._gopher_navigate(url, push=True))

    # ------------------------------------------------------------------
    # Gemini navigation (runs on async thread)
    # ------------------------------------------------------------------

    async def _gemini_navigate(self, start_url: str, push: bool):
        GLib.idle_add(self._gtk_load_started)

        url = start_url
        for _ in range(6):
            try:
                response = await gemini_fetch(url)
            except GeminiError as e:
                GLib.idle_add(self._viewer.render_error, str(e))
                GLib.idle_add(self._gtk_load_done, url)
                return

            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or 1965

            tofu_status = await self._tofu_check(host, port, response.fingerprint)
            if tofu_status != "trusted":
                changed = tofu_status == "changed"
                trusted = await self._tofu_prompt_cb(host, port, response.fingerprint, changed)
                if not trusted:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Certificate for {host}:{port} was not trusted.",
                    )
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                await self._tofu.trust(host, port, response.fingerprint)

            cat = response.status // 10

            if cat == 3:
                url = urljoin(url, response.meta)
                continue

            if cat == 1:
                if not self._input_prompt_cb:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Server requests input: {response.meta}",
                    )
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                sensitive = (response.status == 11)
                user_input = await self._input_prompt_cb(
                    response.meta or "Enter input:", sensitive
                )
                if user_input is None:
                    # User cancelled — leave the viewer as-is
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                # Append the query to the URL and retry in the same loop
                parsed_url = urlparse(url)
                url = urlunparse(parsed_url._replace(
                    query=quote(user_input, safe="")
                ))
                continue

            if cat != 2:
                GLib.idle_add(
                    self._viewer.render_error,
                    f"{response.status} — {response.meta}",
                )
                GLib.idle_add(self._gtk_load_done, url)
                return

            # Success — decode and render
            mime, charset = self._parse_mime(response.meta)
            if mime in ("text/gemini", ""):
                text = response.body.decode(charset, errors="replace")
                title = self._extract_gemtext_title(text)
                if title:
                    self._page_title = title
                GLib.idle_add(lambda t=text, u=url: self._viewer.render_gemtext(t, u))
            elif mime.startswith("text/"):
                text = response.body.decode(charset, errors="replace")
                GLib.idle_add(lambda t=text: self._viewer.render_plain(t))
            else:
                # Non-text content — prompt for a save location and download.
                parsed_path = urlparse(url).path
                filename = parsed_path.rstrip("/").rsplit("/", 1)[-1] or "download"
                if self._save_as_cb:
                    save_path = await self._save_as_cb(filename)
                    if save_path:
                        try:
                            loop = async_utils.get_loop()
                            await loop.run_in_executor(
                                None,
                                lambda p=save_path, d=response.body: open(p, "wb").write(d),
                            )
                            GLib.idle_add(
                                self._viewer.render_info,
                                f"Saved to: {save_path}",
                            )
                        except OSError as exc:
                            GLib.idle_add(self._viewer.render_error, f"Save failed: {exc}")
                else:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Binary content ({mime}) — no save dialog available.",
                    )
                GLib.idle_add(self._gtk_load_done, url)
                return

            self.current_url = url
            if push:
                self._push_nav(url)

            GLib.idle_add(self._gtk_load_done, url)
            return

        GLib.idle_add(self._viewer.render_error, "Too many redirects.")
        GLib.idle_add(self._gtk_load_done, start_url)

    async def _tofu_check(self, host: str, port: int, fingerprint: str) -> str:
        if self._tofu is None:
            return "trusted"
        return await self._tofu.check(host, port, fingerprint)

    # ------------------------------------------------------------------
    # Gopher navigation (async thread)
    # ------------------------------------------------------------------

    async def _gopher_navigate(self, url: str, push: bool):
        GLib.idle_add(self._gtk_load_started)

        host, port, item_type, selector = gopher_parse_url(url)

        # Type 7 = search: prompt for the query before making any connection
        query = ""
        if item_type == "7":
            if not self._input_prompt_cb:
                GLib.idle_add(
                    self._viewer.render_error,
                    "Search input is not available.",
                )
                GLib.idle_add(self._gtk_load_done, url)
                return
            user_input = await self._input_prompt_cb(
                selector.strip("/") or "Search:", False
            )
            if user_input is None:
                GLib.idle_add(self._gtk_load_done, url)
                return
            query = user_input

        try:
            response = await gopher_fetch(url, query=query)
        except GopherError as e:
            GLib.idle_add(self._viewer.render_error, str(e))
            GLib.idle_add(self._gtk_load_done, url)
            return

        if item_type in ("1", "7"):
            items = parse_menu(response.body)
            GLib.idle_add(lambda i=items: self._viewer.render_gopher_menu(i))

        elif item_type == "0":
            text = response.body.decode("utf-8", errors="replace")
            GLib.idle_add(lambda t=text: self._viewer.render_plain(t))

        elif item_type in BINARY_TYPES:
            filename = (selector.rstrip("/").split("/")[-1]) or "download"
            if self._save_as_cb:
                save_path = await self._save_as_cb(filename)
                if save_path:
                    try:
                        loop = async_utils.get_loop()
                        await loop.run_in_executor(
                            None, lambda p=save_path, d=response.body: open(p, "wb").write(d)
                        )
                        GLib.idle_add(
                            self._viewer.render_info,
                            f"Saved to: {save_path}",
                        )
                    except OSError as e:
                        GLib.idle_add(self._viewer.render_error, f"Save failed: {e}")
            else:
                GLib.idle_add(self._viewer.render_error, "Download not available.")
            GLib.idle_add(self._gtk_load_done, url)
            return

        else:
            GLib.idle_add(
                self._viewer.render_error,
                f"Unsupported Gopher item type: {item_type!r}",
            )
            GLib.idle_add(self._gtk_load_done, url)
            return

        # Derive a human-readable title from the selector path component
        _last = selector.rstrip("/").rsplit("/", 1)[-1] if "/" in selector else selector
        self._page_title = (
            _last.replace("-", " ").replace("_", " ").title() or host
        )

        self.current_url = url
        if push:
            self._push_nav(url)

        GLib.idle_add(self._gtk_load_done, url)

    def _push_nav(self, url: str):
        self._nav_history = self._nav_history[: self._nav_pos + 1]
        self._nav_history.append(url)
        self._nav_pos = len(self._nav_history) - 1

    # ------------------------------------------------------------------
    # GTK callbacks (scheduled via idle_add — run on GTK thread)
    # ------------------------------------------------------------------

    def _gtk_load_started(self):
        if self._spinner is not None:
            self._spinner.set_visible(True)
            self._spinner.start()
        if self._on_favicon_changed:
            self._on_favicon_changed(self, None)   # reset to app icon during load
        if self._on_load_started:
            self._on_load_started(self)

    def _gtk_load_done(self, url: str):
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner.set_visible(False)
        if self._on_title_changed:
            self._on_title_changed(self, self.get_title())
        if self._on_uri_changed:
            self._on_uri_changed(self, url)
        if self._on_nav_state_changed:
            self._on_nav_state_changed(self)
        if self._on_load_finished:
            self._on_load_finished(self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_gemtext_title(text: str) -> str:
        """Return the first heading found in a Gemtext document, or ''."""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
            if s.startswith("## "):
                return s[3:].strip()
            if s.startswith("### "):
                return s[4:].strip()
        return ""

    @staticmethod
    def _parse_mime(meta: str) -> tuple[str, str]:
        if not meta:
            return ("text/gemini", "utf-8")
        parts = [p.strip() for p in meta.split(";")]
        mime = parts[0].lower()
        charset = "utf-8"
        for part in parts[1:]:
            if part.lower().startswith("charset="):
                charset = part[8:].strip()
        return (mime, charset)

    # ------------------------------------------------------------------
    # Find in page (GTK thread)
    # ------------------------------------------------------------------

    def find(self, text: str):
        """Start a find operation. Returns match count for text tabs, None for web."""
        if self.kind == TabKind.WEB:
            fc = self._web_view.get_find_controller()
            if text:
                flags = (WebKit.FindOptions.CASE_INSENSITIVE |
                         WebKit.FindOptions.WRAP_AROUND)
                fc.search(text, flags, 100)
            else:
                fc.search_finish()
            return None
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER):
            return self._viewer.find(text)
        return None

    def find_next(self):
        if self.kind == TabKind.WEB:
            self._web_view.get_find_controller().search_next()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER):
            self._viewer.find_next()

    def find_prev(self):
        if self.kind == TabKind.WEB:
            self._web_view.get_find_controller().search_previous()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER):
            self._viewer.find_prev()

    def find_clear(self):
        if self.kind == TabKind.WEB:
            try:
                self._web_view.get_find_controller().search_finish()
            except Exception:
                pass
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER):
            self._viewer.find_clear()

    # ------------------------------------------------------------------
    # Theming (GTK thread)
    # ------------------------------------------------------------------

    def apply_theme(self, theme: TextTheme) -> None:
        """Apply a TextTheme to this tab's text viewer (Gemini/Gopher only)."""
        self._text_theme = theme
        if hasattr(self, "_viewer"):
            self._viewer.apply_theme(theme)

    # ------------------------------------------------------------------
    # Print (GTK thread)
    # ------------------------------------------------------------------

    def print_page(self, parent: Gtk.Widget):
        """Show the print dialog. Only supported for web tabs."""
        if self.kind == TabKind.WEB:
            print_op = WebKit.PrintOperation.new(self._web_view)
            print_op.run_dialog(parent)

    # ------------------------------------------------------------------
    # WebKit signal handlers (GTK thread)
    # ------------------------------------------------------------------

    def _on_wk_title(self, _wv, _param):
        if self._on_title_changed:
            self._on_title_changed(self, self._web_view.get_title() or "New Tab")

    def _on_wk_uri(self, _wv, _param):
        uri = self._web_view.get_uri() or ""
        self.current_url = uri
        if self._on_uri_changed:
            self._on_uri_changed(self, uri)

    def _on_wk_load_changed(self, _wv, event):
        if event == WebKit.LoadEvent.STARTED:
            if self._on_load_started:
                self._on_load_started(self)
        elif event == WebKit.LoadEvent.FINISHED:
            if self._on_load_finished:
                self._on_load_finished(self)
            if self._on_nav_state_changed:
                self._on_nav_state_changed(self)

    def _on_wk_decide_policy(self, _wv, decision, decision_type):
        """Redirect new-window requests into a new tab; intercept gemini/gopher links."""
        if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            nav_action = decision.get_navigation_action()
            url = nav_action.get_request().get_uri()
            if self._open_url_cb and url:
                GLib.idle_add(lambda u=url: self._open_url_cb(u) and False)
            decision.ignore()
            return True
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            url = nav_action.get_request().get_uri() or ""
            if url.startswith(("gemini://", "gopher://")) and self._open_url_cb:
                GLib.idle_add(lambda u=url: self._open_url_cb(u) and False)
                decision.ignore()
                return True
        return False

    def _on_wk_favicon(self, _wv, _param):
        """Convert the WebKit favicon texture to a Gio.Icon and notify BrowserWindow."""
        if not self._on_favicon_changed:
            return
        texture = self._web_view.get_favicon()
        if not texture:
            return
        try:
            png_bytes = texture.save_to_png_bytes()
            icon = Gio.BytesIcon.new(png_bytes)
            self._on_favicon_changed(self, icon)
        except Exception:
            pass  # fall back to app icon

    def _on_wk_context_menu(self, _wv, menu, hit_test):
        """Customise the WebKit right-click context menu."""
        link_uri = hit_test.get_link_uri() if hit_test.context_is_link() else None

        if link_uri and self._open_url_cb:
            # Remove the stock "Open Link in New Window" item (misleading label —
            # our decide-policy handler already redirects it, but the text is wrong).
            for i in range(menu.get_n_items()):
                item = menu.get_item_at_position(i)
                if item and item.get_stock_action() == \
                        WebKit.ContextMenuAction.OPEN_LINK_IN_NEW_WINDOW:
                    menu.remove(item)
                    break

            # Add "Open Link in New Tab" backed by a GAction.
            action = Gio.SimpleAction.new("open-link-new-tab", None)
            captured = link_uri
            action.connect(
                "activate",
                lambda *_, u=captured: GLib.idle_add(lambda: self._open_url_cb(u) and False),
            )
            menu.prepend(
                WebKit.ContextMenuItem.new_from_gaction(
                    action, "Open Link in New Tab", None
                )
            )

        # Remove "Inspect Element" — no developer tools in this browser.
        for i in range(menu.get_n_items()):
            item = menu.get_item_at_position(i)
            if item and item.get_stock_action() == \
                    WebKit.ContextMenuAction.INSPECT_ELEMENT:
                menu.remove(item)
                break

        return False  # show the (modified) menu
