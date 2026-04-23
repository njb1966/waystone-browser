# Waystone Browser

A multi-protocol GUI browser for Linux supporting HTTP/HTTPS, Gemini, Gopher, Spartan, and Titan.

Built with Python, GTK 4, Libadwaita, and WebKitGTK.

---

## Supported protocols

| Protocol | Scheme | Rendering | Notes |
|----------|--------|-----------|-------|
| HTTP / HTTPS | `http://` `https://` | WebKitGTK | Full web engine; JS on by default |
| Gemini | `gemini://` | Native text renderer | Gemtext, redirects, input prompts, TOFU, client certificates, streaming render |
| Gopher | `gopher://` | Native text renderer | Menus, text, search (type 7), binary download/open |
| Spartan | `spartan://` | Native text renderer | Gemtext, redirects, data-input links (`=`) |
| Titan | `titan://` | Upload dialog | Write content to Gemini capsules; triggered by `titan://` links in Gemini pages |

---

## Features

### Browsing
- **Tabbed browsing** — open/close/duplicate tabs; Ctrl+Tab to cycle
- **Session restore** — reopens your last tabs on next launch
- **New-tab page** — quick links to Gemcities, Geminispace, and Floodgap
- **Find in page** — Ctrl+F with live match highlighting; F3 / Shift+F3 to step through
- **Per-tab zoom** — Ctrl+= / Ctrl+- / Ctrl+0 (web tabs)
- **Print** — Ctrl+P opens the native print dialog (web tabs)
- **Cross-protocol links** — clicking a `gemini://` link from a web page (or vice-versa) opens it in the correct tab type automatically
- **Open in new tab** — middle-click or right-click any link in Gemini / Gopher / Spartan pages

### Bookmarks & History
- **Bookmarks** — add with Ctrl+D; right-click the star to quick-add directly to the Bookmarks Bar
- **Bookmark folders** — organise into arbitrarily nested folders; right-click a folder to rename, move, or delete it
- **Move Under…** — drag a folder under any other folder or to top level via context menu
- **Bookmarks bar** — toggle with Ctrl+Shift+B; items directly in "Bookmarks Bar" show as flat buttons; sub-folders show as dropdown menus
- **Import / Export** — import Netscape HTML bookmark files (with full nested folder hierarchy) or `.gmi` files; export to Netscape HTML; import shows live progress
- **History** — auto-recorded per navigation; full-text search; clear all

### Gemini
- **Streaming render** — page content appears progressively as it arrives (no waiting for the full response)
- **SSLContext caching** — TLS session resumption across requests to the same capsule (faster reloads and relay hops)
- **TOFU certificate trust** — trust-on-first-use with change detection and cert management
- **Input prompts** — handles status 10 (plain) and 11 (sensitive/password) requests
- **Client certificate identities** — create, import, and export identities as `.p12` files; identities are automatically sent to capsules that require them (status 60)
- **Binary / media content** — non-text responses prompt to Open with default app or Save As…
- **Redirect handling** — follows up to 8 redirects automatically
- **Titan upload** — click a `titan://` link to open an upload dialog with multiline text editor and optional auth token

### Spartan
- **Full navigation** — browse `spartan://` pages with gemtext rendering, plain text, and binary download
- **Data-input links** — `=` link lines (Spartan's form equivalent) render with a ✏ icon; clicking prompts for text and re-requests with it as the request body
- **Redirect handling** — follows up to 8 code-3 redirects
- **Cross-protocol links** — Spartan pages can link to Gemini, Gopher, or web URLs

### Gopher
- **Full RFC 1436 support** — menus, text files, type-7 search, binary types
- **Media / binary content** — binary responses prompt to Open with default app or Save As…
- **Cross-protocol links** — `h`-type links open in the appropriate tab (Gemini, web, or Gopher)

### Gemini/Gopher/Spartan appearance
- **7 built-in colour themes** — System, Solarized Light, Solarized Dark, Nord, Dracula, Paper, Gruvbox Dark
- **Text size** — Small (12 pt) / Normal (14 pt) / Large (16 pt) / X-Large (19 pt)
- **Body font** — System Default, Noto Sans, Noto Serif, Cantarell, DejaVu Sans, DejaVu Serif
- **Noto Color Emoji** — emoji fallback in all themes
- **Link type icons** — ⇒ local / same-capsule links, ● cross-capsule / external links, ✏ Spartan data-input links; colour-coded by protocol
- **Loading spinner** — visual indicator during page loads

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

> **XFCE users:** the Applications Menu won't pick up new entries until the panel is restarted.
> Run `xfce4-panel --restart` after the above commands, or log out and back in.

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

The bookmarks bar sits below the address bar.

- **Flat buttons** — bookmarks saved directly in the **"Bookmarks Bar"** folder appear as buttons
- **Dropdown menus** — sub-folders of "Bookmarks Bar" appear as dropdown `▾` menu buttons
- Right-click any flat button to **Edit** or **Remove** it from the bar
- Right-click the ★ bookmark star to **Add to Bookmarks Bar** instantly

To add bookmarks to the bar:
1. Star a page (Ctrl+D) to save it as a regular bookmark, then open **Bookmarks…** and move it.
2. Or right-click the ★ star while on any page to add directly to the bar.

---

## Bookmarks manager

Open via Ctrl+B or the menu.

- **Sidebar** — click a folder to filter the bookmark list; "All Bookmarks" and "Unfiled" are always pinned at the top; "Bookmarks Bar" is pinned below them
- **Folders** — click the folder icon on any bookmark row to move it; right-click a folder in the sidebar to rename, move under another folder, or delete it
- **Bulk delete** — tick folder checkboxes in the sidebar then click "Delete Selected"
- **Import** — accepts Netscape HTML (`.html`/`.htm`) and Gemini link files (`.gmi`); nested folder structure is preserved from HTML imports; a live progress indicator shows during large imports
- **Export** — saves all bookmarks as a Netscape HTML file compatible with other browsers

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
- **Colour Theme** — 7 built-in themes for Gemini / Gopher / Spartan pages
- **Body Font** — override the font used in text rendering
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

## Spartan browsing

[Spartan](gemini://spartan.mozz.us) is a simpler, TLS-optional alternative to Gemini.

- Type any `spartan://` URL in the address bar to open a Spartan tab
- Pages render identically to Gemini (gemtext or plain text)
- **Data-input links** — lines beginning with `=` in Spartan gemtext are interactive form-like links (rendered with a ✏ icon); clicking one prompts for text, which is submitted as the request body
- Redirects, cross-protocol links, and binary downloads all work the same as in Gemini tabs

## Titan uploading

[Titan](gemini://transjovian.org/titan) is an upload protocol that allows writing content to Gemini capsules (e.g. wiki pages).

- When a Gemini page contains a `titan://` link, clicking it opens an **Upload via Titan** dialog
- Enter the content to upload in the multiline text editor; enter an auth token if the server requires one
- After upload the server's response is rendered in the current tab
- TOFU certificate trust applies to Titan connections the same as Gemini

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
  tab.py               — Tab (renderer widget + navigation + zoom)
  text_viewer.py       — GtkTextView renderer for Gemini / Gopher / Spartan
  gemini_client.py     — Async Gemini client (TLS, TOFU, streaming, client certs)
  spartan_client.py    — Async Spartan client (plain TCP, port 300)
  titan_client.py      — Async Titan upload client (TLS, returns GeminiStream)
  gopher_client.py     — Async Gopher client (RFC 1436)
  gemtext.py           — Gemtext parser
  navigation.py        — URL normalisation and scheme dispatch
  tofu_store.py        — TOFU certificate store
  identity_service.py  — Client certificate identity management
  bookmark_service.py  — Bookmark CRUD with folder support
  history_service.py   — History append + search
  themes.py            — Built-in colour themes (7 themes)
  bookmark_dialog.py   — Bookmarks manager (two-pane, folder sidebar)
  bookmarks_bar.py     — Bookmarks toolbar widget (buttons + folder dropdowns)
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
