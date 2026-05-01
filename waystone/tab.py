"""Tab: owns a renderer widget and exposes a uniform navigation interface."""

import os as _os
import subprocess
import tempfile
from enum import Enum, auto
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse, urljoin, quote

# File extensions recognised as audio or video for the "Open with default app" prompt.
_MEDIA_EXTENSIONS: frozenset[str] = frozenset({
    ".mp3", ".ogg", ".wav", ".flac", ".m4a", ".aac", ".opus", ".wma",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".ogv", ".m4v", ".flv",
})

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit, GLib, Gio

from . import async_utils
from .gemini_client import open_request, GeminiError
from .gopher_client import (
    fetch as gopher_fetch, parse_menu, parse_url as gopher_parse_url,
    GopherError, BINARY_TYPES,
)
from .spartan_client import fetch as spartan_fetch, SpartanError
from .titan_client import upload as titan_upload
from .tofu_store import TOFUStore
from .identity_service import IdentityService
from .text_viewer import TextViewer
from .themes import TextTheme, THEMES, DEFAULT_THEME_ID


class TabKind(Enum):
    WEB = auto()
    GEMINI = auto()
    GOPHER = auto()
    SPARTAN = auto()
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
        identity_service: Optional[IdentityService] = None,
        identity_prompt_cb: Optional[Callable] = None,
        input_prompt_cb: Optional[Callable] = None,
        save_as_cb: Optional[Callable] = None,
        media_action_cb: Optional[Callable] = None,
        titan_upload_cb: Optional[Callable] = None,
        open_url_cb: Optional[Callable] = None,
        fullscreen_enter_cb: Optional[Callable] = None,
        fullscreen_leave_cb: Optional[Callable] = None,
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
        self._identity_service = identity_service
        self._identity_prompt_cb = identity_prompt_cb
        self._input_prompt_cb = input_prompt_cb
        self._save_as_cb = save_as_cb
        self._media_action_cb = media_action_cb
        self._titan_upload_cb = titan_upload_cb
        self._open_url_cb = open_url_cb
        self._fullscreen_enter_cb = fullscreen_enter_cb
        self._fullscreen_leave_cb = fullscreen_leave_cb
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
        elif kind == TabKind.SPARTAN:
            self.widget = self._build_spartan_view(url)
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
        elif self.kind == TabKind.SPARTAN:
            async_utils.run(self._spartan_navigate(url, push=True))
        # TabKind.BLANK: no-op — BrowserWindow converts to the right kind via _open_new_tab

    def teardown(self):
        """Stop media and release resources before this tab is removed from the UI."""
        if self.kind == TabKind.WEB:
            self._web_view.load_uri("about:blank")

    def go_back(self):
        if self.kind == TabKind.WEB:
            if self._web_view.can_go_back():
                self._web_view.go_back()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN) and self._nav_pos > 0:
            self._nav_pos -= 1
            url = self._nav_history[self._nav_pos]
            fn = (self._gemini_navigate if self.kind == TabKind.GEMINI
                  else self._gopher_navigate if self.kind == TabKind.GOPHER
                  else self._spartan_navigate)
            async_utils.run(fn(url, push=False))

    def go_forward(self):
        if self.kind == TabKind.WEB:
            if self._web_view.can_go_forward():
                self._web_view.go_forward()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN) and \
                self._nav_pos < len(self._nav_history) - 1:
            self._nav_pos += 1
            url = self._nav_history[self._nav_pos]
            fn = (self._gemini_navigate if self.kind == TabKind.GEMINI
                  else self._gopher_navigate if self.kind == TabKind.GOPHER
                  else self._spartan_navigate)
            async_utils.run(fn(url, push=False))

    def reload(self):
        if self.kind == TabKind.WEB:
            self._web_view.reload()
        elif self.kind == TabKind.GEMINI and self.current_url:
            async_utils.run(self._gemini_navigate(self.current_url, push=False))
        elif self.kind == TabKind.GOPHER and self.current_url:
            async_utils.run(self._gopher_navigate(self.current_url, push=False))
        elif self.kind == TabKind.SPARTAN and self.current_url:
            async_utils.run(self._spartan_navigate(self.current_url, push=False))

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

    def go_root(self):
        """Navigate to the root document of the current site (scheme://host/)."""
        url = self.get_uri()
        if not url:
            return
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            root = f"{parsed.scheme}://{parsed.netloc}/"
            if root != url:
                self.navigate(root)

    def go_to_nav_index(self, idx: int):
        """Jump to an arbitrary position in the non-web navigation history."""
        if self.kind not in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN):
            return
        if not (0 <= idx < len(self._nav_history)):
            return
        self._nav_pos = idx
        url = self._nav_history[idx]
        fn = (self._gemini_navigate if self.kind == TabKind.GEMINI
              else self._gopher_navigate if self.kind == TabKind.GOPHER
              else self._spartan_navigate)
        async_utils.run(fn(url, push=False))

    @property
    def nav_history(self) -> list[str]:
        return list(self._nav_history)

    @property
    def nav_pos(self) -> int:
        return self._nav_pos

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
        self._web_view.connect("enter-fullscreen", self._on_wk_enter_fullscreen)
        self._web_view.connect("leave-fullscreen", self._on_wk_leave_fullscreen)
        if url:
            self._web_view.load_uri(url)
        return self._web_view

    def _build_gemini_view(self, url: str) -> Gtk.Widget:
        self._viewer = TextViewer(
            navigate_cb=self._on_gemini_link_clicked,
            new_tab_cb=self._open_url_cb,
        )
        self._viewer.apply_theme(self._text_theme)
        overlay = self._make_spinner_overlay()
        if url:
            async_utils.run(self._gemini_navigate(url, push=True))
        return overlay

    def _build_gopher_view(self, url: str) -> Gtk.Widget:
        self._viewer = TextViewer(
            navigate_cb=self._on_gopher_link_clicked,
            new_tab_cb=self._open_url_cb,
        )
        self._viewer.apply_theme(self._text_theme)
        overlay = self._make_spinner_overlay()
        if url:
            async_utils.run(self._gopher_navigate(url, push=True))
        return overlay

    def _build_spartan_view(self, url: str) -> Gtk.Widget:
        self._viewer = TextViewer(
            navigate_cb=self._on_spartan_link_clicked,
            new_tab_cb=self._open_url_cb,
        )
        self._viewer.apply_theme(self._text_theme)
        overlay = self._make_spinner_overlay()
        if url:
            async_utils.run(self._spartan_navigate(url, push=True))
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
        if url.startswith("titan://"):
            async_utils.run(self._titan_upload(url))
        elif url.startswith(("http://", "https://", "gopher://", "spartan://")) and self._open_url_cb:
            self._open_url_cb(url)
        else:
            async_utils.run(self._gemini_navigate(url, push=True))

    def _on_gopher_link_clicked(self, url: str):
        if url.startswith(("http://", "https://", "gemini://", "spartan://")) and self._open_url_cb:
            self._open_url_cb(url)
        else:
            async_utils.run(self._gopher_navigate(url, push=True))

    def _on_spartan_link_clicked(self, url: str):
        if url.startswith("spartan-data:"):
            real_url = url[len("spartan-data:"):]
            async_utils.run(self._spartan_data_submit(real_url))
        elif url.startswith(("http://", "https://", "gemini://", "gopher://", "titan://")) and self._open_url_cb:
            self._open_url_cb(url)
        else:
            async_utils.run(self._spartan_navigate(url, push=True))

    # ------------------------------------------------------------------
    # Gemini navigation (runs on async thread)
    # ------------------------------------------------------------------

    async def _gemini_navigate(self, start_url: str, push: bool):
        GLib.idle_add(self._gtk_load_started)

        url = start_url

        # Pre-load any stored client certificate for the initial host.
        cert_pem, key_pem = await self._identity_for_url(url)

        for _ in range(8):  # redirect budget (+ 1 cert retry per hop)
            try:
                stream = await open_request(url, cert_pem=cert_pem, key_pem=key_pem)
            except GeminiError as e:
                GLib.idle_add(self._viewer.render_error, str(e))
                GLib.idle_add(self._gtk_load_done, url)
                return

            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or 1965

            tofu_status = await self._tofu_check(host, port, stream.header.fingerprint)
            if tofu_status != "trusted":
                changed = tofu_status == "changed"
                trusted = await self._tofu_prompt_cb(
                    host, port, stream.header.fingerprint, changed
                )
                if not trusted:
                    await stream.aclose()
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Certificate for {host}:{port} was not trusted.",
                    )
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                await self._tofu.trust(host, port, stream.header.fingerprint)

            status = stream.header.status
            meta   = stream.header.meta
            cat    = status // 10

            # 3x — redirect: close stream, loop with new URL
            if cat == 3:
                await stream.aclose()
                url = urljoin(url, meta)
                cert_pem, key_pem = await self._identity_for_url(url)
                continue

            # 6x — client certificate required / rejected
            if cat == 6:
                await stream.aclose()
                if status == 60:
                    if not self._identity_prompt_cb:
                        GLib.idle_add(
                            self._viewer.render_error,
                            "This capsule requires a client certificate.\n\n"
                            "Manage identities via Menu → Identities.",
                        )
                        GLib.idle_add(self._gtk_load_done, url)
                        return
                    result = await self._identity_prompt_cb(host, port, meta or "")
                    if result is None:
                        GLib.idle_add(self._gtk_load_done, url)
                        return
                    cert_pem, key_pem = result
                    continue  # retry with the chosen certificate
                elif status == 61:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Certificate not authorised by {host}.\n\n{meta}",
                    )
                elif status == 62:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Certificate not valid for {host}.\n\n{meta}",
                    )
                else:
                    GLib.idle_add(self._viewer.render_error, f"{status} — {meta}")
                GLib.idle_add(self._gtk_load_done, url)
                return

            # 1x — input required
            if cat == 1:
                await stream.aclose()
                if not self._input_prompt_cb:
                    GLib.idle_add(
                        self._viewer.render_error,
                        f"Server requests input: {meta}",
                    )
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                sensitive = (status == 11)
                user_input = await self._input_prompt_cb(meta or "Enter input:", sensitive)
                if user_input is None:
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                parsed_url = urlparse(url)
                url = urlunparse(parsed_url._replace(query=quote(user_input, safe="")))
                continue

            if cat != 2:
                await stream.aclose()
                GLib.idle_add(self._viewer.render_error, f"{status} — {meta}")
                GLib.idle_add(self._gtk_load_done, url)
                return

            # 2x — success: stream or buffer the body
            mime, charset = self._parse_mime(meta)

            if mime in ("text/gemini", ""):
                # Progressive rendering: push lines to the viewer as chunks arrive.
                GLib.idle_add(self._viewer.begin_gemtext_stream, url)
                incomplete = ""
                page_title = ""
                try:
                    async for chunk in stream.chunks():
                        incomplete += chunk.decode(charset, errors="replace")
                        last_nl = incomplete.rfind("\n")
                        if last_nl == -1:
                            continue
                        lines = incomplete[:last_nl].split("\n")
                        incomplete = incomplete[last_nl + 1:]
                        if not page_title:
                            for raw in lines:
                                t = self._extract_gemtext_title(raw)
                                if t:
                                    page_title = t
                                    break
                        GLib.idle_add(self._viewer.feed_gemtext_lines, lines)
                except GeminiError as e:
                    await stream.aclose()
                    GLib.idle_add(self._viewer.render_error, str(e))
                    GLib.idle_add(self._gtk_load_done, url)
                    return
                finally:
                    await stream.aclose()
                # flush any remainder that had no trailing newline
                if incomplete:
                    if not page_title:
                        page_title = self._extract_gemtext_title(incomplete)
                    GLib.idle_add(self._viewer.feed_gemtext_lines, [incomplete])
                GLib.idle_add(self._viewer.end_gemtext_stream)
                if page_title:
                    self._page_title = page_title

            elif mime.startswith("text/"):
                body = await stream.read_all()
                text = body.decode(charset, errors="replace")
                GLib.idle_add(self._viewer.render_plain, text)

            elif self._is_media_mime(mime):
                # Audio/video: prompt first, then stream to temp file.
                # Reading the full body with read_all() would hang indefinitely
                # on a live stream (e.g. a CGI radio proxy), so we prompt before
                # consuming any body data and stream chunks into a temp file.
                parsed_path = urlparse(url).path
                filename = parsed_path.rstrip("/").rsplit("/", 1)[-1] or "download"
                choice = None
                if self._media_action_cb:
                    choice = await self._media_action_cb(filename, mime)
                if choice == "open":
                    await self._stream_media_to_temp(stream, filename)
                elif choice == "save" and self._save_as_cb:
                    save_path = await self._save_as_cb(filename)
                    if save_path:
                        await self._stream_to_file(stream, save_path, url)
                    else:
                        await stream.aclose()
                else:
                    await stream.aclose()
                GLib.idle_add(self._gtk_load_done, url)
                return

            else:
                # Non-text, non-media binary: buffer fully then offer save.
                body = await stream.read_all()
                parsed_path = urlparse(url).path
                filename = parsed_path.rstrip("/").rsplit("/", 1)[-1] or "download"
                await self._handle_binary(body, filename, mime)
                GLib.idle_add(self._gtk_load_done, url)
                return

            self.current_url = url
            if push:
                self._push_nav(url)
            GLib.idle_add(self._gtk_load_done, url)
            return

        GLib.idle_add(self._viewer.render_error, "Too many redirects.")
        GLib.idle_add(self._gtk_load_done, start_url)

    async def _identity_for_url(
        self, url: str
    ) -> tuple[Optional[bytes], Optional[bytes]]:
        """Return (cert_pem, key_pem) bytes for the host in *url*, or (None, None)."""
        if not self._identity_service:
            return None, None
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or 1965
        identity = await self._identity_service.get_for_host(host, port)
        if identity:
            return identity["cert_pem"].encode(), identity["key_pem"].encode()
        return None, None

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
            # Gopher type "s" is explicitly audio; other types probed by extension.
            mime = "audio/ogg" if item_type == "s" else ""
            await self._handle_binary(response.body, filename, mime)
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

    # ------------------------------------------------------------------
    # Spartan navigation (async thread)
    # ------------------------------------------------------------------

    async def _spartan_navigate(self, url: str, push: bool = True, body: bytes = b"") -> None:
        GLib.idle_add(self._gtk_load_started)

        for _ in range(8):
            try:
                status, meta, resp_body = await spartan_fetch(url, body=body)
            except SpartanError as e:
                GLib.idle_add(self._viewer.render_error, str(e))
                GLib.idle_add(self._gtk_load_done, url)
                return

            if status == 3:
                body = b""  # body is not re-sent after a redirect
                url = urljoin(url, meta)
                continue

            if status != 2:
                GLib.idle_add(self._viewer.render_error, f"{status} — {meta}")
                GLib.idle_add(self._gtk_load_done, url)
                return

            mime, charset = self._parse_mime(meta or "text/gemini")
            text = resp_body.decode(charset, errors="replace")

            if mime in ("text/gemini", ""):
                processed = self._preprocess_spartan_gemtext(text, url)
                GLib.idle_add(self._viewer.begin_gemtext_stream, url)
                GLib.idle_add(self._viewer.feed_gemtext_lines, processed)
                GLib.idle_add(self._viewer.end_gemtext_stream)
                self._page_title = self._extract_gemtext_title(text)
            elif mime.startswith("text/"):
                GLib.idle_add(self._viewer.render_plain, text)
            else:
                parsed_path = urlparse(url).path
                filename = parsed_path.rstrip("/").rsplit("/", 1)[-1] or "download"
                await self._handle_binary(resp_body, filename, mime)
                GLib.idle_add(self._gtk_load_done, url)
                return

            self.current_url = url
            if push:
                self._push_nav(url)
            GLib.idle_add(self._gtk_load_done, url)
            return

        GLib.idle_add(self._viewer.render_error, "Too many redirects.")
        GLib.idle_add(self._gtk_load_done, url)

    async def _spartan_data_submit(self, url: str) -> None:
        """Prompt for text input and re-request *url* with it as the request body."""
        if not self._input_prompt_cb:
            GLib.idle_add(
                self._viewer.render_error,
                "Input is required but not available.",
            )
            return
        user_input = await self._input_prompt_cb("Enter content to submit:", False)
        if user_input is None:
            return
        await self._spartan_navigate(url, push=True, body=user_input.encode("utf-8"))

    @staticmethod
    def _preprocess_spartan_gemtext(text: str, base_url: str) -> list[str]:
        """Convert Spartan '= path label' data links to '=> spartan-data:<url> label'."""
        lines = []
        for raw in text.splitlines():
            if raw.startswith("= "):
                rest = raw[2:].strip()
                parts = rest.split(None, 1)
                if parts:
                    path = parts[0]
                    label = parts[1].strip() if len(parts) > 1 else path
                    resolved = urljoin(base_url, path)
                    lines.append(f"=> spartan-data:{resolved} {label}")
                else:
                    lines.append(raw)
            else:
                lines.append(raw)
        return lines

    # ------------------------------------------------------------------
    # Titan upload (async thread)
    # ------------------------------------------------------------------

    async def _titan_upload(self, titan_url: str) -> None:
        """Prompt for content and upload it to a titan:// URL."""
        if not self._titan_upload_cb:
            GLib.idle_add(
                self._viewer.render_error,
                "Titan upload is not configured.",
            )
            return

        result = await self._titan_upload_cb(titan_url)
        if result is None:
            return

        body_text, token, mime = result
        body = body_text.encode("utf-8")

        GLib.idle_add(self._gtk_load_started)

        try:
            stream = await titan_upload(titan_url, body=body, token=token, mime=mime)
        except GeminiError as e:
            GLib.idle_add(self._viewer.render_error, f"Upload failed: {e}")
            GLib.idle_add(self._gtk_load_done, titan_url)
            return

        # TOFU check for the upload target's cert
        parsed = urlparse(titan_url.split(";")[0])
        host = parsed.hostname or ""
        port = parsed.port or 1965
        tofu_status = await self._tofu_check(host, port, stream.header.fingerprint)
        if tofu_status != "trusted":
            changed = tofu_status == "changed"
            trusted = await self._tofu_prompt_cb(host, port, stream.header.fingerprint, changed)
            if not trusted:
                await stream.aclose()
                GLib.idle_add(
                    self._viewer.render_error,
                    f"Certificate for {host}:{port} was not trusted.",
                )
                GLib.idle_add(self._gtk_load_done, titan_url)
                return
            await self._tofu.trust(host, port, stream.header.fingerprint)

        status = stream.header.status
        meta = stream.header.meta
        cat = status // 10

        if cat == 3:
            await stream.aclose()
            redirect_url = urljoin(titan_url, meta)
            GLib.idle_add(self._gtk_load_done, titan_url)
            # Follow the redirect as a Gemini request
            async_utils.run(self._gemini_navigate(redirect_url, push=True))
            return

        if cat == 2:
            body_bytes = await stream.read_all()
            mime, charset = self._parse_mime(meta)
            text = body_bytes.decode(charset, errors="replace")
            gemini_base = "gemini://" + titan_url.split("://", 1)[-1].split(";")[0]
            if mime in ("text/gemini", ""):
                GLib.idle_add(self._viewer.render_gemtext, text, gemini_base)
            else:
                GLib.idle_add(self._viewer.render_plain, text)
        else:
            await stream.aclose()
            GLib.idle_add(self._viewer.render_error, f"{status} — {meta}")

        GLib.idle_add(self._gtk_load_done, titan_url)

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
    # Binary / media content handling (async thread)
    # ------------------------------------------------------------------

    async def _handle_binary(self, body: bytes, filename: str, mime: str) -> None:
        """Prompt to open media with the default app, or fall back to Save As."""
        is_media = self._is_media_mime(mime) or self._is_media_filename(filename)
        if is_media and self._media_action_cb:
            choice = await self._media_action_cb(filename, mime)
            if choice is None:
                return  # cancelled
            if choice == "open":
                await self._open_with_default_app(body, filename)
                return
            # choice == "save" falls through to Save As below

        if self._save_as_cb:
            save_path = await self._save_as_cb(filename)
            if save_path:
                try:
                    loop = async_utils.get_loop()
                    await loop.run_in_executor(
                        None, lambda p=save_path, d=body: open(p, "wb").write(d)
                    )
                    GLib.idle_add(self._viewer.render_info, f"Saved to: {save_path}")
                except OSError as exc:
                    GLib.idle_add(self._viewer.render_error, f"Save failed: {exc}")
        else:
            GLib.idle_add(
                self._viewer.render_error,
                f"Binary content ({mime or 'unknown'}) — no save dialog available.",
            )

    async def _open_with_default_app(self, body: bytes, filename: str) -> None:
        suffix = _os.path.splitext(filename)[1] or ""
        loop = async_utils.get_loop()
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="waystone_media_")
            def _write_and_launch():
                try:
                    _os.write(fd, body)
                finally:
                    _os.close(fd)
                subprocess.Popen(["xdg-open", tmp_path])
            await loop.run_in_executor(None, _write_and_launch)
            GLib.idle_add(self._viewer.render_info, f"Opening: {filename}")
        except OSError as exc:
            GLib.idle_add(self._viewer.render_error, f"Could not open media: {exc}")

    async def _stream_media_to_temp(self, stream, filename: str) -> None:
        """Write a Gemini media stream chunk-by-chunk to a temp file, then xdg-open it.

        Unlike _open_with_default_app this never calls read_all(), so it works for
        live audio/video streams that never send EOF.  The player opens as soon as the
        file is created and can read ahead while we continue writing.
        """
        suffix = _os.path.splitext(filename)[1] or ""
        loop = async_utils.get_loop()
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="waystone_media_")
            _os.close(fd)
            launched = False
            with open(tmp_path, "wb") as fh:
                async for chunk in stream.chunks():
                    await loop.run_in_executor(None, fh.write, chunk)
                    if not launched:
                        subprocess.Popen(["xdg-open", tmp_path])
                        launched = True
            if not launched:
                subprocess.Popen(["xdg-open", tmp_path])
            GLib.idle_add(self._viewer.render_info, f"Opening: {filename}")
        except GeminiError as e:
            GLib.idle_add(self._viewer.render_error, str(e))
        except OSError as exc:
            GLib.idle_add(self._viewer.render_error, f"Could not open media: {exc}")
        finally:
            await stream.aclose()

    async def _stream_to_file(self, stream, save_path: str, url: str) -> None:
        """Write a Gemini stream to a user-specified file path."""
        loop = async_utils.get_loop()
        try:
            with open(save_path, "wb") as fh:
                async for chunk in stream.chunks():
                    await loop.run_in_executor(None, fh.write, chunk)
            GLib.idle_add(self._viewer.render_info, f"Saved to: {save_path}")
        except GeminiError as e:
            GLib.idle_add(self._viewer.render_error, str(e))
        except OSError as exc:
            GLib.idle_add(self._viewer.render_error, f"Save failed: {exc}")
        finally:
            await stream.aclose()

    @staticmethod
    def _is_media_mime(mime: str) -> bool:
        return mime.startswith(("audio/", "video/"))

    @staticmethod
    def _is_media_filename(filename: str) -> bool:
        return _os.path.splitext(filename)[1].lower() in _MEDIA_EXTENSIONS

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
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN):
            return self._viewer.find(text)
        return None

    def find_next(self):
        if self.kind == TabKind.WEB:
            self._web_view.get_find_controller().search_next()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN):
            self._viewer.find_next()

    def find_prev(self):
        if self.kind == TabKind.WEB:
            self._web_view.get_find_controller().search_previous()
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN):
            self._viewer.find_prev()

    def find_clear(self):
        if self.kind == TabKind.WEB:
            try:
                self._web_view.get_find_controller().search_finish()
            except Exception:
                pass
        elif self.kind in (TabKind.GEMINI, TabKind.GOPHER, TabKind.SPARTAN):
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
            # Middle-click: open in new tab rather than navigating current frame.
            if nav_action.get_mouse_button() == 2 and self._open_url_cb and url:
                GLib.idle_add(lambda u=url: self._open_url_cb(u) and False)
                decision.ignore()
                return True
        return False

    def _on_wk_enter_fullscreen(self, _wv):
        if self._fullscreen_enter_cb:
            self._fullscreen_enter_cb()
        return True  # we handle it

    def _on_wk_leave_fullscreen(self, _wv):
        if self._fullscreen_leave_cb:
            self._fullscreen_leave_cb()
        return True  # we handle it

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
