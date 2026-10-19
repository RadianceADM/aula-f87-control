"""Top-bar icon and menu for GNOME and other Linux desktops.

Implements the StatusNotifierItem and com.canonical.dbusmenu D-Bus
interfaces directly with Gio, so it needs no extra packages and lives inside
the GTK 4 app. On Ubuntu the built-in "Ubuntu AppIndicators" extension shows
it in the top bar. Other desktops with a StatusNotifierItem host (KDE, most
panels) work the same way.
"""

from dataclasses import dataclass, field
from pathlib import Path

from gi.repository import Gio, GLib

DATA_DIR = Path(__file__).resolve().parent / "data"
ICON_NAME = "io.github.aula_f87.Control-symbolic"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"

_SNI_XML = """<node><interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconThemePath" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <property name="XAyatanaLabel" type="s" access="read"/>
  <property name="XAyatanaLabelGuide" type="s" access="read"/>
  <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  <signal name="NewTitle"/>
  <signal name="NewIcon"/>
  <signal name="NewToolTip"/>
  <signal name="NewStatus"><arg type="s"/></signal>
  <signal name="XAyatanaNewLabel"><arg type="s"/><arg type="s"/></signal>
</interface></node>"""

_MENU_XML = """<node><interface name="com.canonical.dbusmenu">
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout">
    <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
    <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
  </method>
  <method name="GetGroupProperties">
    <arg type="ai" direction="in"/><arg type="as" direction="in"/>
    <arg type="a(ia{sv})" direction="out"/>
  </method>
  <method name="GetProperty">
    <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
  </method>
  <method name="Event">
    <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
    <arg type="u" direction="in"/>
  </method>
  <method name="EventGroup">
    <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
  </method>
  <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  <method name="AboutToShowGroup">
    <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
  </method>
  <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
</interface></node>"""


@dataclass
class Item:
    """One menu entry. ``toggle`` is None, "checkmark" or "radio".

    ``key`` identifies the entry across rebuilds when its label changes."""
    label: str = ""
    action: object = None
    toggle: str = None
    checked: bool = False
    enabled: bool = True
    children: list = None
    separator: bool = False
    key: str = None


SEPARATOR = Item(separator=True)


@dataclass
class _Node:
    item: Item
    children: list = field(default_factory=list)


class Tray:
    """Publishes the icon and a menu built by ``build_menu()`` (a list of Items).

    Call ``refresh()`` whenever the state shown in the menu changes.
    ``available`` is True while a top-bar host is showing the icon.
    """

    def __init__(self, connection, title, build_menu, on_activate):
        self._conn = connection
        self._title = title
        self._build_menu = build_menu
        self._on_activate = on_activate
        self._label = ""
        self._tooltip = title
        self._revision = 1
        self._nodes = {}
        # Ids stay the same for the same entry and are never reused: the top-bar
        # host updates entries by id and doesn't expect one to change type
        # (e.g. separator -> entry) when entries come and go.
        self._menu_ids = {}
        self._next_id = 0
        self.available = False
        self._rebuild()

        sni = Gio.DBusNodeInfo.new_for_xml(_SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]
        self._ids = [
            connection.register_object(ITEM_PATH, sni, self._item_call, self._item_get, None),
            connection.register_object(MENU_PATH, menu, self._menu_call, self._menu_get, None),
        ]
        self._watch = Gio.bus_watch_name_on_connection(
            connection, WATCHER, Gio.BusNameWatcherFlags.NONE,
            self._watcher_appeared, self._watcher_vanished)

    # ------------------------------------------------------------------ public

    def refresh(self, label=None, tooltip=None):
        """Rebuild the menu; optionally update the text next to the icon."""
        self._rebuild()
        self._revision += 1
        self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                   GLib.Variant("(ui)", (self._revision, 0)))
        if label is not None and label != self._label:
            self._label = label
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "XAyatanaNewLabel",
                       GLib.Variant("(ss)", (label, "100%")))
        if tooltip is not None and tooltip != self._tooltip:
            self._tooltip = tooltip
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip", None)

    def close(self):
        Gio.bus_unwatch_name(self._watch)
        for reg in self._ids:
            self._conn.unregister_object(reg)
        self.available = False

    # ------------------------------------------------------------------ registration

    def _watcher_appeared(self, connection, _name, _owner):
        def registered(conn, result):
            try:
                conn.call_finish(result)
                self.available = True
            except GLib.Error:
                self.available = False

        connection.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                        GLib.Variant("(s)", (connection.get_unique_name(),)), None,
                        Gio.DBusCallFlags.NONE, -1, None, registered)

    def _watcher_vanished(self, _connection, _name):
        self.available = False

    def _emit(self, path, interface, signal, params):
        try:
            self._conn.emit_signal(None, path, interface, signal, params)
        except GLib.Error:
            pass

    # ------------------------------------------------------------------ StatusNotifierItem

    def _item_get(self, _conn, _sender, _path, _iface, name):
        values = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", "aula-f87-control"),
            "Title": GLib.Variant("s", self._title),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", ICON_NAME),
            "IconThemePath": GLib.Variant("s", str(DATA_DIR)),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (ICON_NAME, [], self._title, self._tooltip)),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
            "XAyatanaLabel": GLib.Variant("s", self._label),
            "XAyatanaLabelGuide": GLib.Variant("s", "100%"),
        }
        return values.get(name)

    def _item_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(lambda: self._on_activate() and False)
        invocation.return_value(None)

    # ------------------------------------------------------------------ dbusmenu

    def _rebuild(self):
        """Give every entry its id (see ``_menu_ids``) and remember the tree."""
        self._nodes = {0: _Node(Item(), [])}

        def add(parent_id, parent_key, items):
            separators, seen = 0, {}
            for item in items:
                if item.separator:
                    separators += 1
                    own = f"separator {separators}"
                else:
                    own = item.key or item.label
                seen[own] = seen.get(own, 0) + 1
                key = f"{parent_key}/{own}" + (f"#{seen[own]}" if seen[own] > 1 else "")
                if key not in self._menu_ids:
                    self._next_id += 1
                    self._menu_ids[key] = self._next_id
                node_id = self._menu_ids[key]
                self._nodes[node_id] = _Node(item, [])
                self._nodes[parent_id].children.append(node_id)
                if item.children:
                    add(node_id, key, item.children)

        add(0, "", self._build_menu())

    def _props(self, node_id):
        item = self._nodes[node_id].item
        if node_id == 0:
            return {"children-display": GLib.Variant("s", "submenu")}
        if item.separator:
            return {"type": GLib.Variant("s", "separator")}
        props = {"label": GLib.Variant("s", item.label.replace("_", "__")),
                 "enabled": GLib.Variant("b", item.enabled)}
        if item.toggle:
            props["toggle-type"] = GLib.Variant("s", item.toggle)
            props["toggle-state"] = GLib.Variant("i", 1 if item.checked else 0)
        if item.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        return props

    def _layout(self, node_id, depth):
        children = []
        if depth != 0:
            children = [self._layout(child, depth - 1) for child in self._nodes[node_id].children]
        return GLib.Variant("(ia{sv}av)", (node_id, self._props(node_id), children))

    def _menu_get(self, _conn, _sender, _path, _iface, name):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(name)

    def _click(self, node_id):
        node = self._nodes.get(node_id)
        if node and node.item.action and node.item.enabled:
            GLib.idle_add(lambda: node.item.action() and False)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent, depth, _names = args
            if parent not in self._nodes:
                parent = 0
            layout = self._layout(parent, depth)
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self._revision), layout))
        elif method == "GetGroupProperties":
            ids = args[0] or list(self._nodes)
            result = [(i, self._props(i)) for i in ids if i in self._nodes]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            node_id, name = args
            value = self._props(node_id).get(name) if node_id in self._nodes else None
            invocation.return_value(GLib.Variant("(v)", (value or GLib.Variant("s", ""),)))
        elif method == "Event":
            node_id, event, _data, _time = args
            if event == "clicked":
                self._click(node_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            for node_id, event, _data, _time in args[0]:
                if event == "clicked":
                    self._click(node_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
