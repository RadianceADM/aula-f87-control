"""Version and changelog for the About window.

The changelog is CHANGELOG.md. Builds copy it into the package as
``aula_f87/data/CHANGELOG.md`` (see setup.py); a source checkout reads it from
the top of the repo.
"""

import html
import re
from pathlib import Path

from . import __version__

NAME = "AULA F87 Control"
DEVELOPER = "RadianceADM"
WEBSITE = "https://github.com/RadianceADM/aula-f87-control"
ISSUES = WEBSITE + "/issues"
CHANGELOG_URL = WEBSITE + "/blob/main/CHANGELOG.md"
SUMMARY = ("Backlight effects, per-key colors, music sync, sleep timer and battery level "
           "for AULA F87 / F87 Pro keyboards")
LICENSE = "GPL-3.0-or-later"
COPYRIGHT = "© 2026 RadianceADM"


def changelog_path():
    here = Path(__file__).resolve().parent
    for path in (here / "data" / "CHANGELOG.md", here.parent / "CHANGELOG.md"):
        if path.is_file():
            return path
    return None


def releases():
    """[(version, date, [(depth, text), ...]), ...], newest first.
    depth 0 is a top-level bullet, 1 a sub-bullet; text is still Markdown."""
    path = changelog_path()
    if path is None:
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"## v?(\S+)\s*(?:[—–-]\s*(.+))?$", line)
        if heading:
            out.append((heading[1], (heading[2] or "").strip(), []))
            continue
        if not out or not line.strip():
            continue
        items = out[-1][2]
        bullet = re.match(r"( *)- (.*)", line)
        if bullet:
            items.append((min(len(bullet[1]) // 2, 1), bullet[2].strip()))
        elif items:  # wrapped line of the previous bullet
            depth, text = items[-1]
            items[-1] = (depth, f"{text} {line.strip()}")
    return out


def _inline(text, bold, italic, code):
    """Markdown emphasis, code and links -> the given markup."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(code(part[1:-1]))
            continue
        part = re.sub(r"\*\*(.+?)\*\*", lambda m: bold(m[1]), part)
        part = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", lambda m: italic(m[1]), part)
        out.append(part)
    return "".join(out)


def plain(text):
    return _inline(text, lambda s: s, lambda s: s, lambda s: s)


def release_notes_markup(entries=None):
    """AppStream-style markup for Adw.AboutDialog (p, ul, li, em, code).

    The dialog already titles the notes with this version, so only older
    versions get a heading of their own."""
    esc = html.escape
    chunks = []
    for version, date, items in (releases() if entries is None else entries):
        if version != __version__:
            title = f"Version {version}" + (f" · {date}" if date else "")
            chunks.append(f"<p><em>{esc(title)}</em></p>")
        if items:
            lis = "".join("<li>{}</li>".format(_inline(
                esc(text, quote=False),
                lambda s: f"<em>{s}</em>", lambda s: s, lambda s: f"<code>{s}</code>"))
                for _depth, text in items)
            chunks.append(f"<ul>{lis}</ul>")
    return "".join(chunks)


__all__ = ["__version__", "NAME", "DEVELOPER", "WEBSITE", "ISSUES", "CHANGELOG_URL", "SUMMARY",
           "LICENSE", "COPYRIGHT", "changelog_path", "releases", "plain", "release_notes_markup"]
