#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/njb1966/waystone-browser"
RAW_URL="https://raw.githubusercontent.com/njb1966/waystone-browser/main"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}Warning:${NC} $*" >&2; }
error() { echo -e "${RED}Error:${NC} $*" >&2; exit 1; }

command -v apt-get &>/dev/null || error "This installer requires apt (Debian, Ubuntu, Mint, etc.)."

info "Installing system dependencies..."
sudo apt-get install -y \
    git \
    python3 \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    gir1.2-webkit-6.0

# Ensure pipx
if ! command -v pipx &>/dev/null; then
    if apt-cache show pipx &>/dev/null 2>&1; then
        sudo apt-get install -y pipx
    else
        python3 -m pip install --user pipx
    fi
fi

export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_INSTALL=false
if [[ -f "$SCRIPT_DIR/data/com.waystone.browser.desktop" ]]; then
    LOCAL_INSTALL=true
fi

if [[ "$LOCAL_INSTALL" == true ]]; then
    info "Installing Waystone from local source..."
    pipx install "$SCRIPT_DIR" --system-site-packages --force
else
    info "Installing Waystone..."
    pipx install "git+${REPO_URL}" --system-site-packages --force
fi

info "Installing desktop entry and icon..."

fetch() {
    if command -v curl &>/dev/null; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget &>/dev/null; then
        wget -q "$1" -O "$2"
    else
        warn "curl/wget not found — skipping $(basename "$2")"
        return
    fi
}

copy_or_fetch() {
    local local_src="$1" remote_url="$2" dest="$3"
    if [[ "$LOCAL_INSTALL" == true ]]; then
        cp "$local_src" "$dest"
    else
        fetch "$remote_url" "$dest"
    fi
}

# Prefer /usr/local/share (always in XDG_DATA_DIRS) so XFCE/garcon picks it up
# reliably without needing XDG_DATA_HOME to be set. Fall back to ~/.local/share.
if sudo mkdir -p \
        /usr/local/share/applications \
        /usr/local/share/icons/hicolor/scalable/apps \
        /usr/local/share/icons/hicolor/48x48/apps 2>/dev/null; then
    DATA_SHARE=/usr/local/share
    INSTALL_CMD="sudo cp"
else
    warn "Cannot write to /usr/local/share — installing to ~/.local/share instead."
    warn "If the app menu entry does not appear, ensure XDG_DATA_HOME or ~/.local/share is in XDG_DATA_DIRS."
    DATA_SHARE="$HOME/.local/share"
    INSTALL_CMD="cp"
    mkdir -p \
        "$DATA_SHARE/applications" \
        "$DATA_SHARE/icons/hicolor/scalable/apps" \
        "$DATA_SHARE/icons/hicolor/48x48/apps"
fi

copy_or_fetch \
    "$SCRIPT_DIR/data/com.waystone.browser.desktop" \
    "${RAW_URL}/data/com.waystone.browser.desktop" \
    /tmp/com.waystone.browser.desktop

# Rewrite Exec with the full absolute path so XFCE/garcon finds the binary
# even when ~/.local/bin is not in the session's PATH.
WAYSTONE_BIN="$(command -v waystone 2>/dev/null || echo "$HOME/.local/bin/waystone")"
sed -i "s|^Exec=waystone|Exec=$WAYSTONE_BIN|" /tmp/com.waystone.browser.desktop

$INSTALL_CMD /tmp/com.waystone.browser.desktop "$DATA_SHARE/applications/com.waystone.browser.desktop"

copy_or_fetch \
    "$SCRIPT_DIR/data/icons/hicolor/scalable/apps/com.waystone.browser.svg" \
    "${RAW_URL}/data/icons/hicolor/scalable/apps/com.waystone.browser.svg" \
    /tmp/com.waystone.browser.svg
$INSTALL_CMD /tmp/com.waystone.browser.svg "$DATA_SHARE/icons/hicolor/scalable/apps/com.waystone.browser.svg"

copy_or_fetch \
    "$SCRIPT_DIR/data/icons/hicolor/48x48/apps/com.waystone.browser.png" \
    "${RAW_URL}/data/icons/hicolor/48x48/apps/com.waystone.browser.png" \
    /tmp/com.waystone.browser.png
$INSTALL_CMD /tmp/com.waystone.browser.png "$DATA_SHARE/icons/hicolor/48x48/apps/com.waystone.browser.png"

if [[ "$DATA_SHARE" == /usr/local/share ]]; then
    sudo update-desktop-database "$DATA_SHARE/applications/" 2>/dev/null || true
    sudo gtk-update-icon-cache -f -t "$DATA_SHARE/icons/hicolor" 2>/dev/null || true
else
    update-desktop-database "$DATA_SHARE/applications/" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$DATA_SHARE/icons/hicolor" 2>/dev/null || true
fi

# Remind user if ~/.local/bin is not in PATH permanently
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin is not in your PATH. Add this to ~/.bashrc or ~/.profile:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

info "Done! Run 'waystone' to start the browser."
