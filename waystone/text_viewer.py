"""TextViewer — GtkTextView-based renderer for Gemini and Gopher content."""

from typing import TYPE_CHECKING, Callable, Optional
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Pango, GLib

from .gemtext import parse, LineType

if TYPE_CHECKING:
    from .gopher_client import GopherItem

# Gopher item-type display prefixes
_GOPHER_PREFIX: dict[str, str] = {
    "0": "[TXT] ",
    "1": "[DIR] ",
    "5": "[ZIP] ",
    "6": "[UUE] ",
    "7": "[ ? ] ",
    "9": "[BIN] ",
    "g": "[GIF] ",
    "h": "[WEB] ",
    "I": "[IMG] ",
    "s": "[SND] ",
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
        t("link_base",      foreground="#3584e4",
                            underline=Pango.Underline.SINGLE)
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
                url = self._resolve_url(line.url or "", base_url)
                label = line.text or url
                self._insert_link(end, "⇒ " + label + "\n", url)
            else:
                # TEXT — empty lines become a blank line
                self._insert(end, line.text + "\n", "text")

        self._scroll_top()

    def render_plain(self, text: str):
        self._clear()
        end = self._buf.get_end_iter()
        self._buf.insert_with_tags_by_name(end, text, "text")
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
        from .gopher_client import item_url, BINARY_TYPES
        self._clear()
        end = self._buf.get_end_iter()

        for item in items:
            if item.type == "i":
                # Informational line — plain text, may be empty
                self._insert(end, item.display + "\n", "text")
            elif item.type == "3":
                # Error line
                self._insert(end, "⚠ " + item.display + "\n", "gopher_err")
            else:
                url = item_url(item)
                prefix = _GOPHER_PREFIX.get(item.type, "[???] ")
                label = prefix + item.display
                if url:
                    self._insert_link(end, label + "\n", url)
                else:
                    self._insert(end, label + "\n", "text")

        self._scroll_top()

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

    def _insert_link(self, iter_: Gtk.TextIter, label: str, url: str):
        tag_name = _next_link_name()
        tag = self._buf.create_tag(tag_name,
                                   foreground="#3584e4",
                                   underline=Pango.Underline.SINGLE)
        self._link_tags[tag_name] = url
        # Apply both the shared link_base style and the unique per-link tag
        start_mark = self._buf.create_mark(None, iter_, True)
        self._buf.insert_with_tags_by_name(iter_, label, "link_base")
        start_iter = self._buf.get_iter_at_mark(start_mark)
        self._buf.apply_tag(tag, start_iter, iter_)
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
