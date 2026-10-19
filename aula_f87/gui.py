"""GTK 4 / libadwaita window for AULA F87 lighting."""

import colorsys
import queue
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from . import about, autostart, device  # noqa: E402
from .settings import Settings  # noqa: E402
from .tray import SEPARATOR, Item  # noqa: E402
from .effects import (EFFECTS, FOLLOW_KEYS, MUSIC_FOLLOW, MUSIC_STYLES,  # noqa: E402
                      PER_KEY, PRESETS, SIDE_MODES,
                      SLEEP_MINUTES, Effect, battery_text, effect_info, nearest_sleep_index,
                      sleep_label)
from .layout import HEIGHT_U, KEY_X, KEYS, WIDTH_U  # noqa: E402

APP_ID = "io.github.aula_f87.Control"
ICON = "io.github.aula_f87.Control"
APPLY_DELAY_MS = 350
POLL_SECONDS = 3
BATTERY_EVERY_POLLS = 20  # about once a minute

CASE_COLOR = (0.10, 0.10, 0.11)
UNLIT_COLOR = (0.21, 0.21, 0.23)


def _rgba(rgb):
    color = Gdk.RGBA()
    color.parse("#%02x%02x%02x" % tuple(rgb))
    return color


def _rgb(rgba):
    return tuple(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue))


def _fill_rounded(snapshot, x, y, w, h, radius, rgb_float):
    rect = Graphene.Rect().init(x, y, w, h)
    clip = Gsk.RoundedRect()
    clip.init_from_rect(rect, radius)
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = (*rgb_float, 1.0)
    snapshot.push_rounded_clip(clip)
    snapshot.append_color(color, rect)
    snapshot.pop()


class Worker:
    """Runs device I/O off the UI thread, one job at a time."""

    def __init__(self):
        self._jobs = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, job, done=None, failed=None):
        self._jobs.put((job, done, failed))

    def _run(self):
        while True:
            job, done, failed = self._jobs.get()
            try:
                result = job()
            except Exception as exc:  # reported back to the UI
                if failed:
                    GLib.idle_add(lambda e=exc: failed(e) and False)
            else:
                if done:
                    GLib.idle_add(lambda r=result: done(r) and False)


class KeyboardView(Gtk.Widget):
    """Draws the 87-key board. With ``paint`` set, click/drag paints keys."""

    def __init__(self, color_for, paint=None, height=230):
        super().__init__(hexpand=True)
        self._color_for = color_for
        self._paint = paint
        self._height = height
        self._hits = []
        self._origin = (0.0, 0.0)
        self._button = 1
        if paint:
            drag = Gtk.GestureDrag(button=0)
            drag.connect("drag-begin", self._on_drag_begin)
            drag.connect("drag-update", self._on_drag_update)
            self.add_controller(drag)
            self.set_cursor(Gdk.Cursor.new_from_name("crosshair"))

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 480, 900, -1, -1
        return self._height, self._height, -1, -1

    def _on_drag_begin(self, gesture, x, y):
        self._origin = (x, y)
        self._button = gesture.get_current_button()
        self._paint_at(x, y)

    def _on_drag_update(self, _gesture, dx, dy):
        self._paint_at(self._origin[0] + dx, self._origin[1] + dy)

    def _paint_at(self, x, y):
        for kx, ky, kw, kh, led in self._hits:
            if kx <= x <= kx + kw and ky <= y <= ky + kh:
                self._paint(led, erase=self._button == 3)
                return

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        pad = 14
        unit = min((width - 2 * pad) / WIDTH_U, (height - 2 * pad) / HEIGHT_U)
        ox = (width - unit * WIDTH_U) / 2
        oy = (height - unit * HEIGHT_U) / 2
        _fill_rounded(snapshot, ox - unit * 0.3, oy - unit * 0.3, unit * (WIDTH_U + 0.6),
                      unit * (HEIGHT_U + 0.6), unit * 0.35, CASE_COLOR)

        font = Pango.FontDescription.from_string("Sans")
        font.set_absolute_size(max(6.0, unit * 0.22) * Pango.SCALE)
        dark_text, light_text = Gdk.RGBA(), Gdk.RGBA()
        dark_text.parse("rgba(25,25,25,0.85)")
        light_text.parse("rgba(242,242,242,0.85)")
        gap = unit * 0.08
        self._hits = []
        for key in KEYS:
            x = ox + key.x * unit + gap / 2
            y = oy + key.y * unit + gap / 2
            w = key.w * unit - gap
            h = unit - gap
            r, g, b = self._color_for(key.led)
            lit = r + g + b > 0
            _fill_rounded(snapshot, x, y, w, h, unit * 0.12,
                          (r / 255, g / 255, b / 255) if lit else UNLIT_COLOR)

            layout = self.create_pango_layout(key.label)
            layout.set_font_description(font)
            tw, th = layout.get_pixel_size()
            snapshot.save()
            snapshot.translate(Graphene.Point().init(x + (w - tw) / 2, y + (h - th) / 2))
            bright = lit and 0.299 * r + 0.587 * g + 0.114 * b > 140
            snapshot.append_layout(layout, dark_text if bright else light_text)
            snapshot.restore()
            self._hits.append((x, y, w, h, key.led))


class Swatch(Gtk.Widget):
    def __init__(self, rgb):
        super().__init__()
        self._rgb = tuple(c / 255 for c in rgb)

    def do_measure(self, _orientation, _for_size):
        return 22, 22, -1, -1

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        _fill_rounded(snapshot, 0, 0, w, h, 6, (0.5, 0.5, 0.5))
        _fill_rounded(snapshot, 1, 1, w - 2, h - 2, 5, self._rgb)


def _swatch(name, rgb, on_click):
    button = Gtk.Button(child=Swatch(rgb), tooltip_text=name, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: on_click(rgb))
    return button


def _level_scale(on_change):
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 4, 1)
    scale.set_digits(0)
    scale.set_round_digits(0)
    scale.set_draw_value(False)
    scale.set_size_request(240, -1)
    scale.set_valign(Gtk.Align.CENTER)
    for i in range(5):
        scale.add_mark(i, Gtk.PositionType.BOTTOM, str(i))
    scale.connect("value-changed", lambda *_: on_change())
    return scale


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AULA F87 Control")
        self.settings = Settings()
        self.set_default_size(*self.settings["window"])
        self.kb = None
        self.worker = Worker()
        self.state = device.Lighting()
        self.keys = [(0, 0, 0)] * device.PLANE
        self.brush = tuple(self.settings["brush"])
        self._effects = list(EFFECTS)
        self._loading = False
        self._connecting = False
        self._apply_source = 0
        self._apply_queued = False
        self._damaged = False   # the keyboard's stored settings need Repair
        self.music = None
        self._music_starting = False
        self._music_cancel = False  # window closed while music sync was starting
        self._music_colors = [(0, 0, 0)] * device.PLANE
        self._music_draw_pending = False
        self._polls = 0
        self.battery = None

        self.toasts = Adw.ToastOverlay()
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(self._lighting_page(), "lighting", "Lighting",
                                   "weather-clear-symbolic")
        stack.add_titled_with_icon(self._per_key_page(), "per-key", "Per-key colors",
                                   "applications-graphics-symbolic")
        stack.add_titled_with_icon(self._music_page(), "music", "Music sync",
                                   "audio-x-generic-symbolic")
        self.toasts.set_child(stack)
        stack.set_visible_child_name(self.settings["tab"])
        stack.connect("notify::visible-child-name",
                      lambda st, _p: self.settings.__setitem__("tab", st.get_visible_child_name()))

        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(
            stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        status = Gtk.Box(spacing=6)
        status.append(Gtk.Image(icon_name="input-keyboard-symbolic"))
        self.status_label = Gtk.Label(label="Looking for keyboard…")
        self.status_label.add_css_class("dim-label")
        status.append(self.status_label)
        header.pack_start(status)
        menu = Gio.Menu()
        menu.append(f"About {about.NAME}", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main menu", primary=True))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic",
                                         tooltip_text="Reconnect and reload from keyboard")
        self.refresh_button.connect("clicked", lambda *_: self.connect_keyboard())
        header.pack_end(self.refresh_button)

        self.banner = Adw.Banner(button_label="Retry")
        self.banner.connect("button-clicked", lambda *_: self._repair() if self._damaged
                            else self.connect_keyboard())

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        self.set_content(view)

        self.tray = None
        connection = app.get_dbus_connection()
        if connection is not None:
            from .tray import Tray
            self.tray = Tray(connection, "AULA F87 Control", self._tray_menu, self.show_window)

        self._sync_widgets()
        self.connect_keyboard()
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll)
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------ pages

    def _lighting_page(self):
        page = Adw.PreferencesPage()

        preview = Adw.PreferencesGroup()
        self.preview = KeyboardView(self._preview_color)
        preview.add(self.preview)
        page.add(preview)

        group = Adw.PreferencesGroup(title="Effect")
        self.effect_row = Adw.ComboRow(title="Lighting effect",
                                       model=Gtk.StringList.new([e.name for e in self._effects]))
        self.effect_row.connect("notify::selected", lambda *_: self._changed())
        group.add(self.effect_row)
        page.add(group)

        group = Adw.PreferencesGroup(title="Color")
        self.rainbow_row = Adw.SwitchRow(title="Rainbow",
                                         subtitle="Use all colors instead of a single one")
        self.rainbow_row.connect("notify::active", lambda *_: self._changed())
        group.add(self.rainbow_row)

        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                                  valign=Gtk.Align.CENTER)
        self.color_button.connect("notify::rgba", lambda *_: self._color_picked())
        self.color_row = Adw.ActionRow(title="Color", subtitle="Pick any color")
        self.color_row.add_suffix(self.color_button)
        self.color_row.set_activatable_widget(self.color_button)
        group.add(self.color_row)

        self.preset_row = Adw.ActionRow(title="Quick colors")
        presets = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        for name, rgb in PRESETS:
            presets.append(_swatch(name, rgb, self._pick_preset))
        self.preset_row.add_suffix(presets)
        group.add(self.preset_row)
        page.add(group)

        group = Adw.PreferencesGroup(title="Brightness and speed")
        self.brightness = _level_scale(self._changed)
        self.brightness_row = Adw.ActionRow(title="Brightness")
        self.brightness_row.add_suffix(self.brightness)
        group.add(self.brightness_row)
        self.speed = _level_scale(self._changed)
        self.speed_row = Adw.ActionRow(title="Speed")
        self.speed_row.add_suffix(self.speed)
        group.add(self.speed_row)
        page.add(group)

        group = Adw.PreferencesGroup(
            title="Side lights",
            description="The light bar above the arrow keys is set on the keyboard: "
                        "press Fn + Left Shift to cycle its effects.")
        self.side_row = Adw.ComboRow(title="Side lights effect",
                                     model=Gtk.StringList.new(list(SIDE_MODES)))
        self.side_row.connect("notify::selected", lambda *_: self._changed())
        group.add(self.side_row)
        page.add(group)

        group = Adw.PreferencesGroup(title="Power")
        self.battery_row = Adw.ActionRow(title="Battery", subtitle="—")
        group.add(self.battery_row)
        self.keep_on_row = Adw.SwitchRow(
            title="Keep backlight on",
            subtitle="Never turn the backlight off when idle. Uses more battery on 2.4G.")
        self.keep_on_row.connect("notify::active", lambda *_: self._sleep_changed())
        group.add(self.keep_on_row)
        self.sleep_row = Adw.ComboRow(
            title="Turn backlight off after", subtitle="Idle time without a key press",
            model=Gtk.StringList.new([sleep_label(m) for m in SLEEP_MINUTES]))
        self.sleep_row.set_selected(nearest_sleep_index(5))
        self.sleep_row.connect("notify::selected", lambda *_: self._sleep_changed())
        group.add(self.sleep_row)
        page.add(group)

        self.lighting_widgets = [self.effect_row, self.rainbow_row, self.color_row,
                                 self.preset_row, self.brightness_row, self.speed_row,
                                 self.side_row, self.keep_on_row, self.sleep_row]
        return page

    def _per_key_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                      margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        hint = Gtk.Label(label="Click or drag over keys to paint them. Right-click clears a key. "
                               "Press Apply to send the colors to the keyboard.",
                         xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        box.append(hint)

        self.paint_view = KeyboardView(lambda led: self.keys[led], paint=self._paint_key,
                                       height=330)
        self.paint_view.set_vexpand(True)
        box.append(self.paint_view)

        tools = Gtk.Box(spacing=8)
        tools.append(Gtk.Label(label="Brush"))
        self.brush_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                                  rgba=_rgba(self.brush),
                                                  valign=Gtk.Align.CENTER)
        self.brush_button.connect("notify::rgba", lambda b, _p: self._set_brush(_rgb(b.get_rgba())))
        tools.append(self.brush_button)
        for name, rgb in PRESETS:
            tools.append(_swatch(name, rgb, lambda c: self.brush_button.set_rgba(_rgba(c))))
        tools.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        fill = Gtk.Button(label="Fill all")
        fill.connect("clicked", lambda *_: self._fill_keys(self.brush))
        tools.append(fill)
        clear = Gtk.Button(label="Clear all")
        clear.connect("clicked", lambda *_: self._fill_keys((0, 0, 0)))
        tools.append(clear)

        spacer = Gtk.Box(hexpand=True)
        tools.append(spacer)
        self.apply_keys_button = Gtk.Button(label="Apply to keyboard")
        self.apply_keys_button.add_css_class("suggested-action")
        self.apply_keys_button.add_css_class("pill")
        self.apply_keys_button.connect("clicked", lambda *_: self._apply_keys())
        tools.append(self.apply_keys_button)
        box.append(tools)
        return box

    def _music_page(self):
        page = Adw.PreferencesPage()

        preview = Adw.PreferencesGroup()
        self.music_view = KeyboardView(lambda led: self._music_colors[led])
        preview.add(self.music_view)
        page.add(preview)

        group = Adw.PreferencesGroup(
            title="Music sync",
            description="The keys move with whatever this computer is playing, from any app. "
                        "Your saved lighting comes back when you stop.")
        self.music_button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
        self.music_button.add_css_class("pill")
        self.music_button.add_css_class("suggested-action")
        self.music_button.connect("clicked", lambda *_: self._toggle_music())
        self.music_row = Adw.ActionRow(title="Follow the music", subtitle="Stopped")
        self.music_row.add_suffix(self.music_button)
        group.add(self.music_row)

        self.music_style_row = Adw.ComboRow(title="Style",
                                            model=Gtk.StringList.new(list(MUSIC_STYLES)))
        self.music_style_row.set_selected(self.settings["music_style"])
        self.music_style_row.connect("notify::selected", lambda *_: self._music_settings())
        group.add(self.music_style_row)

        self._follow_updating = False
        self.follow_checks = {}
        follow_box = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER)
        for key, label in (("all", "All"),) + MUSIC_FOLLOW:
            check = Gtk.CheckButton(label=label)
            check.connect("toggled", lambda _b, k=key: self._follow_toggled(k))
            follow_box.append(check)
            self.follow_checks[key] = check
        self._show_follow(self.settings["music_follow"])
        follow_row = Adw.ActionRow(title="Follow", subtitle="What the lights react to")
        follow_row.add_suffix(follow_box)
        group.add(follow_row)

        self.sensitivity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 2.0, 0.05)
        self.brightness_music = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        for scale, value, marks in ((self.sensitivity, self.settings["music_sensitivity"],
                                     (0.2, 0.35, 0.5, 1.0, 1.5, 2.0)),
                                    (self.brightness_music, self.settings["music_brightness"],
                                     (0.25, 0.5, 0.75, 1.0))):
            scale.set_value(value)
            scale.set_draw_value(False)
            scale.set_size_request(240, -1)
            scale.set_valign(Gtk.Align.CENTER)
            for mark in marks:
                scale.add_mark(mark, Gtk.PositionType.BOTTOM, None)
            scale.connect("value-changed", lambda *_: self._music_settings())
        row = Adw.ActionRow(title="Sensitivity", subtitle="Higher = taller bars")
        row.add_suffix(self.sensitivity)
        group.add(row)
        row = Adw.ActionRow(title="Brightness")
        row.add_suffix(self.brightness_music)
        group.add(row)
        page.add(group)
        return page

    # ------------------------------------------------------------------ music

    def _set_brush(self, rgb):
        self.brush = rgb
        self.settings["brush"] = rgb

    def _toggle_music(self):
        """Start/stop chosen by the user; remembered so it resumes next time."""
        if self.music:
            self.settings["music_on"] = False
            self._stop_music()
        else:
            self.settings["music_on"] = True
            self._start_music()

    def _show_follow(self, selected):
        self._follow_updating = True
        try:
            self.follow_checks["all"].set_active(not selected)
            for key in FOLLOW_KEYS:
                self.follow_checks[key].set_active(key in selected)
        finally:
            self._follow_updating = False

    def _follow(self):
        return [key for key in FOLLOW_KEYS if self.follow_checks[key].get_active()]

    def _follow_toggled(self, key):
        """"All" and the specific choices exclude each other; with nothing
        picked, "All" ticks itself again."""
        if self._follow_updating:
            return
        checks = self.follow_checks
        if key == "all" and checks["all"].get_active():
            self._show_follow([])
        elif key != "all" and checks[key].get_active():
            self._show_follow(self._follow())
        elif not self._follow():
            self._show_follow([])
        self._music_settings()

    def _tray_follow(self, key):
        if key == "all":
            self._show_follow([])
            self._music_settings()
        else:
            self.follow_checks[key].set_active(not self.follow_checks[key].get_active())

    def _music_settings(self):
        self.settings["music_follow"] = self._follow()
        self.settings["music_style"] = self.music_style_row.get_selected()
        self.settings["music_sensitivity"] = round(self.sensitivity.get_value(), 2)
        self.settings["music_brightness"] = round(self.brightness_music.get_value(), 2)
        self._tray_refresh()
        if self.music:
            self.music.style = self.music_style_row.get_selected()
            self.music.sensitivity = self.sensitivity.get_value()
            self.music.brightness = self.brightness_music.get_value()
            self.music.follow = tuple(self._follow())

    def _start_music(self):
        if not self.kb or self._music_starting:
            return
        self._music_starting = True
        self._music_cancel = False
        self._sync_widgets()
        link = self.kb.link

        def on_frame(colors):  # music thread
            self._music_colors = colors
            if not self._music_draw_pending:
                self._music_draw_pending = True
                GLib.idle_add(self._draw_music_frame)

        def on_error(exc):  # music thread
            GLib.idle_add(lambda: self._music_failed(exc) and False)

        def done(sync):
            self._music_starting = False
            if sync.running and not self._music_cancel:  # it may already have failed
                self.music = sync
                self._music_settings()
            else:
                self.worker.submit(sync.stop)
            self._sync_widgets()

        def failed(exc):
            self._music_starting = False
            self.settings["music_on"] = False  # don't retry a start that can't work
            self._sync_widgets()
            self.toasts.add_toast(Adw.Toast(title=f"Couldn't start music sync: {exc}", timeout=6))

        def job():
            try:
                from .music import MusicSync  # needs numpy
            except ImportError as exc:
                raise RuntimeError(f"music sync needs numpy ({exc}). "
                                   "Install it with: sudo apt install python3-numpy") from None
            return MusicSync(link, on_frame, on_error)

        # Queued on the worker so it starts after any pending keyboard writes.
        self.worker.submit(job, done, failed)

    def _draw_music_frame(self):
        self._music_draw_pending = False
        self.music_view.queue_draw()
        return False

    def _stop_music(self, then=None):
        sync, self.music = self.music, None
        self._sync_widgets()

        def done(_result):
            self._music_colors = [(0, 0, 0)] * device.PLANE
            self.music_view.queue_draw()
            if then:
                then()

        if sync:
            self.worker.submit(sync.stop, done)

    def _music_failed(self, exc):
        self._stop_music()
        if isinstance(exc, OSError) or (self.kb and not self.kb.alive):
            self._disconnected("Lost connection to the keyboard.")
        self.toasts.add_toast(Adw.Toast(title=f"Music sync stopped: {exc}", timeout=6))

    def _remember_size(self):
        if self.get_visible() and not self.is_maximized() and self.get_width() > 0:
            self.settings["window"] = [self.get_width(), self.get_height()]

    def _on_close(self, *_):
        # Closing the window stops music sync, so the keyboard goes back to its
        # own lighting within a second. With the top-bar icon showing, the app
        # stays there (music sync can be started from its menu); "Quit" ends it.
        self._remember_size()
        if self.tray and self.tray.available:
            if self.music:
                self._stop_music()  # resumes when the window is opened again
            self._music_cancel = self._music_starting
            self.set_visible(False)
            return True
        self._shutdown()
        return False

    def _shutdown(self):
        self._remember_size()
        if self.music:
            self.music.stop()
            self.music = None
        if self.tray:
            self.tray.close()
            self.tray = None

    def show_window(self):
        self.set_visible(True)
        self.present()
        self._resume_music()

    def _resume_music(self):
        """Music sync was on when the window was last open (or before the
        keyboard dropped out): start it again."""
        if (self.settings["music_on"] and self.kb and self.get_visible()
                and not self.music and not self._music_starting):
            self._start_music()

    def quit_app(self):
        self._shutdown()
        self.get_application().quit()

    def show_about(self):
        """Version, links, and the changelog under "What's New"."""
        self.show_window()
        # The icon ships with the package too, for installs that didn't add it to the icon theme.
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(
            str(Path(__file__).resolve().parent / "data"))
        info = dict(application_name=about.NAME, application_icon=ICON, version=about.__version__,
                    developer_name=about.DEVELOPER, website=about.WEBSITE, issue_url=about.ISSUES,
                    license_type=Gtk.License.GPL_3_0, copyright=about.COPYRIGHT,
                    comments=about.SUMMARY, debug_info=self._debug_info())
        notes = about.release_notes_markup()
        if notes:
            info.update(release_notes=notes, release_notes_version=about.__version__)
        if hasattr(Adw, "AboutDialog"):        # libadwaita 1.5+
            dialog = Adw.AboutDialog(**info)
            dialog.add_link("Full changelog", about.CHANGELOG_URL)
            dialog.present(self)
        else:                                   # libadwaita 1.2-1.4
            window = Adw.AboutWindow(transient_for=self, modal=True, **info)
            window.add_link("Full changelog", about.CHANGELOG_URL)
            window.present()

    def _debug_info(self):
        import platform
        keyboard = self.kb.description if self.kb else "not connected"
        return "\n".join([
            f"{about.NAME} {about.__version__}",
            f"Keyboard: {keyboard}",
            f"Python {platform.python_version()}, GTK {Gtk.get_major_version()}."
            f"{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, libadwaita "
            f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}",
            f"System: {platform.platform()}",
        ])

    # ------------------------------------------------------------------ top-bar icon

    def _tray_menu(self):
        connected = self.kb is not None
        editable = connected and self.music is None and not self._music_starting
        header = self.kb.description if connected else "Keyboard not connected"
        items = [Item(header, enabled=False, key="keyboard")]
        if self._damaged:
            items.append(Item("Repair keyboard settings", self._repair))
        if connected and self.battery is not None:
            items.append(Item(f"Battery: {battery_text(self.battery, False)}", enabled=False,
                              key="battery"))
        items += [
            SEPARATOR,
            Item("Music sync", self._toggle_music, toggle="checkmark",
                 checked=self.music is not None, enabled=connected and not self._music_starting),
            Item("Music style", children=[
                Item(name, lambda i=i: self.music_style_row.set_selected(i), toggle="radio",
                     checked=self.music_style_row.get_selected() == i)
                for i, name in enumerate(MUSIC_STYLES)]),
            Item("Follow", children=[
                Item("All", lambda: self._tray_follow("all"), toggle="checkmark",
                     checked=not self._follow())
            ] + [
                Item(label, lambda k=key: self._tray_follow(k), toggle="checkmark",
                     checked=key in self._follow())
                for key, label in MUSIC_FOLLOW]),
            Item("Keep backlight on",
                 lambda: self.keep_on_row.set_active(not self.keep_on_row.get_active()),
                 toggle="checkmark", checked=self.keep_on_row.get_active(), enabled=editable),
            SEPARATOR,
            Item("Color", enabled=editable, children=[
                Item(name, lambda c=rgb: self._pick_preset(c)) for name, rgb in PRESETS
            ] + [SEPARATOR, Item("Rainbow", self._tray_rainbow, toggle="checkmark",
                                 checked=self.state.colorful or not effect_info(self.state.effect).color)]),
            Item("Effect", enabled=editable, children=[
                Item(e.name, lambda i=i: self.effect_row.set_selected(i), toggle="radio",
                     checked=e.id == self.state.effect)
                for i, e in enumerate(self._effects)]),
            Item("Brightness", enabled=editable and 1 <= self.state.effect <= 18, children=[
                Item("Off" if n == 0 else f"{n * 25}%", lambda n=n: self.brightness.set_value(n),
                     toggle="radio", checked=self.state.brightness == n)
                for n in range(5)]),
            SEPARATOR,
            Item("Open AULA F87 Control", self.show_window),
            Item("About", self.show_about),
            Item("Start at login", self._toggle_autostart, toggle="checkmark",
                 checked=autostart.is_enabled()),
            Item("Quit", self.quit_app),
        ]
        return items

    def _tray_rainbow(self):
        if effect_info(self.state.effect).color:
            self.rainbow_row.set_active(not self.rainbow_row.get_active())
        else:
            self.effect_row.set_selected(self._effect_index(3))  # Rainbow wave

    def _toggle_autostart(self):
        if autostart.is_enabled():
            autostart.disable()
        else:
            autostart.enable()
        self._tray_refresh()

    def _tray_refresh(self):
        if not self.tray:
            return
        percent = getattr(self.battery, "percent", None)
        label = f"{percent}%" if percent is not None and self.kb else ""
        tooltip = (self.kb.description if self.kb else
                   "Keyboard settings damaged: open to repair" if self._damaged else
                   "Keyboard not connected")
        self.tray.refresh(label=label, tooltip=tooltip)

    # ------------------------------------------------------------------ connection

    def connect_keyboard(self, quiet=False):
        if self._connecting or self.music or self._music_starting:
            return
        self._connecting = True
        old, self.kb = self.kb, None
        if not quiet:
            self.status_label.set_label("Connecting…")

        def job():
            if old:
                old.close()
            kb = device.connect()
            try:
                return kb, kb.read_lighting(), kb.read_keys(), kb.read_battery()
            except Exception:
                kb.close()
                raise

        def done(result):
            self._connecting = False
            self.kb, state, keys, battery = result
            self.keys = keys
            self._show_state(state)
            self.banner.set_revealed(False)
            self._show_battery(battery)
            self._sync_widgets()
            self.paint_view.queue_draw()
            self._resume_music()

        def failed(exc):
            self._connecting = False
            self._disconnected(str(exc), isinstance(exc, device.DamagedSettings))

        self.worker.submit(job, done, failed)

    def _disconnected(self, message, damaged=False):
        if self.kb:
            # Close on the worker so jobs already queued for this handle finish first.
            self.worker.submit(self.kb.close)
            self.kb = None
        if damaged and not self._damaged:
            self.show_window()  # the keyboard may not type until this is fixed
        self._damaged = damaged
        self.status_label.set_label("Settings damaged" if damaged else "Not connected")
        self.battery_row.set_subtitle("—")
        self.banner.set_title(message)
        self.banner.set_button_label("Repair" if damaged else "Retry")
        self.banner.set_revealed(True)
        self._sync_widgets()

    def _repair(self):
        """Write the keyboard's last good settings back (see Keyboard.repair)."""
        if self._connecting:
            return
        self._connecting = True  # no reconnect attempts meanwhile
        self.banner.set_revealed(False)
        self.status_label.set_label("Repairing…")

        def job():
            kb = device.connect()
            try:
                return kb.repair()
            finally:
                kb.close()

        def done(used):
            self._connecting = False
            self._damaged = False
            self.toasts.add_toast(Adw.Toast(title=f"Repaired: put back the keyboard's {used}",
                                            timeout=5))
            self.connect_keyboard()

        def failed(exc):
            self._connecting = False
            self._disconnected(f"Repair failed: {exc}", damaged=True)

        self.worker.submit(job, done, failed)

    def _poll(self):
        self._polls += 1
        if self.kb and not self.kb.alive:
            if self.music:
                self._stop_music()
            self._disconnected("The keyboard was unplugged.")
        elif not self.kb:
            self.connect_keyboard(quiet=True)
        elif (self._polls % BATTERY_EVERY_POLLS == 0 and not self.music
              and not self._music_starting):
            kb = self.kb
            self.worker.submit(kb.read_battery,
                               lambda battery: self.kb is kb and self._show_battery(battery))
        return True

    def _show_battery(self, battery):
        """Battery level over 2.4G; over the cable the keyboard runs on USB power."""
        if not self.kb:
            return
        text = battery_text(battery, self.kb.link.label == "USB cable", self.kb.last_battery())
        self.battery = battery
        self.battery_row.set_subtitle(text)
        suffix = f" · Battery {battery}" if battery is not None else ""
        self.status_label.set_label(self.kb.description + suffix)
        self._tray_refresh()

    # ------------------------------------------------------------------ power

    def _sleep_changed(self):
        keep_on = self.keep_on_row.get_active()
        self.sleep_row.set_sensitive(self.kb is not None and not keep_on and self.music is None)
        self._tray_refresh()
        if self._loading or not self.kb:
            return
        minutes = 0 if keep_on else SLEEP_MINUTES[self.sleep_row.get_selected()]
        self.state.sleep = minutes
        kb = self.kb
        message = ("Backlight stays on" if minutes == 0
                   else f"Backlight turns off after {sleep_label(minutes)} idle")
        self.worker.submit(lambda: kb.set_sleep(minutes),
                           lambda _r: self.toasts.add_toast(Adw.Toast(title=message, timeout=2)),
                           self._io_failed)

    # ------------------------------------------------------------------ lighting

    def _effect_index(self, effect_id):
        for i, e in enumerate(self._effects):
            if e.id == effect_id:
                return i
        info = effect_info(effect_id)
        self._effects.append(Effect(effect_id, f"{info.name} (set on keyboard)", True, True))
        self.effect_row.get_model().append(self._effects[-1].name)
        return len(self._effects) - 1

    def _show_state(self, state):
        self._loading = True
        try:
            self.state = state
            self.effect_row.set_selected(self._effect_index(state.effect))
            self.rainbow_row.set_active(state.colorful)
            self.color_button.set_rgba(_rgba(state.color))
            self.brightness.set_value(state.brightness)
            self.speed.set_value(state.speed)
            if state.side < len(SIDE_MODES):
                self.side_row.set_selected(state.side)
            self.keep_on_row.set_active(state.sleep == 0)
            if state.sleep:
                self.sleep_row.set_selected(nearest_sleep_index(state.sleep))
        finally:
            self._loading = False
        self._sync_widgets()

    def _read_widgets(self):
        index = self.effect_row.get_selected()
        effect = self._effects[index].id if index < len(self._effects) else self.state.effect
        return device.Lighting(
            effect=effect,
            brightness=int(self.brightness.get_value()),
            speed=int(self.speed.get_value()),
            colorful=self.rainbow_row.get_active(),
            color=_rgb(self.color_button.get_rgba()),
            side=self.side_row.get_selected(),
            sleep=self.state.sleep,
        )

    def _sync_widgets(self):
        busy = self.music is not None or self._music_starting
        connected = self.kb is not None and not busy  # music sync owns the keyboard while on
        info = effect_info(self.state.effect)
        timed = 1 <= self.state.effect <= 18
        for widget in self.lighting_widgets:
            widget.set_sensitive(connected)
        self.rainbow_row.set_sensitive(connected and info.color)
        self.brightness_row.set_sensitive(connected and timed)
        self.speed_row.set_sensitive(connected and timed and info.speed)
        self.sleep_row.set_sensitive(connected and not self.keep_on_row.get_active())
        self.apply_keys_button.set_sensitive(connected)
        self.refresh_button.set_sensitive(not busy)
        self.preview.queue_draw()

        running = self.music is not None
        self.music_button.set_label("Stop" if running else "Start")
        self.music_button.remove_css_class("destructive-action" if not running else "suggested-action")
        self.music_button.add_css_class("destructive-action" if running else "suggested-action")
        self.music_button.set_sensitive(self.kb is not None and not self._music_starting)
        if running:
            self.music_row.set_subtitle(f"On · {self.kb.link.label}" if self.kb else "On")
        else:
            self.music_row.set_subtitle("Starting…" if self._music_starting else
                                        "Stopped" if self.kb else "Connect the keyboard first")
        self._tray_refresh()

    def _pick_preset(self, rgb):
        self.color_button.set_rgba(_rgba(rgb))
        self._color_picked()  # notify::rgba doesn't fire if the color is unchanged

    def _color_picked(self):
        """Picking a color means "make it this color": leave rainbow mode and,
        if the current effect can't take a color, switch to Static."""
        if self._loading:
            return
        self._loading = True
        try:
            if not effect_info(self.state.effect).color:
                self.effect_row.set_selected(self._effect_index(1))
            self.rainbow_row.set_active(False)
        finally:
            self._loading = False
        self._changed()

    def _changed(self):
        if self._loading:
            return
        self.state = self._read_widgets()
        self._sync_widgets()
        if self.kb:
            if self._apply_source:
                GLib.source_remove(self._apply_source)
            self._apply_source = GLib.timeout_add(APPLY_DELAY_MS, self._apply_lighting)

    def _apply_lighting(self):
        self._apply_source = 0
        if not self.kb or self._apply_queued:
            return False  # a queued job will send the newest state
        self._apply_queued = True
        kb = self.kb

        def job():  # worker thread
            self._apply_queued = False
            kb.apply_lighting(self.state)

        self.worker.submit(job, None, self._io_failed)
        return False

    def _io_failed(self, exc):
        if isinstance(exc, device.DamagedSettings):
            self._disconnected(str(exc), damaged=True)
            return
        if isinstance(exc, OSError) or (self.kb and not self.kb.alive):
            self._disconnected("Lost connection to the keyboard.")
        self.toasts.add_toast(Adw.Toast(title=f"Couldn't update the keyboard: {exc}", timeout=5))

    def _preview_color(self, led):
        state = self.state
        if state.effect == 0:
            return (0, 0, 0)
        if state.effect == PER_KEY:
            return self.keys[led]
        info = effect_info(state.effect)
        if 1 <= state.effect <= 18 and state.brightness == 0:
            return (0, 0, 0)
        level = 0.4 + 0.6 * state.brightness / 4
        if state.colorful or not info.color:
            hue = KEY_X.get(led, 0) / WIDTH_U
            rgb = tuple(c * 255 for c in colorsys.hsv_to_rgb(hue, 1, 1))
        else:
            rgb = state.color
        return tuple(int(c * level) for c in rgb)

    # ------------------------------------------------------------------ per-key

    def _paint_key(self, led, erase=False):
        color = (0, 0, 0) if erase else self.brush
        if self.keys[led] != color:
            self.keys = list(self.keys)
            self.keys[led] = color
            self.paint_view.queue_draw()

    def _fill_keys(self, color):
        self.keys = list(self.keys)
        for key in KEYS:
            self.keys[key.led] = color
        self.paint_view.queue_draw()

    def _apply_keys(self):
        if not self.kb:
            return
        kb, keys = self.kb, list(self.keys)
        self.apply_keys_button.set_sensitive(False)

        def done(_result):
            self.apply_keys_button.set_sensitive(True)
            self.state.effect = PER_KEY
            self._show_state(self.state)
            self.toasts.add_toast(Adw.Toast(title="Per-key colors applied", timeout=2))

        def failed(exc):
            self.apply_keys_button.set_sensitive(True)
            self._io_failed(exc)

        self.worker.submit(lambda: kb.apply_keys(keys), done, failed)


class App(Adw.Application):
    def __init__(self, background=False):
        super().__init__(application_id=APP_ID)
        self._background = background

    def do_startup(self):
        Adw.Application.do_startup(self)
        # "quit" is reachable over D-Bus, so installers can stop a running copy:
        # gdbus call --session --dest io.github.aula_f87.Control \
        #   --object-path /io/github/aula_f87/Control --method org.gtk.Actions.Activate quit [] {}
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self._quit())
        self.add_action(action)
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", lambda *_: self.get_windows() and self.get_windows()[0].show_about())
        self.add_action(action)

    def _quit(self):
        windows = self.get_windows()
        if windows:
            windows[0].quit_app()
        else:
            self.quit()

    def do_activate(self):
        windows = self.get_windows()
        window = windows[0] if windows else Window(self)
        if self._background and not windows:
            # Started at login: stay in the top bar. Opening the app again shows the window.
            self._background = False
            return
        window.show_window()


def main(background=False):
    autostart.enable_on_first_run()
    app = App(background)
    if background:
        app.register(None)
        if app.get_is_remote():
            return 0  # already running; don't pop up a window at login
    return app.run(sys.argv[:1])
