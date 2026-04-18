# Waystone Browser

A multi-protocol GUI browser for Linux supporting HTTP/HTTPS, Gemini, and Gopher.

Built with Python, GTK 4, Libadwaita, and WebKitGTK.

---

## Supported protocols

| Protocol | Rendering | Notes |
|----------|-----------|-------|
| `http://` / `https://` | WebKitGTK | Full web engine; JS on by default |
| `gemini://` | Native text renderer | Gemtext, redirects, input prompts, TOFU |
| `gopher://` | Native text renderer | Menus, text, search (type 7), binary download |

---

## Features

- **Tabbed browsing** — open/close tabs, Ctrl+Tab to cycle
- **Bookmarks** — add with Ctrl+D; organised into folders; bookmarks bar for quick access
- **History** — auto-recorded per navigation; searchable
- **Gemini TOFU** — certificate trust-on-first-use with change detection
- **Gemini input prompts** — handles status 10/11 (sensitive) requests
- **Gopher search** — type-7 search dialogs
- **Loading indicators** — spinner overlay for Gemini/Gopher tabs
- **Dark mode** — System Default / Light / Dark via Settings
- **Zoom** — Ctrl+= / Ctrl+- / Ctrl+0 (web tabs)
- **Open in new tab** — `target="_blank"` and middle-click links open in a new tab

---

## Dependencies

### System packages (Debian/Ubuntu)

```bash
sudo apt-get install \
    python3 \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    gir1.2-webkit-6.0 \
    python3-aiosqlite
```

---

## Running (development)

```bash
git clone https://github.com/njb166/waystone-browser
cd waystone-browser
./run.sh
```

`run.sh` runs `python3 -m waystone.main`.

---

## Installing (system-wide)

```bash
pip install --user .
waystone
```

To register the desktop entry and icon:

```bash
install -Dm644 data/com.waystone.browser.desktop \
    ~/.local/share/applications/com.waystone.browser.desktop

install -Dm644 data/com.waystone.browser.svg \
    ~/.local/share/icons/hicolor/scalable/apps/com.waystone.browser.svg

update-desktop-database ~/.local/share/applications/
```

---

## Flatpak

A manifest is provided at `com.waystone.browser.yml`.
Requires `flatpak-builder` and the GNOME Platform 47 runtime.

```bash
flatpak install flathub org.gnome.Platform//47 org.gnome.Sdk//47

flatpak-builder --user --install --force-clean \
    _build com.waystone.browser.yml
```

---

## Keyboard shortcuts

### Navigation
| Shortcut | Action |
|----------|--------|
| Alt+Left | Back |
| Alt+Right | Forward |
| F5 / Ctrl+R | Reload |
| Ctrl+Shift+R | Hard reload (bypass cache) |

### Tabs
| Shortcut | Action |
|----------|--------|
| Ctrl+T | New tab |
| Ctrl+W | Close tab |
| Ctrl+Tab | Next tab |
| Ctrl+Shift+Tab | Previous tab |

### Address bar & bookmarks
| Shortcut | Action |
|----------|--------|
| Ctrl+L | Focus address bar |
| Ctrl+D | Bookmark / unbookmark current page |
| Ctrl+B | Open Bookmarks manager |
| Ctrl+H | Open History |
| Ctrl+Shift+B | Toggle bookmarks bar |

### Zoom (web tabs)
| Shortcut | Action |
|----------|--------|
| Ctrl+= / Ctrl++ | Zoom in |
| Ctrl+- | Zoom out |
| Ctrl+0 | Reset zoom |

---

## Bookmarks bar

The bookmarks bar sits below the address bar and shows bookmarks that have been
explicitly moved into the **"Bookmarks Bar"** folder.

1. Star a page (Ctrl+D) to save it as a regular bookmark.
2. Open **Bookmarks…** → click the folder icon on any row → pick **Bookmarks Bar**.
3. The link appears as a button in the toolbar immediately.

Bookmarks can also be organised into custom folders via the same Move menu.
Right-click a folder in the sidebar to **Rename** or **Delete** it.

---

## Settings

Open via the menu (⋮) → **Settings…**

**General**
- **Homepage URL** — opened in every new tab
- **Enable JavaScript** — applies to new web tabs
- **Show Bookmarks Bar** — toggle the toolbar (also Ctrl+Shift+B)
- **Color Scheme** — System Default / Light / Dark (applied immediately)

**Gemini**
- View and remove stored TOFU certificate fingerprints

Settings are saved to `~/.config/waystone/settings.json`.

---

## Data storage

| Data | Location |
|------|----------|
| Bookmarks, history, TOFU certs | `~/.local/share/waystone/waystone.db` |
| Settings | `~/.config/waystone/settings.json` |

---

## Project structure

```
waystone/
  main.py              — BrowserWindow, WaystoneApp entry point
  tab.py               — Tab (renderer widget + nav state + zoom)
  text_viewer.py       — GtkTextView renderer for Gemini/Gopher
  gemini_client.py     — Async Gemini protocol client (TLS + TOFU)
  gemtext.py           — Gemtext parser
  gopher_client.py     — Async Gopher protocol client (RFC 1436)
  navigation.py        — URL normalisation and scheme dispatch
  tofu_store.py        — TOFU certificate store
  bookmark_service.py  — Bookmark CRUD with folder support
  history_service.py   — History append + search
  bookmark_dialog.py   — Bookmarks manager (two-pane, folder sidebar)
  bookmarks_bar.py     — Bookmarks toolbar widget
  history_dialog.py    — History viewer
  settings_dialog.py   — Settings (Adw.PreferencesDialog)
  settings_service.py  — Settings persistence (JSON)
  db.py                — aiosqlite database wrapper + migrations
  async_utils.py       — Background asyncio thread + GLib bridge
data/
  com.waystone.browser.desktop  — Desktop entry
  com.waystone.browser.svg      — Application icon
com.waystone.browser.yml        — Flatpak manifest
```

---

## License

MIT
