"""App preferences that live on the computer, not in the keyboard.

Lighting, per-key colors and the sleep timer are stored in the keyboard
itself. Everything else the app remembers between runs is kept here:
music sync (on/off, style, sensitivity, brightness), the last tab, the brush
color and the window size.

File: ~/.config/aula-f87-control/settings.json (Windows: %APPDATA%\\aula-f87-control).
"""

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "music_on": False,           # resume music sync when the app starts / the keyboard returns
    "music_style": 0,
    "music_sensitivity": 1.0,
    "music_brightness": 1.0,
    "tab": "lighting",
    "brush": [255, 0, 0],
    "window": [1060, 820],
}


def _default_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "aula-f87-control" / "settings.json"


def _clamp(value, lo, hi, default):
    try:
        return min(hi, max(lo, type(default)(value)))
    except (TypeError, ValueError):
        return default


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else _default_path()
        try:
            stored = json.loads(self.path.read_text())
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        self._data = dict(DEFAULTS)
        self._data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        self._validate()

    def _validate(self):
        d = self._data
        d["music_on"] = bool(d["music_on"])
        d["music_style"] = _clamp(d["music_style"], 0, 3, 0)
        d["music_sensitivity"] = _clamp(d["music_sensitivity"], 0.5, 2.0, 1.0)
        d["music_brightness"] = _clamp(d["music_brightness"], 0.1, 1.0, 1.0)
        if d["tab"] not in ("lighting", "per-key", "music"):
            d["tab"] = "lighting"
        try:
            d["brush"] = [max(0, min(255, int(c))) for c in d["brush"]][:3]
            assert len(d["brush"]) == 3
        except (TypeError, ValueError, AssertionError):
            d["brush"] = list(DEFAULTS["brush"])
        try:
            d["window"] = [max(640, int(d["window"][0])), max(480, int(d["window"][1]))]
        except (TypeError, ValueError, IndexError):
            d["window"] = list(DEFAULTS["window"])

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        if isinstance(value, tuple):
            value = list(value)
        if self._data.get(key) != value:
            self._data[key] = value
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self.path)  # atomic: a crash never leaves a half-written file
        except OSError:
            pass
