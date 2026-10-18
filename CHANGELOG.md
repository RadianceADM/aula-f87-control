# Changelog

## v0.3.1 — 2026-10-19

- **App settings are saved now.** The app remembers whether music sync is on, its style,
  sensitivity and brightness, the last tab, the brush color and the window size, in
  `settings.json`. If music sync was on, it starts again with the app, including at login,
  and again when the keyboard comes back. Pressing **Stop** keeps it off.

## v0.3.0 — 2026-10-19

- **Top-bar icon (Linux).** A quick menu for music sync and its style, keep backlight on,
  colors, effects and brightness, plus opening the window, start at login and quitting. The
  battery % is shown next to the icon over 2.4G. It's built directly on D-Bus
  (StatusNotifierItem + dbusmenu), so it needs no extra packages and works with Ubuntu's
  AppIndicators extension.
- **Runs in the background.** Closing the window keeps the app, and music sync, running in
  the top bar. Use **Quit** in the menu to stop it.
- **Starts at login.** `install.sh` and the quick installer turn this on and start the app
  right away. Turn it off with *Start at login* in the menu or `./install.sh --no-autostart`.
  Re-installing restarts a running copy so updates take effect.
- **New app icon.**
- New `--background` option.

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
