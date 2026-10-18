# Changelog

## v0.2.0 — 2026-10-19

First public release.

- **Lighting:** 14 built-in effects in any color or rainbow, with brightness, speed and the
  side lights effect.
- **Per-key colors:** paint keys on an on-screen keyboard and save them to the keyboard.
- **Music sync:** the keys follow whatever the computer plays. Styles are EQ bars, meter
  colors, rainbow and beat pulse. It uses live frames that are never saved to the keyboard.
- **Power:** battery level over 2.4G (the last reading is shown while on the cable), plus a
  *Keep backlight on* switch and a *Turn backlight off after* timer.
- **Apps:** a GTK 4 / libadwaita app on Linux and a Tkinter app on Windows and macOS. The
  command line has `status`, `set`, `sleep` and `music`.
- **Connections:** USB cable and 2.4G receiver. Linux uses hidraw and PipeWire. Windows and
  macOS use hidapi and soundcard.
- **Quick install scripts:** `scripts/install-linux.sh` and `scripts/install-windows.ps1`.
- **Protocol reference:** [docs/PROTOCOL.md](docs/PROTOCOL.md).
