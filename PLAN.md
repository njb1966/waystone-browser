# PLAN.md — Multi-Protocol GUI Browser (Linux, WebKitGTK + Gemini + Gopher)

## 0. Goals / Non-goals

### Goals (v1)
- Single contained **GUI browser** for Linux
- Supports browsing:
  - `http://` and `https://` (general browsing)
  - `gemini://` (text/gemtext ethos)
  - `gopher://` (menus + text; download binary)
- Modern-ish UX:
  - Tabs
  - Back/Forward/Reload
  - Address bar with URL entry
  - Shared bookmarks manager (supports all schemes)
  - History (basic)
- Simple, safe handling of Gemini certificates (TOFU-style)
- Client certificate identity support for authenticated Gemini capsules
- Linux-first packaging story (dev run first; Flatpak later)

### Non-goals (v1)
- Building a new web engine (use WebKitGTK)
- Chromium-based components (QtWebEngine/CEF/Electron are out)
- Power-user web features (ad-blocking, extensions, sync, advanced privacy UI)
- "Full modern web compatibility" guarantees (it's "general browsing")

---

## 1. Technology Choices

### Runtime / Platform
- Linux only

### UI Toolkit
- GTK 4 + Libadwaita
  - `AdwApplicationWindow`, `AdwTabView`/`AdwTabBar` for tabs
  - `AdwHeaderBar` for window chrome
  - Dark mode + GNOME HIG styling for free
  - Flatpak-friendly (part of standard GNOME runtime)

### Web rendering (HTTP/HTTPS)
- WebKitGTK (WebKitWebView)

### Gemini/Gopher rendering
- Native text-first renderer widget:
  - `GtkTextView`-based viewer
  - Clickable links with protocol-differentiated icon prefixes
  - 7 built-in colour themes with live switching
  - Per-user font and text size overrides

### Language
- **Python + PyGObject + WebKitGTK bindings** (decided)
  - Fastest path to working prototype
  - PyGObject has solid GTK 4 + Libadwaita support

### Async / Concurrency
- **asyncio** (decided)
  - GTK main loop integrated via manual `asyncio` event loop wiring
  - Gemini and Gopher network I/O runs in async coroutines (non-blocking)
  - WebKit fetches its own content; no async needed there
  - Pattern: `asyncio.ensure_future()` / `await` for protocol clients;
    results dispatched back to GTK via `GLib.idle_add()`

### Data storage
- SQLite for bookmarks/history/cert store/identities
- Use `aiosqlite` for async-safe DB access
- Plain SQL layer (no ORM)

### Crypto
- `cryptography` library for X.509 cert generation and PKCS#12 import/export

---

## 2. High-Level Architecture

### 2.1 Core Concepts
- **BrowserWindow**: top-level window; owns tab strip + address bar + menus
- **Tab**: represents one navigation context
  - Has `TabKind = Web | Gemini | Gopher`
  - Owns a renderer widget (WebKitWebView or TextViewer)
  - Owns navigation history stack (back/forward)
- **NavigationController**: central URL dispatcher
  - Parses URL scheme
  - Routes to appropriate loader/renderer
- **BookmarkService**: CRUD for bookmarks (shared across schemes)
- **HistoryService**: append-only visits + clear
- **IdentityService**: client certificate CRUD, host mapping, .p12 import/export
- **TOFUStore**: server certificate fingerprint storage
- **GeminiClient**: TLS + TOFU + client cert + gemtext fetch
- **GopherClient**: TCP fetch; parses menus; downloads binary

### 2.2 Scheme Handling (Routing)
- `http/https` => WebKitWebView loads directly
- `gemini` => GeminiClient fetches => parse gemtext => render in TextViewer
- `gopher` => GopherClient fetches => parse menu/text/binary
  - menu/text => render in TextViewer
  - binary => prompt Save As…

### 2.3 Shared Bookmarks
Bookmarks are `title + url + optional folder`.
All schemes are stored together.

---

## 3. UI/UX Plan

### Main window layout
- Top: tab bar
- Below: header bar (back/forward/reload + address bar + bookmark star + menu button)
- Optional: bookmarks bar (toggle Ctrl+Shift+B)
- Content: current tab's renderer widget

### Tab behaviour
- New tab (Ctrl+T), Close tab (Ctrl+W), Duplicate tab (Ctrl+Shift+T)
- Cycle tabs (Ctrl+Tab / Ctrl+Shift+Tab)
- Close last tab opens a new tab automatically
- Session restore: last open URLs reopened on next launch

### Menus
- Bookmarks…
- History…
- Identities…
- Settings…
- About…

### Settings
- **General**: Homepage URL, JavaScript toggle, Bookmarks bar toggle, Color Scheme
- **Gemini**: Text Size, Colour Theme, Body Font, Trusted Certificates

---

## 4. Data Model (SQLite)

### 4.1 Bookmarks
```sql
CREATE TABLE bookmarks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL DEFAULT '',
    url        TEXT    NOT NULL UNIQUE,
    folder     TEXT             DEFAULT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
```

### 4.2 History
```sql
CREATE TABLE history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT    NOT NULL,
    title      TEXT             DEFAULT '',
    visited_at INTEGER NOT NULL DEFAULT (unixepoch())
);
```

### 4.3 Gemini TOFU store
```sql
CREATE TABLE gemini_certs (
    host          TEXT    NOT NULL,
    port          INTEGER NOT NULL DEFAULT 1965,
    fingerprint   TEXT    NOT NULL,
    first_seen_at INTEGER NOT NULL DEFAULT (unixepoch()),
    last_seen_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (host, port)
);
```

### 4.4 Client certificate identities ✅
```sql
CREATE TABLE identities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    cert_pem   TEXT    NOT NULL,
    key_pem    TEXT    NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE identity_hosts (
    host        TEXT    NOT NULL,
    port        INTEGER NOT NULL DEFAULT 1965,
    identity_id INTEGER NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    PRIMARY KEY (host, port)
);
```

---

## 5. Protocol Details

### 5.1 Gemini
- Request: connect host:port (default 1965), TLS handshake, send URL + CRLF
- Response codes handled:
  - `10` / `11` — input prompt (plain / sensitive)
  - `20` — success; render gemtext or download binary
  - `30` / `31` — redirect (up to 8 hops)
  - `40`–`59` — error displayed in viewer
  - `60` — client certificate required: prompt user to select/create identity
  - `61` — certificate not authorised
  - `62` — certificate not valid
- TOFU: prompt on first use; warn on fingerprint change
- Client certs: loaded from identity store; sent in TLS handshake

### 5.2 Gopher
- Parse gopher URL: default port 70, selector + item type
- Fetch: TCP, send selector + CRLF, read response
- Item types rendered:
  - `1` / `7` — directory menu / search
  - `0` — text file
  - `5`, `6`, `9`, `g`, `I`, `s` — binary download (Save As…)

---

## 6. Milestones

### ✅ Milestone 0 — Repo + Dev Environment
- Repository structure, Python venv, dependencies
- `AdwApplicationWindow` with `AdwHeaderBar` + tab strip

### ✅ Milestone 1 — Tabbed Shell + Address Bar
- Tab open/close/duplicate/cycle
- Address bar with URL normalisation and scheme dispatch
- WebKit tab loads HTTP/HTTPS URLs

### ✅ Milestone 2 — Bookmarks + History
- SQLite schema and services
- Bookmark add/remove, folder organisation, bookmarks bar
- History auto-record and searchable viewer

### ✅ Milestone 3 — Gemini Support
- GeminiClient: TLS, TOFU, redirect, input prompts
- Gemtext parser and TextViewer renderer
- Navigation history (back/forward) for Gemini tabs

### ✅ Milestone 4 — Gopher Support
- GopherClient: TCP fetch, menu parser, binary download
- Type-7 search with input prompt
- Gopher navigation in TextViewer

### ✅ Milestone 5 — Polishing + Theming
- Loading spinners, error pages, new-tab start page
- 7 built-in colour themes for Gemini/Gopher
- Text size control (Small / Normal / Large / X-Large)
- Body font selector (System Default + 5 named fonts)
- Noto Color Emoji fallback in all themes
- Link type icon prefix system (⇒ / ● with protocol colour)
- Settings UI (Adw.PreferencesDialog) for all appearance settings
- Keyboard shortcuts (Ctrl+L, Ctrl+T, Ctrl+W, Ctrl+F, Alt+Left/Right, …)

### ✅ Milestone 6 — Gemini Client Certificate Identities
- `IdentityService`: RSA-2048 self-signed cert generation, CRUD, host mapping
- PKCS#12 import/export for cross-browser portability
- `gemini_client.fetch()` passes client certs in TLS handshake
- Tab handles 60/61/62 response codes
- `_prompt_identity` dialog: pick existing identity or create inline on 60
- `IdentityDialog`: full management UI (create, import, export, delete)
- Menu → **Identities…** entry in BrowserWindow

---

## 7. Decisions Log

1. ~~Language choice: Python vs Rust~~ — **Python + PyGObject** ✅
2. ~~GTK 4 alone vs GTK 4 + Libadwaita~~ — **GTK 4 + Libadwaita** ✅
3. ~~Async strategy~~ — **asyncio + GLib.idle_add()** ✅
4. ~~Default JS policy for WebKit tabs~~ — **JS on by default, global toggle in Settings** ✅
5. ~~Non-text MIME handling for Gemini/Gopher~~ — **Download-only (Save As…)** ✅
6. ~~Gopher type 7 search~~ — **Input prompt dialog** ✅
7. ~~Gemini appearance differentiation~~ — **Icon prefix system (⇒/●) + colour themes** ✅
8. ~~Client cert portability~~ — **PKCS#12 (.p12) import/export** ✅

---

## 8. Risks & Mitigations

### Risk: WebKitGTK packaging/version mismatches
Mitigation: Target Flatpak runtime early; document distro dependencies clearly.

### Risk: Security edge cases in Gemini TOFU prompts
Mitigation: Default deny on cert change; show host, port, fingerprint.

### Risk: Client cert private key security
Mitigation: Keys stored in SQLite DB (user-owned file, mode 600 by default).
Future: consider encrypting keys at rest with a master passphrase.

### Risk: Scope creep
Mitigation: Track enhancements in roadmap below.

---

## 9. Roadmap (post-v1)

- **Load cancellation** — cancel in-flight Gemini/Gopher requests
- **History expiry** — auto-purge entries older than N days
- **Address bar autocomplete** — suggest from history as you type
- **Middle-click links** in Gemini/Gopher text viewer → new tab
- **Context menu** in text viewer — Copy, Select All
- **Status bar** — show link target on hover; network status
- **Encrypted identity keys** — optional master passphrase for the identity store
- **Flatpak release** — publish to Flathub

---

## 10. Definition of Done (v1)

- ✅ Install/run on Linux
- ✅ Tabs + address bar + back/forward/reload
- ✅ HTTP/HTTPS browsing via WebKitGTK
- ✅ Gemini browsing with TOFU + gemtext rendering
- ✅ Gemini client certificate identities (create, import, export, auto-send)
- ✅ Gopher browsing with menu/text + binary download
- ✅ Shared bookmarks + basic history UI
- ✅ Appearance customisation (themes, font, size)
- ✅ No Chromium-based dependencies
