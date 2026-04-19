"""TextViewer — GtkTextView-based renderer for Gemini and Gopher content."""

from typing import TYPE_CHECKING, Callable, Optional
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Pango, GLib

from .themes import TextTheme

from .gemtext import parse, LineType

if TYPE_CHECKING:
    from .gopher_client import GopherItem

# Icon and colour-tag for each link type.
# ⇒ = arrow (text / same-capsule)   ● = globe (directory / external)
_LINK_ICONS: dict[str, tuple[str, str]] = {
    "gemini_local": ("⇒", "link_icon_blue"),    # relative / same-capsule
    "gemini":       ("●", "link_icon_blue"),    # gemini:// cross-capsule
    "web":          ("●", "link_icon_orange"),  # http(s)://
    "gopher_dir":   ("●", "link_icon_green"),   # gopher directory / search
    "gopher_text":  ("⇒", "link_icon_green"),   # gopher text file
    "gopher_bin":   ("●", "link_icon_green"),   # binary / image / audio
}

# Short type hints appended to binary Gopher labels so the type is still visible.
_GOPHER_TYPE_HINT: dict[str, str] = {
    "5": "[zip]", "6": "[uue]", "9": "[bin]",
    "g": "[gif]", "I": "[img]", "s": "[snd]",
}

# Monotonically increasing counter for unique link tag names
_link_serial = 0


def _next_link_name() -> str:
    global _link_serial
    _link_serial += 1
    return f"__link_{_link_serial}"


class TextViewer(Gtk.ScrolledWindow):
    """
    Scrollable text renderer.  Wraps a GtkTextView with styled tags.

    navigate_cb(url: str) is called when the user clicks a link.
    """

    def __init__(self, navigate_cb: Callable[[str], None]):
        super().__init__()
        self._navigate_cb = navigate_cb
        self._link_tags: dict[str, str] = {}   # tag_name -> url
        self._find_matches: list[tuple[int, int]] = []
        self._find_current: int = -1

        self._build()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self):
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._buf = Gtk.TextBuffer()
        self._view = Gtk.TextView(buffer=self._buf)
        self._view.set_editable(False)
        self._view.set_cursor_visible(False)
        self._view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._view.set_left_margin(20)
        self._view.set_right_margin(20)
        self._view.set_top_margin(16)
        self._view.set_bottom_margin(16)
        self.set_child(self._view)

        # Per-instance CSS provider used by apply_theme()
        self._css_provider = Gtk.CssProvider()
        self._view.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._create_permanent_tags()

        # Click to follow links
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self._view.add_controller(click)

        # Cursor shape changes over links
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self._view.add_controller(motion)

    def _create_permanent_tags(self):
        t = self._buf.create_tag
        t("h1",             weight=Pango.Weight.BOLD,  scale=1.6)
        t("h2",             weight=Pango.Weight.BOLD,  scale=1.35)
        t("h3",             weight=Pango.Weight.BOLD,  scale=1.15)
        t("list",           left_margin=24)
        t("quote",          style=Pango.Style.ITALIC,  left_margin=24,
                            foreground="#888888")
        t("pre",            family="monospace",         foreground="#268bd2")
        t("link_base",       foreground="#3584e4",
                             underline=Pango.Underline.NONE)
        # Icon colour tags — updated by apply_theme(); shape set by _LINK_ICONS
        t("link_icon_blue",   foreground="#3584e4")
        t("link_icon_green",  foreground="#26a269")
        t("link_icon_orange", foreground="#e66100")
        t("text")
        # Error page tags
        t("error_heading",  foreground="#e01b24", weight=Pango.Weight.BOLD, scale=1.6)
        t("error_status",   foreground="#e01b24", weight=Pango.Weight.BOLD, scale=3.0)
        t("error_desc",     foreground="#888888", scale=1.1)
        # Gopher error line
        t("gopher_err",     foreground="#e01b24", style=Pango.Style.ITALIC)
        # Find-in-page highlights
        t("find_highlight", background="#f9f06b", foreground="#000000")
        t("find_current",   background="#e66100", foreground="#ffffff")

    # ------------------------------------------------------------------
    # Public render API
    # ------------------------------------------------------------------

    def render_gemtext(self, text: str, base_url: str = ""):
        self._clear()
        lines = parse(text)
        end = self._buf.get_end_iter()

        for line in lines:
            lt = line.type

            if lt == LineType.H1:
                self._insert(end, line.text + "\n", "h1")
            elif lt == LineType.H2:
                self._insert(end, line.text + "\n", "h2")
            elif lt == LineType.H3:
                self._insert(end, line.text + "\n", "h3")
            elif lt == LineType.LIST:
                self._insert(end, "• " + line.text + "\n", "list")
            elif lt == LineType.QUOTE:
                self._insert(end, line.text + "\n", "quote")
            elif lt == LineType.PREFORMAT:
                self._insert(end, line.text + "\n", "pre")
            elif lt == LineType.LINK:
                orig  = line.url or ""
                url   = self._resolve_url(orig, base_url)
                label = line.text or url
                self._insert_link(end, label + "\n", url,
                                  self._link_type(orig))
            else:
                # TEXT — empty lines become a blank line
                self._insert(end, line.text + "\n", "text")

        self._scroll_top()

    def render_plain(self, text: str):
        self._clear()
        end = self._buf.get_end_iter()
        self._buf.insert_with_tags_by_name(end, text, "text")
        self._scroll_top()

    def render_info(self, message: str):
        """Render a neutral informational message (e.g. download complete)."""
        self._clear()
        end = self._buf.get_end_iter()
        self._insert(end, "\n", "text")
        self._insert(end, message + "\n", "text")
        self._scroll_top()

    def render_error(self, message: str):
        self._clear()
        end = self._buf.get_end_iter()
        self._insert(end, "\n", "text")

        # If message looks like "STATUS — description" (Gemini/Gopher error responses),
        # render the numeric code large and the description beneath it.
        if " — " in message:
            parts = message.split(" — ", 1)
            if parts[0].strip().isdigit():
                self._insert(end, parts[0].strip() + "\n", "error_status")
                self._insert(end, parts[1].strip() + "\n", "error_desc")
                self._scroll_top()
                return

        self._insert(end, "Error\n", "error_heading")
        self._insert(end, message + "\n", "error_desc")
        self._scroll_top()

    def render_gopher_menu(self, items: "list[GopherItem]"):
        from .gopher_client import item_url
        self._clear()
        end = self._buf.get_end_iter()

        for item in items:
            if item.type == "i":
                self._insert(end, item.display + "\n", "text")
            elif item.type == "3":
                self._insert(end, "⚠ " + item.display + "\n", "gopher_err")
            else:
                url   = item_url(item)
                ltype = self._link_type(url, gopher_item_type=item.type)
                hint  = _GOPHER_TYPE_HINT.get(item.type, "")
                label = (item.display + f" {hint}") if hint else item.display
                if url:
                    self._insert_link(end, label + "\n", url, ltype)
                else:
                    self._insert(end, label + "\n", "text")

        self._scroll_top()

    # ------------------------------------------------------------------
    # Streaming gemtext API (progressive rendering)
    # ------------------------------------------------------------------

    def begin_gemtext_stream(self, base_url: str = "") -> None:
        """Clear the buffer and prepare for incremental gemtext rendering."""
        self._clear()
        self._stream_base_url = base_url
        self._stream_in_pre = False
        self._scroll_top()

    def feed_gemtext_lines(self, raw_lines: list[str]) -> None:
        """
        Render a batch of raw gemtext lines into the buffer.
        Maintains the preformat-toggle state across calls so chunked
        delivery works correctly.  Must be called on the GTK thread.
        """
        end = self._buf.get_end_iter()
        for raw in raw_lines:
            if raw.startswith("```"):
                self._stream_in_pre = not self._stream_in_pre
                continue
            if self._stream_in_pre:
                self._insert(end, raw + "\n", "pre")
                continue
            if raw.startswith("=>"):
                rest = raw[2:].strip()
                parts = rest.split(None, 1)
                orig = parts[0] if parts else ""
                label = parts[1].strip() if len(parts) > 1 else orig
                url = self._resolve_url(orig, self._stream_base_url)
                self._insert_link(end, label + "\n", url, self._link_type(orig))
            elif raw.startswith("###"):
                self._insert(end, raw[3:].strip() + "\n", "h3")
            elif raw.startswith("##"):
                self._insert(end, raw[2:].strip() + "\n", "h2")
            elif raw.startswith("#"):
                self._insert(end, raw[1:].strip() + "\n", "h1")
            elif raw.startswith("* "):
                self._insert(end, "• " + raw[2:].strip() + "\n", "list")
            elif raw.startswith(">"):
                self._insert(end, raw[1:].strip() + "\n", "quote")
            else:
                self._insert(end, raw + "\n", "text")

    def end_gemtext_stream(self) -> None:
        """Called when the stream is fully consumed. Hook for future use."""

    def apply_theme(self, theme: TextTheme) -> None:
        """Apply a colour theme to the viewer.  Safe to call at any time."""
        # Background, text colour, font size, and font family via per-widget CSS.
        css_props: list[str] = [f"font-size: {theme.font_size}pt;"]
        if theme.bg:
            css_props.append(f"background-color: {theme.bg};")
        if theme.fg:
            css_props.append(f"color: {theme.fg};")
        if theme.body_font:
            # Always include Noto Color Emoji for emoji fallback.
            generic = "serif" if "Serif" in theme.body_font else "sans-serif"
            css_props.append(
                f'font-family: "{theme.body_font}", "Noto Color Emoji", {generic};'
            )
        block = " ".join(css_props)
        css = f"textview {{ {block} }} textview > text {{ {block} }}"
        self._css_provider.load_from_data(css.encode())

        # Monospace font for preformat blocks.
        pre_tag = self._buf.get_tag_table().lookup("pre")
        if pre_tag:
            pre_tag.set_property("family", theme.mono_font)
            pre_tag.set_property("family-set", True)

        # Per-tag foreground colours.
        self._set_tag_fg("h1",              theme.h1_fg)
        self._set_tag_fg("h2",              theme.h2_fg)
        self._set_tag_fg("h3",              theme.h3_fg)
        self._set_tag_fg("text",            theme.fg)
        self._set_tag_fg("link_base",       theme.link_fg)
        self._set_tag_fg("link_icon_blue",  theme.link_fg)
        self._set_tag_fg("link_icon_green", theme.link_gopher_fg)
        self._set_tag_fg("link_icon_orange",theme.link_web_fg)
        self._set_tag_fg("quote",           theme.quote_fg)
        self._set_tag_fg("pre",             theme.pre_fg)

    @staticmethod
    def _link_type(url: str, *, gopher_item_type: str = "") -> str:
        """Return a key into _LINK_ICONS for this URL / Gopher item type."""
        if gopher_item_type:
            if gopher_item_type in ("1", "7"):
                return "gopher_dir"
            if gopher_item_type == "0":
                return "gopher_text"
            if gopher_item_type == "h" or url.startswith("http"):
                return "web"
            return "gopher_bin"
        if url.startswith("gemini://"):
            return "gemini"
        if url.startswith("gopher://"):
            return "gopher_dir"
        if url.startswith("http://") or url.startswith("https://"):
            return "web"
        return "gemini_local"

    def _set_tag_fg(self, name: str, colour: Optional[str]) -> None:
        tag = self._buf.get_tag_table().lookup(name)
        if tag is None:
            return
        if colour is not None:
            tag.set_property("foreground", colour)
            tag.set_property("foreground-set", True)
        else:
            tag.set_property("foreground-set", False)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clear(self):
        self._buf.set_text("")
        self._link_tags.clear()
        self._find_matches.clear()
        self._find_current = -1

    def _insert(self, iter_: Gtk.TextIter, text: str, *tag_names: str):
        self._buf.insert_with_tags_by_name(iter_, text, *tag_names)

    def _insert_link(self, iter_: Gtk.TextIter, label: str, url: str,
                     link_type: str = "gemini_local"):
        icon, icon_tag = _LINK_ICONS.get(link_type, ("⇒", "link_icon_blue"))

        # Per-link anonymous tag — carries only the URL for click detection.
        url_tag_name = _next_link_name()
        url_tag = self._buf.create_tag(url_tag_name)
        self._link_tags[url_tag_name] = url

        # Mark the start so the URL tag can cover icon + label together.
        start_mark = self._buf.create_mark(None, iter_, True)

        # Coloured protocol icon
        self._buf.insert_with_tags_by_name(iter_, icon + " ", icon_tag)
        # Link label in the standard link colour
        self._buf.insert_with_tags_by_name(iter_, label, "link_base")

        # Stretch the URL tag over the whole span so the icon is also clickable.
        start_iter = self._buf.get_iter_at_mark(start_mark)
        self._buf.apply_tag(url_tag, start_iter, iter_)
        self._buf.delete_mark(start_mark)

    def _scroll_top(self):
        self._buf.place_cursor(self._buf.get_start_iter())
        self._view.scroll_to_mark(self._buf.get_insert(), 0.0, True, 0.0, 0.0)

    # ------------------------------------------------------------------
    # Find in page
    # ------------------------------------------------------------------

    def find(self, text: str) -> int:
        """Highlight all occurrences of *text*, scroll to the first. Returns match count."""
        self._clear_find_highlights()
        self._find_matches.clear()
        self._find_current = -1

        if not text:
            return 0

        flags = (Gtk.TextSearchFlags.CASE_INSENSITIVE |
                 Gtk.TextSearchFlags.TEXT_ONLY)
        start = self._buf.get_start_iter()
        while True:
            result = start.forward_search(text, flags, None)
            if not result:
                break
            if isinstance(result, tuple):
                if len(result) == 3:
                    found, match_start, match_end = result
                    if not found:
                        break
                else:
                    match_start, match_end = result[0], result[1]
            else:
                break
            self._buf.apply_tag_by_name("find_highlight", match_start, match_end)
            self._find_matches.append(
                (match_start.get_offset(), match_end.get_offset())
            )
            start = match_end.copy()

        if self._find_matches:
            self._find_current = 0
            self._scroll_to_find_match(0)

        return len(self._find_matches)

    def find_next(self):
        if not self._find_matches:
            return
        self._find_current = (self._find_current + 1) % len(self._find_matches)
        self._scroll_to_find_match(self._find_current)

    def find_prev(self):
        if not self._find_matches:
            return
        self._find_current = (self._find_current - 1) % len(self._find_matches)
        self._scroll_to_find_match(self._find_current)

    def find_clear(self):
        self._clear_find_highlights()
        self._find_matches.clear()
        self._find_current = -1

    def _clear_find_highlights(self):
        start = self._buf.get_start_iter()
        end = self._buf.get_end_iter()
        self._buf.remove_tag_by_name("find_highlight", start, end)
        self._buf.remove_tag_by_name("find_current",   start, end)

    def _scroll_to_find_match(self, idx: int):
        start_offset, end_offset = self._find_matches[idx]
        start_iter = self._buf.get_iter_at_offset(start_offset)
        end_iter   = self._buf.get_iter_at_offset(end_offset)
        # Highlight current match in a distinct colour
        self._buf.remove_tag_by_name(
            "find_current", self._buf.get_start_iter(), self._buf.get_end_iter()
        )
        self._buf.apply_tag_by_name("find_current", start_iter, end_iter)
        self._buf.place_cursor(start_iter)
        self._view.scroll_to_mark(self._buf.get_insert(), 0.0, True, 0.0, 0.3)

    @staticmethod
    def _resolve_url(url: str, base: str) -> str:
        from urllib.parse import urljoin
        if not url:
            return base
        if "://" in url:
            return url
        return urljoin(base, url)

    def _iter_at_xy(self, x: float, y: float) -> Optional[Gtk.TextIter]:
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(x), int(y)
        )
        result = self._view.get_iter_at_location(bx, by)
        # PyGObject returns (bool, TextIter) in GTK4
        if isinstance(result, tuple):
            found, iter_ = result
            return iter_ if found else None
        return result  # fallback

    def _url_at_iter(self, iter_: Gtk.TextIter) -> Optional[str]:
        for tag in iter_.get_tags():
            name = tag.get_property("name")
            if name and name in self._link_tags:
                return self._link_tags[name]
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_click(self, gesture, n_press, x, y):
        iter_ = self._iter_at_xy(x, y)
        if iter_ is None:
            return
        url = self._url_at_iter(iter_)
        if url:
            self._navigate_cb(url)

    def _on_motion(self, controller, x, y):
        iter_ = self._iter_at_xy(x, y)
        is_link = iter_ is not None and self._url_at_iter(iter_) is not None
        cursor_name = "pointer" if is_link else "text"
        self._view.set_cursor(Gdk.Cursor.new_from_name(cursor_name, None))
