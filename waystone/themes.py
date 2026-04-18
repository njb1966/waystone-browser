"""Built-in colour themes for the Gemini / Gopher text renderer."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TextTheme:
    """
    Colour settings applied to TextViewer.
    All colour fields accept a CSS colour string or None.
    None means "inherit from the system / GTK theme".
    """
    name: str
    bg:       Optional[str] = None   # viewer background
    fg:       Optional[str] = None   # body text
    h1_fg:    Optional[str] = None
    h2_fg:    Optional[str] = None
    h3_fg:    Optional[str] = None
    link_fg:  Optional[str] = "#3584e4"
    quote_fg: Optional[str] = "#888888"
    pre_fg:   Optional[str] = "#268bd2"


THEMES: dict[str, TextTheme] = {
    "system": TextTheme(
        name="System",
        bg=None, fg=None,
        h1_fg=None, h2_fg=None, h3_fg=None,
        link_fg="#3584e4", quote_fg="#888888", pre_fg="#268bd2",
    ),
    "solarized_light": TextTheme(
        name="Solarized Light",
        bg="#fdf6e3", fg="#657b83",
        h1_fg="#dc322f", h2_fg="#cb4b16", h3_fg="#b58900",
        link_fg="#268bd2", quote_fg="#93a1a1", pre_fg="#859900",
    ),
    "solarized_dark": TextTheme(
        name="Solarized Dark",
        bg="#002b36", fg="#839496",
        h1_fg="#dc322f", h2_fg="#cb4b16", h3_fg="#b58900",
        link_fg="#268bd2", quote_fg="#586e75", pre_fg="#859900",
    ),
    "nord": TextTheme(
        name="Nord",
        bg="#2e3440", fg="#d8dee9",
        h1_fg="#88c0d0", h2_fg="#81a1c1", h3_fg="#5e81ac",
        link_fg="#81a1c1", quote_fg="#616e88", pre_fg="#a3be8c",
    ),
    "dracula": TextTheme(
        name="Dracula",
        bg="#282a36", fg="#f8f8f2",
        h1_fg="#ff79c6", h2_fg="#bd93f9", h3_fg="#6272a4",
        link_fg="#8be9fd", quote_fg="#6272a4", pre_fg="#50fa7b",
    ),
    "paper": TextTheme(
        name="Paper",
        bg="#f5efe6", fg="#2c2416",
        h1_fg="#8b3a0f", h2_fg="#6b4226", h3_fg="#4a3728",
        link_fg="#1a5276", quote_fg="#7d6c55", pre_fg="#4a6741",
    ),
    "gruvbox": TextTheme(
        name="Gruvbox Dark",
        bg="#282828", fg="#ebdbb2",
        h1_fg="#fb4934", h2_fg="#fabd2f", h3_fg="#b8bb26",
        link_fg="#83a598", quote_fg="#928374", pre_fg="#8ec07c",
    ),
}

THEME_IDS   = list(THEMES.keys())
THEME_NAMES = [t.name for t in THEMES.values()]
DEFAULT_THEME_ID = "system"
