#!/usr/bin/env bash
# Quick install / update of AULA F87 Control on Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-linux.sh | bash
#
# Uninstall:
#   curl -fsSL https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-linux.sh | bash -s -- --uninstall
#
# What it does:
#   1. installs the required packages (apt, dnf or pacman; asks for your password)
#   2. downloads the latest release into ~/.local/share/aula-f87-control
#   3. installs the udev rule so your user can talk to the keyboard
#   4. adds the "AULA F87 Control" app-menu entry and the aula-f87-control command
#
# Options (environment variables):
#   AULA_DIR=/path      install somewhere else
#   AULA_VERSION=v0.2.0 install a specific release ("main" = latest code)
#   AULA_SOURCE=/path   install from a local checkout instead of downloading
set -euo pipefail

REPO="RadianceADM/aula-f87-control"
DEST="${AULA_DIR:-$HOME/.local/share/aula-f87-control}"
RULE="/etc/udev/rules.d/70-aula-f87.rules"

say()  { printf '\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

# Only ever delete a folder that holds this app (or is empty).
safe_to_replace() {
    [ ! -e "$1" ] || [ -d "$1/aula_f87" ] || [ -z "$(ls -A "$1" 2>/dev/null)" ]
}

if [ "${1:-}" = "--uninstall" ]; then
    if [ -x "$DEST/install.sh" ]; then "$DEST/install.sh" --remove; fi
    if [ -d "$DEST" ]; then
        safe_to_replace "$DEST" || die "$DEST doesn't look like an AULA F87 Control folder; not deleting it."
        rm -rf "$DEST"
    fi
    if [ -e "$RULE" ]; then
        say "Removing the udev rule (needs your password)"
        as_root rm -f "$RULE"
        as_root udevadm control --reload-rules || true
    fi
    say "AULA F87 Control is uninstalled."
    exit 0
fi

[ "$(uname -s)" = "Linux" ] || die "This installer is for Linux. On Windows use scripts/install-windows.ps1."

# 1. Packages -----------------------------------------------------------------
have_gtk()   { python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; }
have_numpy() { python3 -c 'import numpy' 2>/dev/null; }

if ! command -v python3 >/dev/null || ! have_gtk || ! have_numpy || ! command -v pw-record >/dev/null; then
    if command -v apt-get >/dev/null; then
        say "Installing packages with apt (needs your password)"
        as_root apt-get update -qq
        as_root apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy pipewire-bin
    elif command -v dnf >/dev/null; then
        say "Installing packages with dnf (needs your password)"
        as_root dnf install -y python3 python3-gobject gtk4 libadwaita python3-numpy pipewire-utils
    elif command -v pacman >/dev/null; then
        say "Installing packages with pacman (needs your password)"
        as_root pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita python-numpy pipewire
    else
        warn "Unknown package manager. Install Python 3, GTK 4, libadwaita, PyGObject, NumPy and"
        warn "PipeWire's pw-record yourself, then run this script again."
    fi
fi
command -v python3 >/dev/null || die "python3 is required."
have_gtk || warn "GTK 4 / libadwaita for Python isn't available; the app will use its simpler Tkinter window."

# 2. App files ------------------------------------------------------------------
safe_to_replace "$DEST" || die "$DEST exists and doesn't look like an AULA F87 Control folder. Set AULA_DIR to another path."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [ -n "${AULA_SOURCE:-}" ]; then
    say "Copying the app from $AULA_SOURCE"
    cp -r "$AULA_SOURCE/." "$tmp/"
    rm -rf "$tmp/.git"
else
    version="${AULA_VERSION:-}"
    if [ -z "$version" ]; then
        version="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
                   | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1 || true)"
        [ -n "$version" ] || version="main"
    fi
    if [ "$version" = "main" ]; then
        url="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
    else
        url="https://github.com/$REPO/archive/refs/tags/$version.tar.gz"
    fi
    say "Downloading AULA F87 Control $version"
    curl -fsSL "$url" | tar -xz -C "$tmp" --strip-components=1
fi
[ -f "$tmp/aula_f87/__main__.py" ] || die "The download doesn't contain the app."

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -r "$tmp" "$DEST"
chmod +x "$DEST/install.sh" "$DEST/aula-f87-control"

# 3. Permission to use the keyboard ------------------------------------------------
rule_ok() { [ -f "$RULE" ] && grep -qi '258a' "$RULE" && grep -qi '3554' "$RULE"; }
if ! rule_ok; then
    say "Installing the udev rule so your user can talk to the keyboard (needs your password)"
    as_root install -m 0644 "$DEST/udev/70-aula-f87.rules" "$RULE"
    as_root udevadm control --reload-rules || true
    as_root udevadm trigger || true
fi

# 4. Launcher and app-menu entry ---------------------------------------------------
"$DEST/install.sh" >/dev/null
say "Done. Open \"AULA F87 Control\" from the app menu, or run: aula-f87-control"
echo "If the keyboard isn't found, unplug and replug its cable or receiver once."
echo "To update later, run the same command again."
