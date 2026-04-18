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
        t("h1",        weight=Pango.Weight.BOLD,  scale=1.6)
        t("h2",        weight=Pango.Weight.BOLD,  scale=1.35)
        t("h3",        weight=Pango.Weight.BOLD,  scale=1.15)
        t("list",      left_margin=24)
        t("quote",     style=Pango.Style.ITALIC,  left_margin=24,
                       foreground="#888888")
        t("pre",       family="monospace",         foreground="#268bd2")
        t("link_base", foreground="#3584e4",
                       underline=Pango.Underline.SINGLE)
        t("text")

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
        if not self._buf.get_tag_table().lookup("error_msg"):
            self._buf.create_tag("error_msg", foreground="#e01b24",
                                 weight=Pango.Weight.BOLD, scale=1.1)
        self._buf.insert_with_tags_by_name(end, "Error\n", "error_msg")
        self._buf.insert_with_tags_by_name(end, message + "\n", "text")
        self._scroll_top()

    def render_gopher_menu(self, items: "list[GopherItem]"):
        from .gopher_client import item_url, BINARY_TYPES
        self._clear()
        end = self._buf.get_end_iter()

        if not self._buf.get_tag_table().lookup("gopher_err"):
            self._buf.create_tag("gopher_err", foreground="#e01b24",
                                 style=Pango.Style.ITALIC)

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
