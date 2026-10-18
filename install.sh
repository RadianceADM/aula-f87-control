#!/bin/sh
# Linux install for the current user, run from this folder (keep the folder where it is):
#   - the aula-f87-control command in ~/.local/bin
#   - the "AULA F87 Control" app-menu entry and icon
#   - start at login in the background, with the top-bar icon
#     (turn it off from the icon's menu: "Start at login")
#
# Usage: ./install.sh                 install (and start the app in the background)
#        ./install.sh --no-autostart  install without starting at login
#        ./install.sh --remove        uninstall
set -e

here=$(cd "$(dirname "$0")" && pwd)
app_id="io.github.aula_f87.Control"
bin="$HOME/.local/bin/aula-f87-control"
desktop="$HOME/.local/share/applications/$app_id.desktop"
autostart="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$app_id.desktop"
icons="$HOME/.local/share/icons/hicolor"

# Ask a running copy to quit (it answers on D-Bus), e.g. before an update.
quit_running() {
    gdbus call --session --dest "$app_id" --object-path /io/github/aula_f87/Control \
        --method org.gtk.Actions.Activate quit '[]' '{}' >/dev/null 2>&1 && sleep 1 || true
}

if [ "$1" = "--remove" ]; then
    quit_running
    rm -f "$bin" "$desktop" "$autostart" \
          "$icons/scalable/apps/$app_id.svg" "$icons/symbolic/apps/$app_id-symbolic.svg"
    echo "Removed the command, the app-menu entry, the icon and start at login."
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

mkdir -p "$(dirname "$bin")" "$(dirname "$desktop")" "$icons/scalable/apps" "$icons/symbolic/apps"
chmod +x "$here/aula-f87-control"
ln -sf "$here/aula-f87-control" "$bin"
cp "$here/aula_f87/data/$app_id.svg" "$icons/scalable/apps/"
cp "$here/aula_f87/data/$app_id-symbolic.svg" "$icons/symbolic/apps/"

cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AULA F87 Control
Comment=Backlight, per-key colors, music sync and battery for the AULA F87 keyboard
Exec=$bin
Icon=$app_id
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=keyboard;rgb;backlight;aula;music;battery;
StartupWMClass=$app_id
EOF

if [ "$1" != "--no-autostart" ]; then
    mkdir -p "$(dirname "$autostart")"
    cat > "$autostart" <<EOF
[Desktop Entry]
Type=Application
Name=AULA F87 Control
Comment=Keyboard lighting, music sync and battery in the top bar
Exec=$bin --background
Icon=$app_id
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
fi

if [ ! -e /etc/udev/rules.d/70-aula-f87.rules ]; then
    echo "One more step: allow your user to talk to the keyboard (needs your password):"
    echo "  sudo cp '$here/udev/70-aula-f87.rules' /etc/udev/rules.d/"
    echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
    echo
fi

# Start it now (top-bar icon only) when installing from a desktop session.
if [ "$1" != "--no-autostart" ] && [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    quit_running  # restart an older copy so the update takes effect
    (setsid "$bin" --background >/dev/null 2>&1 &) || true
fi

echo "Installed. Open \"AULA F87 Control\" from the app menu, or run: aula-f87-control"
if [ "$1" != "--no-autostart" ]; then
    echo "It also starts at login with an icon in the top bar (turn off in the icon's menu)."
fi
