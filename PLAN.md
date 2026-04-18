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
- Linux-first packaging story (dev run first; Flatpak later)

### Non-goals (v1)
- Building a new web engine (use WebKitGTK)
- Chromium-based components (QtWebEngine/CEF/Electron are out)
- Power-user web features (ad-blocking, extensions, sync, advanced privacy UI)
- “Full modern web compatibility” guarantees (it’s “general browsing”)

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
  - `GtkTextView`-based viewer (initial)
  - Clickable links + minimal styling
  - No HTML/JS rendering for Gemini/Gopher

### Language
- **Python + PyGObject + WebKitGTK bindings** (decided)
  - Fastest path to working prototype
  - PyGObject has solid GTK 4 + Libadwaita support

### Async / Concurrency
- **asyncio** (decided)
  - GTK main loop integrated via `gbulb` or manual `asyncio` event loop wiring
  - Gemini and Gopher network I/O runs in async coroutines (non-blocking)
  - WebKit fetches its own content; no async needed there
  - Pattern: `asyncio.ensure_future()` / `await` for protocol clients;
    results dispatched back to GTK via `GLib.idle_add()`

### Data storage
- SQLite for bookmarks/history/cert store
- Use `aiosqlite` for async-safe DB access
- Plain SQL layer (no ORM)

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
- **DownloadService**: saves content to disk (Gemini/Gopher v1; Web downloads later/optional)
- **GeminiClient**: TLS + TOFU + gemtext fetch
- **GopherClient**: TCP fetch; parses menus; downloads binary

### 2.2 Scheme Handling (Routing)
- `http/https` => WebKitWebView loads directly
- `gemini` => GeminiClient fetches => parse gemtext => render in TextViewer
- `gopher` => GopherClient fetches => parse menu/text/binary
  - menu/text => render in TextViewer
  - binary => prompt Save As… => DownloadService

### 2.3 Shared Bookmarks
Bookmarks are `title + url (+ optional folder/tag later)`.
All schemes are stored together.

---

## 3. UI/UX Plan (v1)

### Main window layout
- Top: tab bar
- Below: address bar + nav buttons
  - Back, Forward, Reload/Stop
  - Address entry
  - Bookmark star (add/remove)
- Main content area: current tab’s renderer widget

### Tab behavior
- New tab button
- Close tab
- Duplicate tab (nice-to-have, can defer)

### Minimal menus
- Bookmarks…
- History…
- Settings…
- About…

### Settings (minimal)
- Homepage URL (optional)
- Gemini TOFU policy:
  - Prompt on first use (default)
  - Prompt on change (default)
  - View/remove stored Gemini cert fingerprints
- (Optional v1) Toggle JavaScript for WebKit (global)

---

## 4. Data Model (SQLite)

### 4.1 Bookmarks
- `bookmarks`:
  - `id` (int)
  - `title` (text)
  - `url` (text, unique)
  - `created_at` (int)
  - `updated_at` (int)
  - `folder` (text, nullable) — optional in v1, can add later

### 4.2 History
- `history`:
  - `id`
  - `url`
  - `title` (nullable)
  - `visited_at`

Basic history UI can be “most recent first” + search-by-substring.

### 4.3 Gemini TOFU store
- `gemini_certs`:
  - `host` (text) — may include `host:port`
  - `port` (int)
  - `fingerprint` (text) — SHA-256 of leaf cert (or pubkey)
  - `first_seen_at`
  - `last_seen_at`

---

## 5. Protocol Details (Implementation Notes)

### 5.1 Gemini
- Implement Gemini request:
  - Connect to host:port (default 1965)
  - TLS handshake
  - Send URL line + CRLF
  - Read status/meta line
  - Handle:
    - 20 success (text/gemini or other MIME)
    - 30/31 redirects
    - 40+ errors (display nicely)
- TOFU:
  - On first connection: show fingerprint, ask trust, store
  - On fingerprint change: warn + require confirmation

Rendering:
- Gemtext parsing:
  - headings (`#`, `##`, `###`)
  - links (`=> URL [label]`)
  - list items (`*`)
  - blockquotes (`>`)
  - preformatted blocks (``` … ```)
- Convert to styled segments in TextViewer:
  - headings bold/larger (simple tags)
  - links clickable

### 5.2 Gopher
- Parse gopher URL:
  - default port 70
  - selector + optional type
- Fetch:
  - open TCP
  - send selector + CRLF
  - read response
- Render:
  - directory/menu (type `1`) as list of links
  - text file (type `0`) as text
  - binary types: prompt Save As…
- Minimal MIME inference based on gopher item type; keep it simple in v1.

---

## 6. Milestones

### Milestone 0 — Repo + Dev Environment (1–2 days)
- Create repository structure
- ~~Choose language~~ — Python (decided)
- Set up Python venv + dependencies:
  - `pygobject`, `libadwaita`, `webkit2gtk-6.0` (or `webkitgtk-6.0`)
  - `gbulb` (asyncio/GLib loop integration)
  - `aiosqlite`
- Add `run.sh` / `pyproject.toml`
- Add build/run instructions to README

Deliverable:
- `AdwApplicationWindow` launches with placeholder `AdwHeaderBar` + tab strip

---

### Milestone 1 — Tabbed Shell + Address Bar (1–2 weeks)
- Implement tab system
- Address bar:
  - URL parsing/normalization
  - scheme dispatch (http/https/gemini/gopher)
- Back/forward/reload mechanics (initial for web tabs; stub for gemini/gopher until Milestone 3)

Deliverable:
- Multiple tabs open/close
- WebKit tab loads `https://example.org`

---

### Milestone 2 — Bookmarks + History (1–2 weeks)
- SQLite setup and services
- Bookmark add/remove for current page
- Bookmark manager dialog/list
- History append on navigation + history viewer dialog

Deliverable:
- Bookmark `gemini://…`, `gopher://…`, `https://…` all together
- Open bookmark in new/current tab

---

### Milestone 3 — Gemini Support (2–4 weeks)
- GeminiClient with TLS
- TOFU store + prompts
- Gemtext parser
- TextViewer renderer with clickable links
- Gemini navigation history integration
- Redirect handling (basic)

Deliverable:
- Browse Gemini capsules in-app in tabs
- Trust prompts work; cert changes detected

---

### Milestone 4 — Gopher Support (2–4 weeks)
- GopherClient + parsers
- Render menus + text
- Handle binary downloads (Save As…)

Deliverable:
- Browse Gopher menus/text in-app
- Download binary items to disk

---

### Milestone 5 — Polishing + Packaging (2–4 weeks)
- UX improvements:
  - loading indicators for Gemini/Gopher
  - better error pages
  - keyboard shortcuts (Ctrl+L, Ctrl+T, Ctrl+W)
- Settings UI (minimal)
- Packaging:
  - Flatpak manifest (recommended for Linux)
  - Desktop file + icon
- Basic documentation

Deliverable:
- Installable artifact (Flatpak) + release checklist

---

## 7. Open Questions / Decisions (Track Early)

1. ~~Language choice: Python vs Rust~~ — **Python + PyGObject** (decided)
2. ~~GTK 4 alone vs GTK 4 + Libadwaita~~ — **GTK 4 + Libadwaita** (decided)
3. ~~Async strategy~~ — **asyncio + gbulb/GLib.idle_add()** (decided)
4. ~~Default JS policy for WebKit tabs~~ — **JS on by default, global toggle in Settings** (decided)
5. ~~Non-text MIME handling for Gemini/Gopher~~ — **Download-only (Save As…); no external open in v1** (decided)
6. Gopher item type 7 (search): needs query input prompt — how to surface in UI?

---

## 8. Risks & Mitigations

### Risk: WebKitGTK packaging/version mismatches
Mitigation:
- Target Flatpak runtime early (Milestone 5), or document distro dependencies clearly.

### Risk: Security edge cases in Gemini TOFU prompts
Mitigation:
- Keep the TOFU UI clear and conservative:
  - default deny on cert change unless user approves
  - show host, port, fingerprint, first/last seen

### Risk: Scope creep (turning into a full browser)
Mitigation:
- Keep v1 “general browsing” + core features only.
- Track enhancements in a separate `ROADMAP.md`.

---

## 9. Minimal v1 Definition of Done
- Install/run on Linux
- Tabs + address bar + back/forward/reload
- HTTP/HTTPS browsing via WebKitGTK
- Gemini browsing with TOFU + gemtext rendering
- Gopher browsing with menu/text + binary download
- Shared bookmarks + basic history UI
- No Chromium-based dependencies
