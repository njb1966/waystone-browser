# Waystone Browser

A multi-protocol GUI browser for Linux supporting HTTP/HTTPS, Gemini, and Gopher.

Built with Python, GTK 4, Libadwaita, and WebKitGTK.

---

## Supported protocols

| Protocol | Rendering | Notes |
|----------|-----------|-------|
| `http://` / `https://` | WebKitGTK | Full web engine; JS on by default |
| `gemini://` | Native text renderer | Gemtext, redirects, input prompts, TOFU, client certificates |
| `gopher://` | Native text renderer | Menus, text, search (type 7), binary download |

---

## Features

### Browsing
- **Tabbed browsing** — open/close/duplicate tabs; Ctrl+Tab to cycle
- **Session restore** — reopens your last tabs on next launch
- **New-tab page** — quick links to Gemcities, Geminispace, and Floodgap
- **Find in page** — Ctrl+F with live match highlighting; F3 / Shift+F3 to step through
- **Per-tab zoom** — Ctrl+= / Ctrl+- / Ctrl+0 (web tabs)
- **Print** — Ctrl+P opens the native print dialog (web tabs)
- **Open in new tab** — `target="_blank"` and gemini:// / gopher:// links from web pages

### Bookmarks & History
- **Bookmarks** — add with Ctrl+D; organised into folders; bookmarks bar for quick access
- **Bookmarks bar** — toggle with Ctrl+Shift+B; shows items in the "Bookmarks Bar" folder
- **History** — auto-recorded per navigation; full-text search; clear all

### Gemini
- **TOFU certificate trust** — trust-on-first-use with change detection and cert management
- **Input prompts** — handles status 10 (plain) and 11 (sensitive/password) requests
- **Client certificate identities** — create, import, and export identities as `.p12` files;
  identities are automatically sent to capsules that require them (status 60)
- **Binary downloads** — non-text Gemini responses prompt a Save As… dialog
- **Redirect handling** — follows up to 8 redirects automatically
- **Error display** — 6x cert errors (61/62) shown with clear messages

### Gemini/Gopher appearance
- **7 built-in colour themes** — System, Solarized Light, Solarized Dark, Nord, Dracula, Paper, Gruvbox Dark
- **Text size** — Small (12 pt) / Normal (14 pt) / Large (16 pt) / X-Large (19 pt)
- **Body font** — System Default, Noto Sans, Noto Serif, Cantarell, DejaVu Sans, DejaVu Serif
- **Noto Color Emoji** — emoji fallback in all themes
- **Link type icons** — ⇒ local capsule links, ● gemini/web/gopher links; colour-coded by protocol
- **Loading spinner** — visual indicator during Gemini/Gopher page loads

### Web (HTTP/HTTPS)
- **Full WebKitGTK engine** — JavaScript, cookies, modern CSS/HTML
- **Web favicons** — site icons appear in the tab strip
- **Context menu** — "Open Link in New Tab" for web tabs

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
    python3-aiosqlite \
    python3-cryptography
```

> **Note:** System packages are required and cannot be installed via pip alone.
> The recommended install paths are `./run.sh` for development or Flatpak for end users.

---

## Running (development)

```bash
git clone https://github.com/njb1966/waystone-browser
cd waystone-browser
./run.sh
```

`run.sh` runs `python3 -m waystone.main`.

---

## Installing (system-wide)

Because Waystone depends on `python3-gi` (PyGObject), which is a system package and cannot
be installed via pip, you must give pipx access to system site-packages:

```bash
sudo apt-get install \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0

pipx install . --system-site-packages
```

If pipx says the package is already installed, add `--force` to recreate the venv:

```bash
pipx install . --system-site-packages --force
```

Then run:

```bash
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
| Ctrl+Shift+T | Duplicate tab |
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

### Find in page
| Shortcut | Action |
|----------|--------|
| Ctrl+F | Open find bar |
| F3 / Ctrl+G | Next match |
| Shift+F3 / Ctrl+Shift+G | Previous match |

### Zoom & Print (web tabs)
| Shortcut | Action |
|----------|--------|
| Ctrl+= / Ctrl++ | Zoom in |
| Ctrl+- | Zoom out |
| Ctrl+0 | Reset zoom |
| Ctrl+P | Print |

---

## Bookmarks bar

The bookmarks bar sits below the address bar and shows bookmarks in the **"Bookmarks Bar"** folder.

1. Star a page (Ctrl+D) to save it as a regular bookmark.
2. Open **Bookmarks…** → click the folder icon on any row → pick **Bookmarks Bar**.
3. The link appears as a button in the toolbar immediately.

Bookmarks can also be organised into custom folders via the same Move menu.
Right-click a folder in the sidebar to **Rename** or **Delete** it.

---

## Settings

Open via the menu (⋮) → **Settings…**

### General
- **Homepage URL** — opened in every new tab
- **Enable JavaScript** — applies to new web tabs
- **Show Bookmarks Bar** — toggle the toolbar (also Ctrl+Shift+B)
- **Color Scheme** — System Default / Light / Dark (applied immediately)

### Gemini
- **Text Size** — Small / Normal / Large / X-Large
- **Colour Theme** — 7 built-in themes for Gemini and Gopher pages
- **Body Font** — override the font used in Gemini/Gopher text rendering
- **Trusted Certificates** — view and remove stored TOFU fingerprints

---

## Gemini Identities

Open via the menu (⋮) → **Identities…**

Waystone supports Gemini client certificate authentication used by capsules like
[Station](gemini://station.martinrue.com) and Gemini-accessible BBS systems.

### Creating an identity
1. Menu → **Identities…** → **New Identity…**
2. Enter a name (e.g. your username or handle).
3. A self-signed certificate is generated and stored locally.

### Importing from another browser
1. Export your identity from Lagrange, Kristall, or another Gemini browser as a `.p12` file.
2. Menu → **Identities…** → **Import .p12…**
3. Select the file and enter the password if one was set.

### Exporting to another browser
1. Menu → **Identities…** → click the **Export** button on any identity.
2. Optionally set a password to protect the file.
3. Save the `.p12` file and import it into the target browser.

### How it works
When a capsule returns **60 CLIENT CERTIFICATE REQUIRED**, Waystone prompts you to select
or create an identity. The choice is remembered — future visits to that capsule automatically
send the correct certificate with no additional prompts.

---

## Data storage

| Data | Location |
|------|----------|
| Bookmarks, history, TOFU certs, identities | `~/.local/share/waystone/waystone.db` |
| Settings | `~/.config/waystone/settings.json` |

---

## Project structure

```
waystone/
  main.py              — BrowserWindow, WaystoneApp entry point
  tab.py               — Tab (renderer widget + nav state + zoom)
  text_viewer.py       — GtkTextView renderer for Gemini/Gopher
  gemini_client.py     — Async Gemini protocol client (TLS + TOFU + client certs)
  gemtext.py           — Gemtext parser
  gopher_client.py     — Async Gopher protocol client (RFC 1436)
  navigation.py        — URL normalisation and scheme dispatch
  tofu_store.py        — TOFU certificate store
  identity_service.py  — Client certificate identity management
  bookmark_service.py  — Bookmark CRUD with folder support
  history_service.py   — History append + search
  themes.py            — Built-in colour themes (7 themes)
  bookmark_dialog.py   — Bookmarks manager (two-pane, folder sidebar)
  bookmarks_bar.py     — Bookmarks toolbar widget
  history_dialog.py    — History viewer
  identity_dialog.py   — Identity manager (create, import, export)
  settings_dialog.py   — Settings (Adw.PreferencesDialog)
  settings_service.py  — Settings persistence (JSON)
  db.py                — aiosqlite database wrapper + migrations
  async_utils.py       — Background asyncio thread + GLib bridge
  newtab.html          — New-tab start page
data/
  com.waystone.browser.desktop  — Desktop entry
  com.waystone.browser.svg      — Application icon
com.waystone.browser.yml        — Flatpak manifest
```

---

## License

MIT
