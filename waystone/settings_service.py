"""Persistent settings backed by ~/.config/waystone/settings.json."""

import json
from pathlib import Path

_CONFIG_DIR  = Path.home() / ".config" / "waystone"
_CONFIG_FILE = _CONFIG_DIR / "settings.json"

_DEFAULTS: dict = {
    "homepage":            "",
    "js_enabled":          True,
    "show_bookmarks_bar":  True,
    "color_scheme":        "default",   # "default" | "light" | "dark"
    "session_urls":        [],
}


class SettingsService:
    def __init__(self) -> None:
        self._data: dict = dict(_DEFAULTS)
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if _CONFIG_FILE.exists():
            try:
                with open(_CONFIG_FILE) as f:
                    self._data.update(json.load(f))
            except Exception:
                pass

    def save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def homepage(self) -> str:
        return self._data.get("homepage", "")

    @homepage.setter
    def homepage(self, value: str) -> None:
        self._data["homepage"] = value
        self.save()

    @property
    def js_enabled(self) -> bool:
        return bool(self._data.get("js_enabled", True))

    @js_enabled.setter
    def js_enabled(self, value: bool) -> None:
        self._data["js_enabled"] = bool(value)
        self.save()

    @property
    def show_bookmarks_bar(self) -> bool:
        return bool(self._data.get("show_bookmarks_bar", True))

    @show_bookmarks_bar.setter
    def show_bookmarks_bar(self, value: bool) -> None:
        self._data["show_bookmarks_bar"] = bool(value)
        self.save()

    @property
    def color_scheme(self) -> str:
        return self._data.get("color_scheme", "default")

    @color_scheme.setter
    def color_scheme(self, value: str) -> None:
        self._data["color_scheme"] = value
        self.save()

    @property
    def session_urls(self) -> list:
        return list(self._data.get("session_urls", []))

    @session_urls.setter
    def session_urls(self, value: list) -> None:
        self._data["session_urls"] = list(value)
        self.save()
