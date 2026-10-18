#!/bin/sh
# Linux install for the current user: a launcher in ~/.local/bin and an app-menu entry.
# Runs the app straight from this folder, so keep the folder where it is.
#
# Usage: ./install.sh           install
#        ./install.sh --remove  uninstall
set -e

here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin/aula-f87-control"
desktop="$HOME/.local/share/applications/io.github.aula_f87.Control.desktop"

if [ "$1" = "--remove" ]; then
    rm -f "$bin" "$desktop"
    echo "Removed the launcher and the app-menu entry."
    echo "To also remove the udev rule: sudo rm /etc/udev/rules.d/70-aula-f87.rules"
    exit 0
fi

# Check the Python packages the app needs.
missing=""
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' \
    2>/dev/null || missing="$missing python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
python3 -c 'import numpy' 2>/dev/null || missing="$missing python3-numpy"
command -v pw-record >/dev/null 2>&1 || missing="$missing pipewire-bin"
if [ -n "$missing" ]; then
    echo "Missing packages. On Ubuntu/Debian install them with:"
    echo "  sudo apt install$missing"
    echo "(Without GTK 4 the app falls back to its simpler Tkinter window: sudo apt install python3-tk.)"
    echo
fi

mkdir -p "$(dirname "$bin")" "$(dirname "$desktop")"
chmod +x "$here/aula-f87-control"
ln -sf "$here/aula-f87-control" "$bin"

cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AULA F87 Control
Comment=Backlight, per-key colors and music sync for the AULA F87 keyboard
Exec=$bin
Icon=input-keyboard
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=keyboard;rgb;backlight;aula;music;
StartupWMClass=io.github.aula_f87.Control
EOF

if [ ! -e /etc/udev/rules.d/70-aula-f87.rules ]; then
    echo "One more step: allow your user to talk to the keyboard (needs your password):"
    echo "  sudo cp '$here/udev/70-aula-f87.rules' /etc/udev/rules.d/"
    echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
    echo
fi
echo "Installed. Open \"AULA F87 Control\" from the app menu, or run: aula-f87-control"
