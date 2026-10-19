"""Start the app at login (Linux): it runs in the background with its top-bar icon.

Uses the freedesktop autostart folder, which GNOME, KDE and most desktops read.
Turning it off writes the entry with ``Hidden=true`` (the standard way to say
"don't start this"), so the choice is remembered and also overrides a
system-wide entry. On its first run the app turns start-at-login on, unless
an entry already exists, so every install method behaves the same.
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


def _write(hidden):
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
        "X-GNOME-Autostart-enabled=true\n"
        + ("Hidden=true\n" if hidden else ""))


def is_configured():
    return _path().exists()


def is_enabled():
    try:
        return "Hidden=true" not in _path().read_text()
    except OSError:
        return False


def enable():
    _write(hidden=False)


def disable():
    _write(hidden=True)


def enable_on_first_run():
    """Turn start-at-login on the first time the app runs (never after the user chose)."""
    if not is_configured():
        try:
            enable()
        except OSError:
            pass
