"""Start the app at login (Linux): it runs in the background with its top-bar icon.

Uses the freedesktop autostart folder, which GNOME, KDE and most desktops read.
"""

import os
import shutil
import sys
from pathlib import Path

DESKTOP_ID = "io.github.aula_f87.Control"


def _path():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{DESKTOP_ID}.desktop"


def _command():
    found = shutil.which("aula-f87-control")
    if not found:
        script = Path(sys.argv[0]).resolve()
        found = str(script) if script.name == "aula-f87-control" else f"{sys.executable} -m aula_f87"
    return f'"{found}"' if " " in found and not found.endswith("-m aula_f87") else found


def is_enabled():
    path = _path()
    try:
        return "Hidden=true" not in path.read_text()
    except OSError:
        return False


def enable():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=AULA F87 Control\n"
        "Comment=Keyboard lighting, music sync and battery in the top bar\n"
        f"Exec={_command()} --background\n"
        f"Icon={DESKTOP_ID}\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n")


def disable():
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
