"""Gestionnaire de fichiers du rice Hyprland (GTK4 + libadwaita)."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

import hashlib
import mimetypes
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import core
from i18n import tr

APP_ID = "fr.forsaken.Fichiers"
THUMB_SIZE = 128
THUMB_DIR = Path.home() / ".cache" / "studio" / "thumbs"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif", ".heic", ".heif"}
ARCHIVE_EXT = {".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
               ".tar.zst", ".gz", ".bz2", ".xz", ".7z", ".rar", ".zst"}
_STUDIO_CFG = Path.home() / ".config" / "studio" / "studio.json"
_THUMB_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="thumb")


def _xdg(key, fallback):
    try:
        r = subprocess.run(["xdg-user-dir", key], capture_output=True, text=True, timeout=2)
        p = Path(r.stdout.strip())
        return p if p.is_dir() else fallback
    except Exception:
        return fallback


BOOKMARKS = [
    ("Accueil",         Path.home(),                                          "user-home-symbolic"),
    ("Bureau",          _xdg("DESKTOP",    Path.home() / "Bureau"),           "user-desktop-symbolic"),
    ("Documents",       _xdg("DOCUMENTS",  Path.home() / "Documents"),        "folder-documents-symbolic"),
    ("Téléchargements", _xdg("DOWNLOAD",   Path.home() / "Téléchargements"),  "folder-download-symbolic"),
    ("Images",          _xdg("PICTURES",   Path.home() / "Images"),           "folder-pictures-symbolic"),
    ("Musique",         _xdg("MUSIC",      Path.home() / "Musique"),          "folder-music-symbolic"),
    ("Vidéos",          _xdg("VIDEOS",     Path.home() / "Vidéos"),           "folder-videos-symbolic"),
]


def _human_size(n):
    for unit, div in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} o"


def _human_date(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def _make_thumb(path):
    try:
        from PIL import Image
        key = hashlib.sha1(f"{path}{path.stat().st_mtime}".encode()).hexdigest()[:16]
        out = THUMB_DIR / f"{key}.png"
        if not out.exists():
            THUMB_DIR.mkdir(parents=True, exist_ok=True)
            im = Image.open(path)
            im.thumbnail((THUMB_SIZE, THUMB_SIZE))
            im.convert("RGBA").save(out)
        return str(out)
    except Exception:
        return None


def _icon_for_type(ctype):
    if ctype.startswith("image/"):  return "image-x-generic-symbolic"
    if ctype.startswith("video/"):  return "video-x-generic-symbolic"
    if ctype.startswith("audio/"):  return "audio-x-generic-symbolic"
    if ctype.startswith("text/"):   return "text-x-generic-symbolic"
    if "pdf" in ctype:              return "application-pdf-symbolic"
    if any(x in ctype for x in ("zip", "tar", "gzip", "bzip", "xz", "7z", "rar")):
        return "package-x-generic-symbolic"
    return "text-x-generic-symbolic"


def _ctype_label(ctype):
    if ctype == "inode/directory": return tr("Dossier")
    t = ctype.split("/")[-1].split("+")[0].replace("-", " ")
    return t.upper() if len(t) <= 4 else t.capitalize()


# ─── FileItem GObject ────────────────────────────────────────────────────────

class FileItem(GObject.Object):
    __gtype_name__ = "FichierItem"

    thumb = GObject.Property(type=str, default="")

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.name = path.name
        self.is_dir = False
        self.size = 0
        self.mtime = 0.0
        self.ctype = "inode/directory"
        self.icon_name = "folder-symbolic"

        try:
            s = path.lstat()
            if stat.S_ISLNK(s.st_mode):
                try:
                    s = path.stat()
                except OSError:
                    pass
            self.is_dir = stat.S_ISDIR(s.st_mode)
            self.size = s.st_size
            self.mtime = s.st_mtime
        except OSError:
            pass

        if self.is_dir:
            self.ctype = "inode/directory"
            self.icon_name = "folder-symbolic"
        else:
            self.ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.icon_name = _icon_for_type(self.ctype)


# ─── BreadcrumbBar ───────────────────────────────────────────────────────────

class BreadcrumbBar(Gtk.Stack):
    def __init__(self, on_navigate):
        super().__init__(transition_type=Gtk.StackTransitionType.NONE)
        self._navigate = on_navigate
        self._path = Path.home()

        self._box = Gtk.Box(spacing=0)
        sw = Gtk.ScrolledWindow(
            child=self._box,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            hexpand=True, has_frame=False,
        )
        self._sw = sw
        # Clic sur fond → mode saisie
        click = Gtk.GestureClick(button=1)
        click.connect("released", lambda g, n, x, y: (
            self.show_entry() if not isinstance(self._sw.pick(x, y, Gtk.PickFlags.DEFAULT), Gtk.Button) else None
        ))
        sw.add_controller(click)
        self.add_named(sw, "crumbs")

        self._entry = Gtk.Entry(hexpand=True)
        self._entry.connect("activate", self._entry_activate)
        ctl = Gtk.EventControllerKey()
        ctl.connect("key-pressed", self._entry_key)
        self._entry.add_controller(ctl)
        self.add_named(self._entry, "entry")
        self.set_visible_child_name("crumbs")

    def show_entry(self):
        self._entry.set_text(str(self._path))
        self.set_visible_child_name("entry")
        self._entry.grab_focus()
        self._entry.select_region(0, -1)

    def _entry_activate(self, entry):
        p = Path(entry.get_text().strip()).expanduser()
        if p.is_dir():
            self._navigate(p)
        self.set_visible_child_name("crumbs")

    def _entry_key(self, ctl, keyval, _code, _mods):
        if keyval == Gdk.KEY_Escape:
            self.set_visible_child_name("crumbs")
            return True
        return False

    def set_path(self, path):
        self._path = path
        while (c := self._box.get_first_child()):
            self._box.remove(c)

        parts = []
        p = path
        while True:
            parts.append(p)
            if p.parent == p:
                break
            p = p.parent
        parts.reverse()

        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if part == Path.home():
                btn = Gtk.Button(css_classes=["flat"])
                btn.set_child(Gtk.Image(icon_name="user-home-symbolic", pixel_size=14))
            elif str(part) == "/":
                btn = Gtk.Button(css_classes=["flat"])
                btn.set_child(Gtk.Image(icon_name="drive-harddisk-symbolic", pixel_size=14))
            else:
                btn = Gtk.Button(label=part.name, css_classes=["flat"])
            if is_last:
                btn.set_sensitive(False)
            else:
                btn.connect("clicked", lambda b, pp=part: self._navigate(pp))
            self._box.append(btn)
            if not is_last:
                self._box.append(Gtk.Label(label=" › ", css_classes=["dim-label"]))

        GLib.idle_add(lambda: (
            self._sw.get_hadjustment().set_value(self._sw.get_hadjustment().get_upper()), False
        )[1])
        self.set_visible_child_name("crumbs")


# ─── Dialogue de progression ─────────────────────────────────────────────────

class ProgressDialog(Adw.Dialog):
    def __init__(self, parent, title):
        super().__init__(title=tr(title), content_width=440)
        self._cancelled = False

        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        self._label = Gtk.Label(xalign=0, wrap=True, max_width_chars=52,
                                css_classes=["dim-label"], margin_bottom=8)
        self._bar = Gtk.ProgressBar(hexpand=True)
        self._bar.set_pulse_step(0.05)
        cancel = Gtk.Button(label=tr("Annuler"), halign=Gtk.Align.CENTER, margin_top=12)
        cancel.connect("clicked", lambda _: self._on_cancel())
        for w in (self._label, self._bar, cancel):
            g.add(w)
        page.add(g)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.present(parent)

    def update(self, text, fraction):
        def _do():
            self._label.set_text(text)
            if fraction < 0:
                self._bar.pulse()
            else:
                self._bar.set_fraction(fraction)
            return False
        GLib.idle_add(_do)

    def _on_cancel(self):
        self._cancelled = True
        GLib.idle_add(self.close)

    @property
    def cancelled(self):
        return self._cancelled


# ─── Dialogue de propriétés ──────────────────────────────────────────────────

class PropertiesDialog(Adw.Dialog):
    def __init__(self, parent, items):
        title = tr("Propriétés") if len(items) == 1 else tr("{n} éléments", n=len(items))
        super().__init__(title=title, content_width=440)

        page = Adw.PreferencesPage()

        if len(items) == 1:
            item = items[0]
            g = Adw.PreferencesGroup()
            # Nom (éditable)
            name_row = Adw.EntryRow(title=tr("Nom"), text=item.name)
            g.add(name_row)
            page.add(g)

            g2 = Adw.PreferencesGroup()
            for label, val in [
                (tr("Emplacement"), str(item.path.parent)),
                (tr("Type"), _ctype_label(item.ctype)),
                (tr("Taille"), tr("Dossier") if item.is_dir else _human_size(item.size)),
                (tr("Modifié le"), _human_date(item.mtime)),
            ]:
                r = Adw.ActionRow(title=label, subtitle=val)
                r.set_subtitle_selectable(True)
                g2.add(r)

            # Permissions
            try:
                s = item.path.stat()
                perms = stat.filemode(s.st_mode)
                g2.add(Adw.ActionRow(title=tr("Permissions"), subtitle=perms))
            except OSError:
                pass
            page.add(g2)

            # Rename on save
            save = Gtk.Button(label=tr("Renommer"), css_classes=["suggested-action"])
            save.connect("clicked", lambda _: self._rename(parent, item, name_row.get_text()))
            head = Adw.HeaderBar()
            head.pack_end(save)
            view = Adw.ToolbarView(content=page)
            view.add_top_bar(head)
            self.set_child(view)
        else:
            # Multiple items
            total = sum(i.size for i in items if not i.is_dir)
            g = Adw.PreferencesGroup()
            g.add(Adw.ActionRow(title=tr("Éléments"), subtitle=str(len(items))))
            g.add(Adw.ActionRow(title=tr("Taille totale"), subtitle=_human_size(total)))
            page.add(g)
            view = Adw.ToolbarView(content=page)
            view.add_top_bar(Adw.HeaderBar())
            self.set_child(view)

        self.present(parent)

    def _rename(self, parent, item, new_name):
        new_name = new_name.strip()
        if not new_name or new_name == item.name or "/" in new_name:
            return
        dst = item.path.parent / new_name
        try:
            item.path.rename(dst)
        except OSError as e:
            _show_error(parent, tr("Impossible de renommer"), str(e))
        self.close()


def _show_error(parent, title, msg):
    d = Adw.AlertDialog(heading=title, body=msg)
    d.add_response("ok", "OK")
    d.present(parent)


# ─── FileBrowser (un onglet) ─────────────────────────────────────────────────

class FileBrowser(Gtk.Box):
    """Widget principal d'un onglet : vues liste et grille, navigation, opérations."""

    def __init__(self, app, path=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self._history = []
        self._hist_pos = -1
        self._current = None
        self._show_hidden = app.cfg["files"]["show_hidden"]
        self._view_mode = app.cfg["files"]["view"]
        self._single_click = app.cfg["files"]["single_click"]
        self._clipboard = None   # (paths, is_cut)
        self._loading = False
        self._search_text = ""

        # Store + filter + sort
        self._store = Gio.ListStore.new(FileItem)
        self._filter = Gtk.CustomFilter.new(self._filter_func, None)
        self._filter_model = Gtk.FilterListModel(model=self._store, filter=self._filter)
        self._sort_model = Gtk.SortListModel(model=self._filter_model)
        self._selection = Gtk.MultiSelection(model=self._sort_model)

        self._build_toolbar()
        self._build_views()
        self._add_shortcuts()

        self.navigate(path or Path.home(), add_history=False)

    # ---- construction -------------------------------------------------------

    def _build_toolbar(self):
        bar = Gtk.Box(spacing=4, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)

        # Navigation
        self._btn_back = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat"],
                                     tooltip_text=tr("Précédent") + " (Alt+←)", sensitive=False)
        self._btn_fwd = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat"],
                                    tooltip_text=tr("Suivant") + " (Alt+→)", sensitive=False)
        self._btn_up = Gtk.Button(icon_name="go-up-symbolic", css_classes=["flat"],
                                   tooltip_text=tr("Dossier parent") + " (Alt+↑)")
        self._btn_back.connect("clicked", lambda _: self.go_back())
        self._btn_fwd.connect("clicked", lambda _: self.go_forward())
        self._btn_up.connect("clicked", lambda _: self.go_up())
        for b in (self._btn_back, self._btn_fwd, self._btn_up):
            bar.append(b)

        # Fil d'Ariane
        self._breadcrumb = BreadcrumbBar(self.navigate)
        bar.append(self._breadcrumb)

        # Recherche
        self._search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", css_classes=["flat"],
                                             tooltip_text=tr("Rechercher") + " (Ctrl+F)")
        self._search_btn.connect("toggled", self._on_search_toggle)
        bar.append(self._search_btn)

        # Vue
        self._btn_list = Gtk.ToggleButton(icon_name="view-list-symbolic", css_classes=["flat"],
                                           tooltip_text=tr("Vue liste") + " (Ctrl+1)")
        self._btn_grid = Gtk.ToggleButton(icon_name="view-grid-symbolic", css_classes=["flat"],
                                           tooltip_text=tr("Vue grille") + " (Ctrl+2)")
        self._btn_list.set_active(self._view_mode == "list")
        self._btn_grid.set_active(self._view_mode == "grid")
        self._btn_list.connect("toggled", self._on_list_toggled)
        self._btn_grid.connect("toggled", self._on_grid_toggled)
        bar.append(self._btn_list)
        bar.append(self._btn_grid)

        # Menu
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", css_classes=["flat"])
        menu = Gio.Menu()
        menu.append(tr("Nouveau dossier") + "\tCtrl+Maj+N", "browser.new-folder")
        menu.append(tr("Coller") + "\tCtrl+V", "browser.paste")
        s1 = Gio.Menu()
        s1.append(tr("Fichiers cachés") + "\tCtrl+H", "browser.toggle-hidden")
        s1.append(tr("Tout sélectionner") + "\tCtrl+A", "browser.select-all")
        menu.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append(tr("Ouvrir un terminal ici") + "\tCtrl+Alt+T", "browser.open-terminal")
        menu.append_section(None, s2)
        menu_btn.set_menu_model(menu)
        bar.append(menu_btn)

        self.append(bar)

        # Barre de recherche
        self._search_bar = Gtk.SearchBar()
        self._search_entry = Gtk.SearchEntry(hexpand=True, placeholder_text=tr("Chercher…"))
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_bar.set_child(self._search_entry)
        self._search_bar.set_key_capture_widget(self)
        self.append(self._search_bar)

        # Barre de statut
        self._status = Gtk.Label(xalign=0, margin_start=10, margin_end=10,
                                  margin_bottom=4, css_classes=["dim-label", "caption"])
        self.append(self._status)

    def _build_views(self):
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True)

        # Spinner de chargement
        self._spinner = Adw.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._stack.add_named(self._spinner, "loading")

        # Page vide
        empty = Adw.StatusPage(icon_name="folder-symbolic",
                               title=tr("Dossier vide"),
                               description=tr("Pas de fichiers visibles ici"))
        self._stack.add_named(empty, "empty")

        # Vue liste (ColumnView)
        self._col_view = self._build_column_view()
        sw_list = Gtk.ScrolledWindow(child=self._col_view, vexpand=True, has_frame=False)
        self._add_dnd(sw_list)
        self._stack.add_named(sw_list, "list")

        # Vue grille (GridView)
        self._grid_view = self._build_grid_view()
        sw_grid = Gtk.ScrolledWindow(child=self._grid_view, vexpand=True, has_frame=False)
        self._add_dnd(sw_grid)
        self._stack.add_named(sw_grid, "grid")

        self.append(self._stack)
        self._stack.set_visible_child_name(self._view_mode)

        # Clic droit en phase CAPTURE sur le stack — reçoit l'event avant les vues internes
        gc = Gtk.GestureClick(button=3)
        gc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gc.connect("pressed",  self._on_right_pressed)
        gc.connect("released", self._on_right_released)
        self._stack.add_controller(gc)

    def _build_column_view(self):
        cv = Gtk.ColumnView(
            model=self._selection,
            show_row_separators=True,
            show_column_separators=False,
            reorderable=False,
            single_click_activate=self._single_click,
        )
        cv.add_css_class("data-table")
        # Connecte le tri du ColumnView au SortListModel
        self._sort_model.set_sorter(cv.get_sorter())

        # Colonne Nom
        name_factory = Gtk.SignalListItemFactory()
        name_factory.connect("setup", self._col_name_setup)
        name_factory.connect("bind",  self._col_name_bind)
        name_factory.connect("unbind", self._col_name_unbind)
        name_col = Gtk.ColumnViewColumn(title=tr("Nom"), factory=name_factory, expand=True)
        name_col.set_sorter(Gtk.CustomSorter.new(self._cmp_name))
        cv.append_column(name_col)

        # Colonne Taille
        size_factory = Gtk.SignalListItemFactory()
        size_factory.connect("setup", lambda f, i: i.set_child(
            Gtk.Label(xalign=1, width_chars=10, css_classes=["dim-label", "numeric"])))
        size_factory.connect("bind", lambda f, i: i.get_child().set_text(
            "" if i.get_item().is_dir else _human_size(i.get_item().size)))
        size_col = Gtk.ColumnViewColumn(title=tr("Taille"), factory=size_factory)
        size_col.set_sorter(Gtk.CustomSorter.new(self._cmp_size))
        cv.append_column(size_col)

        # Colonne Date
        date_factory = Gtk.SignalListItemFactory()
        date_factory.connect("setup", lambda f, i: i.set_child(
            Gtk.Label(xalign=0, width_chars=16, css_classes=["dim-label"])))
        date_factory.connect("bind", lambda f, i: i.get_child().set_text(
            _human_date(i.get_item().mtime) if i.get_item().mtime else ""))
        date_col = Gtk.ColumnViewColumn(title=tr("Modifié"), factory=date_factory)
        date_col.set_sorter(Gtk.CustomSorter.new(self._cmp_date))
        cv.append_column(date_col)

        # Colonne Type
        type_factory = Gtk.SignalListItemFactory()
        type_factory.connect("setup", lambda f, i: i.set_child(
            Gtk.Label(xalign=0, width_chars=12, css_classes=["dim-label"])))
        type_factory.connect("bind", lambda f, i: i.get_child().set_text(
            _ctype_label(i.get_item().ctype)))
        type_col = Gtk.ColumnViewColumn(title=tr("Type"), factory=type_factory)
        type_col.set_sorter(Gtk.CustomSorter.new(self._cmp_type))
        cv.append_column(type_col)

        cv.connect("activate", self._on_activate)
        return cv

    def _build_grid_view(self):
        gv = Gtk.GridView(
            model=self._selection,
            single_click_activate=self._single_click,
            min_columns=2, max_columns=12,
        )
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup",  self._grid_setup)
        factory.connect("bind",   self._grid_bind)
        factory.connect("unbind", self._grid_unbind)
        gv.set_factory(factory)
        gv.connect("activate", self._on_activate)
        return gv

    # ---- usines de colonnes ColumnView --------------------------------------

    def _col_name_setup(self, factory, list_item):
        box = Gtk.Box(spacing=8, margin_start=4, margin_end=8,
                      margin_top=2, margin_bottom=2)
        box._icon = Gtk.Image(pixel_size=20)
        box._label = Gtk.Label(xalign=0, hexpand=True,
                               ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=50)
        box.append(box._icon)
        box.append(box._label)
        list_item.set_child(box)

    def _col_name_bind(self, factory, list_item):
        item = list_item.get_item()
        box = list_item.get_child()
        box._label.set_text(item.name)
        box._icon.set_from_icon_name(item.icon_name)
        box._pos = list_item.get_position()

    def _col_name_unbind(self, factory, list_item):
        list_item.get_child()._pos = -1

    # ---- usine GridView ─────────────────────────────────────────────────────

    def _grid_setup(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      width_request=108, margin_start=6, margin_end=6,
                      margin_top=8, margin_bottom=8)
        stack = Gtk.Stack(width_request=THUMB_SIZE, height_request=THUMB_SIZE)
        icon = Gtk.Image(pixel_size=64, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        picture = Gtk.Picture(width_request=THUMB_SIZE, height_request=THUMB_SIZE,
                               content_fit=Gtk.ContentFit.CONTAIN,
                               can_shrink=True)
        stack.add_named(icon, "icon")
        stack.add_named(picture, "picture")
        label = Gtk.Label(max_width_chars=12, wrap=True, lines=2,
                          ellipsize=Pango.EllipsizeMode.MIDDLE,
                          justify=Gtk.Justification.CENTER, xalign=0.5)
        box.append(stack)
        box.append(label)
        box._stack = stack
        box._icon = icon
        box._picture = picture
        box._label = label
        list_item.set_child(box)

    def _grid_bind(self, factory, list_item):
        item = list_item.get_item()
        box = list_item.get_child()
        box._pos = list_item.get_position()
        box._label.set_text(item.name)
        # Affiche l'icône ou la vignette
        if item.thumb:
            box._picture.set_filename(item.thumb)
            box._stack.set_visible_child_name("picture")
        else:
            box._icon.set_from_icon_name(item.icon_name)
            box._stack.set_visible_child_name("icon")
            if item.path.suffix.lower() in IMG_EXT:
                self._request_thumb(item, box)

        # Surveille les mises à jour de vignette
        handler = item.connect("notify::thumb", lambda obj, _p, b=box: self._on_thumb_ready(obj, b))
        box._thumb_handler = handler
        box._thumb_item = item

    def _grid_unbind(self, factory, list_item):
        box = list_item.get_child()
        box._pos = -1
        if hasattr(box, "_thumb_handler"):
            box._thumb_item.disconnect(box._thumb_handler)
            del box._thumb_handler, box._thumb_item

    def _request_thumb(self, item, box):
        path = item.path
        def work():
            result = _make_thumb(path)
            if result:
                GLib.idle_add(lambda: setattr(item, "thumb", result) or False)
        _THUMB_POOL.submit(work)

    def _on_thumb_ready(self, item, box):
        if item.thumb:
            box._picture.set_filename(item.thumb)
            box._stack.set_visible_child_name("picture")

    # ---- contrôleurs ────────────────────────────────────────────────────────

    def _on_right_pressed(self, gesture, n, x, y):
        view = gesture.get_widget()
        pos = self._pick_pos(view, x, y)
        if pos >= 0 and not self._selection.is_selected(pos):
            self._selection.select_item(pos, True)

    def _on_right_released(self, gesture, n, x, y):
        view = gesture.get_widget()
        pos = self._pick_pos(view, x, y)
        items = self._get_selected() if pos >= 0 else []
        self._show_context_menu(x, y, items)

    def _pick_pos(self, view, x, y):
        """Retourne la position dans le sort_model de l'item à (x,y), ou -1.
        Cherche _pos sur le widget cible ET dans l'arbre parent (pour les
        colonnes Taille/Date/Type qui partagent le même ColumnViewRow)."""
        start = view.pick(x, y, Gtk.PickFlags.DEFAULT)
        if not start or start is view:
            return -1
        w = start
        while w and w is not view:
            if hasattr(w, "_pos") and w._pos >= 0:
                return w._pos
            parent = w.get_parent()
            if parent and parent is not view:
                pos = self._find_pos_in_subtree(parent, depth=4)
                if pos >= 0:
                    return pos
            w = parent
        return -1

    def _find_pos_in_subtree(self, widget, depth):
        """DFS dans le sous-arbre pour trouver un widget avec _pos."""
        if depth == 0:
            return -1
        if hasattr(widget, "_pos") and widget._pos >= 0:
            return widget._pos
        child = widget.get_first_child()
        while child:
            result = self._find_pos_in_subtree(child, depth - 1)
            if result >= 0:
                return result
            child = child.get_next_sibling()
        return -1

    def _add_shortcuts(self):
        """Raccourcis clavier globaux du FileBrowser."""
        sc = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)

        def add(key, mods, fn):
            trigger = Gtk.KeyvalTrigger(keyval=key, modifiers=mods)
            action = Gtk.CallbackAction.new(lambda *_: fn() or True)
            sc.add_shortcut(Gtk.Shortcut(trigger=trigger, action=action))

        CTRL  = Gdk.ModifierType.CONTROL_MASK
        ALT   = Gdk.ModifierType.ALT_MASK
        SHIFT = Gdk.ModifierType.SHIFT_MASK
        NONE  = Gdk.ModifierType(0)

        # Navigation
        add(Gdk.KEY_BackSpace, NONE, self.go_up)
        add(Gdk.KEY_Left,  ALT, self.go_back)
        add(Gdk.KEY_Right, ALT, self.go_forward)
        add(Gdk.KEY_Up,    ALT, self.go_up)
        # Ouvrir
        add(Gdk.KEY_Return,    NONE, lambda: self._open_items(self._get_selected()) if self._get_selected() else None)
        add(Gdk.KEY_KP_Enter,  NONE, lambda: self._open_items(self._get_selected()) if self._get_selected() else None)
        # Corbeille / suppression définitive
        add(Gdk.KEY_Delete, NONE,  lambda: self._trash_items(self._get_selected()) if self._get_selected() else None)
        add(Gdk.KEY_Delete, SHIFT, lambda: self._perm_delete(self._get_selected()) if self._get_selected() else None)
        # Renommer / propriétés
        add(Gdk.KEY_F2,   NONE, lambda: self._rename_item(self._get_selected()[0]) if len(self._get_selected()) == 1 else None)
        add(Gdk.KEY_F5,   NONE, self._refresh)
        # Presse-papiers
        add(Gdk.KEY_c, CTRL, lambda: self._copy(self._get_selected()))
        add(Gdk.KEY_x, CTRL, lambda: self._cut(self._get_selected()))
        add(Gdk.KEY_v, CTRL, self._paste)
        add(Gdk.KEY_a, CTRL, lambda: self._selection.select_all())
        add(Gdk.KEY_i, CTRL, lambda: PropertiesDialog(self._get_window(), self._get_selected()) if self._get_selected() else None)
        # Affichage / recherche / dossiers
        add(Gdk.KEY_h, CTRL, self.toggle_hidden)
        add(Gdk.KEY_1, CTRL, lambda: self.set_view("list"))
        add(Gdk.KEY_2, CTRL, lambda: self.set_view("grid"))
        add(Gdk.KEY_f, CTRL, self._start_search)
        add(Gdk.KEY_n, CTRL | SHIFT, self.new_folder)
        add(Gdk.KEY_t, CTRL | ALT, self.open_terminal)
        add(Gdk.KEY_t, CTRL, lambda: self._get_window()._new_tab(self._current))

        self.add_controller(sc)

        # Actions pour le menu burger
        ag = Gio.SimpleActionGroup()
        for name, fn in (
            ("new-folder", self.new_folder),
            ("paste", self._paste),
            ("toggle-hidden", self.toggle_hidden),
            ("select-all", lambda: self._selection.select_all()),
            ("open-terminal", self.open_terminal),
        ):
            a = Gio.SimpleAction.new(name)
            a.connect("activate", lambda _a, _p, f=fn: f())
            ag.add_action(a)
        self.insert_action_group("browser", ag)

    # ---- navigation ─────────────────────────────────────────────────────────

    def navigate(self, path, add_history=True):
        path = Path(path).resolve()
        if not path.is_dir():
            return
        if add_history:
            self._history = self._history[:self._hist_pos + 1]
            self._history.append(path)
            self._hist_pos = len(self._history) - 1
        self._current = path
        self._btn_back.set_sensitive(self._hist_pos > 0)
        self._btn_fwd.set_sensitive(self._hist_pos < len(self._history) - 1)
        self._breadcrumb.set_path(path)
        self._load_directory(path)
        # Titre de l'onglet
        win = self._get_window()
        if win:
            page = win._tab_view.get_page(self)
            if page:
                page.set_title(path.name or "/")

    def go_back(self):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            self.navigate(self._history[self._hist_pos], add_history=False)

    def go_forward(self):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self.navigate(self._history[self._hist_pos], add_history=False)

    def go_up(self):
        if self._current and self._current.parent != self._current:
            self.navigate(self._current.parent)

    # ---- chargement du répertoire ───────────────────────────────────────────

    def _load_directory(self, path):
        self._loading = True
        self._stack.set_visible_child_name("loading")
        self._store.remove_all()

        def work():
            items = []
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        try:
                            items.append(FileItem(Path(entry.path)))
                        except Exception:
                            pass
            except PermissionError:
                GLib.idle_add(self._load_error, tr("Accès refusé"))
                return
            GLib.idle_add(self._populate, items)

        threading.Thread(target=work, daemon=True).start()

    def _populate(self, items):
        self._store.splice(0, self._store.get_n_items(), items)
        self._loading = False
        n = self._filter_model.get_n_items()
        if n == 0:
            self._stack.set_visible_child_name("empty")
        else:
            self._stack.set_visible_child_name(self._view_mode)
        self._update_status()
        return False

    def _load_error(self, msg):
        self._stack.set_visible_child_name("empty")
        return False

    def _update_status(self):
        n = self._filter_model.get_n_items()
        total = self._store.get_n_items()
        sel = len(self._get_selected())
        if sel:
            items = self._get_selected()
            sz = sum(i.size for i in items if not i.is_dir)
            self._status.set_text(tr("{n} sélectionné(s)" , n=sel) +
                                  (f" — {_human_size(sz)}" if sz else ""))
        elif total != n:
            self._status.set_text(tr("{n} éléments ({t} en tout)", n=n, t=total))
        else:
            self._status.set_text(tr("{n} éléments", n=n))

    # ---- filtrage et tri ────────────────────────────────────────────────────

    def _filter_func(self, item, _data):
        if not self._show_hidden and item.name.startswith("."):
            return False
        if self._search_text:
            return self._search_text.lower() in item.name.lower()
        return True

    @staticmethod
    def _cmp_name(a, b, _):
        if a.is_dir != b.is_dir:
            return Gtk.Ordering.SMALLER if a.is_dir else Gtk.Ordering.LARGER
        ka, kb = a.name.lower(), b.name.lower()
        if ka < kb: return Gtk.Ordering.SMALLER
        if ka > kb: return Gtk.Ordering.LARGER
        return Gtk.Ordering.EQUAL

    @staticmethod
    def _cmp_size(a, b, _):
        if a.is_dir != b.is_dir:
            return Gtk.Ordering.SMALLER if a.is_dir else Gtk.Ordering.LARGER
        return (Gtk.Ordering.SMALLER if a.size < b.size else
                Gtk.Ordering.LARGER if a.size > b.size else Gtk.Ordering.EQUAL)

    @staticmethod
    def _cmp_date(a, b, _):
        if a.is_dir != b.is_dir:
            return Gtk.Ordering.SMALLER if a.is_dir else Gtk.Ordering.LARGER
        return (Gtk.Ordering.SMALLER if a.mtime < b.mtime else
                Gtk.Ordering.LARGER if a.mtime > b.mtime else Gtk.Ordering.EQUAL)

    @staticmethod
    def _cmp_type(a, b, _):
        if a.is_dir != b.is_dir:
            return Gtk.Ordering.SMALLER if a.is_dir else Gtk.Ordering.LARGER
        ka, kb = a.ctype, b.ctype
        return (Gtk.Ordering.SMALLER if ka < kb else
                Gtk.Ordering.LARGER if ka > kb else Gtk.Ordering.EQUAL)

    # ---- sélection ──────────────────────────────────────────────────────────

    def _get_selected(self):
        bs = self._selection.get_selection()
        items = []
        for i in range(bs.get_size()):
            pos = bs.get_nth(i)
            items.append(self._selection.get_item(pos))
        return items

    # ---- activation (double-clic / Entrée) ──────────────────────────────────

    def _on_activate(self, view, pos):
        item = self._sort_model.get_item(pos)
        if item:
            self._open_items([item])

    def _open_items(self, items):
        for item in items:
            if item.is_dir:
                self.navigate(item.path)
                return
            Gio.AppInfo.launch_default_for_uri(item.path.as_uri(), None)

    # ---- vue ────────────────────────────────────────────────────────────────

    def _on_list_toggled(self, btn):
        if btn.get_active():
            self.set_view("list")

    def _on_grid_toggled(self, btn):
        if btn.get_active():
            self.set_view("grid")

    def set_view(self, mode):
        self._view_mode = mode
        self._btn_list.handler_block_by_func(self._on_list_toggled)
        self._btn_grid.handler_block_by_func(self._on_grid_toggled)
        self._btn_list.set_active(mode == "list")
        self._btn_grid.set_active(mode == "grid")
        self._btn_list.handler_unblock_by_func(self._on_list_toggled)
        self._btn_grid.handler_unblock_by_func(self._on_grid_toggled)
        if not self._loading:
            n = self._filter_model.get_n_items()
            self._stack.set_visible_child_name(mode if n > 0 else "empty")

    def toggle_hidden(self):
        self._show_hidden = not self._show_hidden
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        n = self._filter_model.get_n_items()
        if not self._loading:
            self._stack.set_visible_child_name(self._view_mode if n > 0 else "empty")
        self._update_status()

    # ---- recherche ──────────────────────────────────────────────────────────

    def _on_search_toggle(self, btn):
        self._search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self._search_entry.grab_focus()
        else:
            self._search_text = ""
            self._search_entry.set_text("")
            self._filter.changed(Gtk.FilterChange.LESS_STRICT)

    def _on_search_changed(self, entry):
        self._search_text = entry.get_text().strip()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        n = self._filter_model.get_n_items()
        if not self._loading:
            self._stack.set_visible_child_name(self._view_mode if n > 0 else "empty")
        self._update_status()

    def _start_search(self):
        self._search_btn.set_active(True)

    # ---- opérations sur les fichiers ────────────────────────────────────────

    def new_folder(self):
        dlg = Adw.Dialog(title=tr("Nouveau dossier"), content_width=400)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title=tr("Nom du dossier"), text=tr("Dossier sans nom"))
        g.add(entry)
        page.add(g)
        save = Gtk.Button(label=tr("Créer"), css_classes=["suggested-action"])
        head = Adw.HeaderBar()
        head.pack_end(save)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(head)
        dlg.set_child(view)

        def do_create(*_):
            name = entry.get_text().strip()
            if not name or "/" in name:
                return
            dst = self._current / name
            try:
                dst.mkdir(exist_ok=False)
            except OSError as e:
                _show_error(self._get_window(), tr("Impossible de créer"), str(e))
                return
            dlg.close()
            self._refresh()

        save.connect("clicked", do_create)
        entry.connect("apply", do_create)
        entry.grab_focus()
        dlg.present(self._get_window())

    def _rename_item(self, item):
        dlg = Adw.Dialog(title=tr("Renommer"), content_width=400)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title=tr("Nouveau nom"), text=item.name)
        g.add(entry)
        page.add(g)
        save = Gtk.Button(label=tr("Renommer"), css_classes=["suggested-action"])
        head = Adw.HeaderBar()
        head.pack_end(save)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(head)
        dlg.set_child(view)

        def do_rename(*_):
            new_name = entry.get_text().strip()
            if not new_name or "/" in new_name or new_name == item.name:
                return
            dst = item.path.parent / new_name
            try:
                item.path.rename(dst)
            except OSError as e:
                _show_error(self._get_window(), tr("Impossible de renommer"), str(e))
                return
            dlg.close()
            self._refresh()

        save.connect("clicked", do_rename)
        entry.connect("apply", do_rename)
        entry.grab_focus()
        # Sélectionne le nom sans l'extension pour faciliter la frappe
        stem = Path(item.name).stem
        GLib.idle_add(lambda: (entry.select_region(0, len(stem)), False)[1])
        dlg.present(self._get_window())

    def _copy(self, items):
        if items:
            self._clipboard = ([i.path for i in items], False)

    def _cut(self, items):
        if items:
            self._clipboard = ([i.path for i in items], True)

    def _paste(self):
        if not self._clipboard or not self._current:
            return
        paths, is_cut = self._clipboard
        dst_dir = self._current
        win = self._get_window()

        prog = ProgressDialog(win, tr("Déplacement en cours…") if is_cut else tr("Copie en cours…"))

        def work():
            for i, src in enumerate(paths):
                if prog.cancelled:
                    break
                prog.update(src.name, i / len(paths))
                dst = dst_dir / src.name
                try:
                    if src.is_dir():
                        if is_cut:
                            shutil.move(str(src), str(dst))
                        else:
                            shutil.copytree(str(src), str(dst))
                    else:
                        if is_cut:
                            shutil.move(str(src), str(dst))
                        else:
                            shutil.copy2(str(src), str(dst))
                except (OSError, shutil.Error) as e:
                    GLib.idle_add(_show_error, win, tr("Erreur de copie"), str(e))
                    break
            if is_cut and not prog.cancelled:
                self._clipboard = None
            GLib.idle_add(prog.close)
            GLib.idle_add(self._refresh)

        threading.Thread(target=work, daemon=True).start()

    def _trash_items(self, items):
        n = len(items)
        if n == 1:
            heading = tr("Mettre « {nom} » à la corbeille ?", nom=items[0].name)
        else:
            heading = tr("Mettre {n} éléments à la corbeille ?", n=n)
        d = Adw.AlertDialog(
            heading=heading,
            body=tr("Les fichiers seront déplacés vers la corbeille."),
        )
        d.add_response("non", tr("Annuler"))
        d.add_response("oui", tr("Mettre à la corbeille"))
        d.set_response_appearance("oui", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._do_trash(items) if r == "oui" else None)
        d.present(self._get_window())

    def _do_trash(self, items):
        def work():
            for item in items:
                f = Gio.File.new_for_path(str(item.path))
                try:
                    f.trash(None)
                except GLib.Error as e:
                    GLib.idle_add(_show_error, self._get_window(), tr("Erreur"), str(e))
            GLib.idle_add(self._refresh)
        threading.Thread(target=work, daemon=True).start()

    def _perm_delete(self, items):
        n = len(items)
        if n == 1:
            heading = tr("Supprimer définitivement « {nom} » ?", nom=items[0].name)
        else:
            heading = tr("Supprimer définitivement {n} éléments ?", n=n)
        d = Adw.AlertDialog(
            heading=heading,
            body=tr("Cette action est irréversible. Les fichiers ne seront pas dans la corbeille."),
        )
        d.add_response("non", tr("Annuler"))
        d.add_response("oui", tr("Supprimer définitivement"))
        d.set_response_appearance("oui", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._do_perm_delete(items) if r == "oui" else None)
        d.present(self._get_window())

    def _do_perm_delete(self, items):
        def work():
            for item in items:
                try:
                    if item.is_dir:
                        shutil.rmtree(str(item.path))
                    else:
                        item.path.unlink()
                except OSError as e:
                    GLib.idle_add(_show_error, self._get_window(), tr("Erreur"), str(e))
            GLib.idle_add(self._refresh)
        threading.Thread(target=work, daemon=True).start()

    # ---- archivage ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_archive(item):
        p = item.path
        # Vérifie les doubles extensions (.tar.gz etc.) puis l'extension simple
        for ext in (p.suffix, "".join(p.suffixes[-2:])):
            if ext.lower() in ARCHIVE_EXT:
                return True
        return False

    def _compress_items(self, items):
        """Dialogue de compression → choisir nom + format."""
        # Nom par défaut : nom du 1er item
        default_name = items[0].name if len(items) == 1 else tr("Archive")

        dlg = Adw.Dialog(title=tr("Compresser"), content_width=420)
        page = Adw.PreferencesPage()

        g = Adw.PreferencesGroup()
        name_row = Adw.EntryRow(title=tr("Nom de l'archive"), text=default_name)
        g.add(name_row)

        fmt_row = Adw.ComboRow(title=tr("Format"))
        fmt_model = Gtk.StringList()
        for fmt in ("zip", "tar.gz", "tar.xz", "tar.bz2"):
            fmt_model.append(fmt)
        fmt_row.set_model(fmt_model)
        g.add(fmt_row)
        page.add(g)

        create_btn = Gtk.Button(label=tr("Créer"), css_classes=["suggested-action"])
        head = Adw.HeaderBar()
        head.pack_end(create_btn)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(head)
        dlg.set_child(view)

        def do_compress(*_):
            name = name_row.get_text().strip()
            fmt = fmt_model.get_string(fmt_row.get_selected())
            if not name:
                return
            archive_path = self._current / f"{name}.{fmt}"
            dlg.close()
            prog = ProgressDialog(self._get_window(), tr("Compression en cours…"))

            def work():
                try:
                    paths = [i.path for i in items]
                    if fmt == "zip":
                        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                            for p in paths:
                                if prog.cancelled:
                                    break
                                prog.update(p.name, -1)
                                if p.is_dir():
                                    for f in p.rglob("*"):
                                        zf.write(f, f.relative_to(p.parent))
                                else:
                                    zf.write(p, p.name)
                    else:
                        mode = {"tar.gz": "w:gz", "tar.xz": "w:xz", "tar.bz2": "w:bz2"}[fmt]
                        with tarfile.open(archive_path, mode) as tf:
                            for p in paths:
                                if prog.cancelled:
                                    break
                                prog.update(p.name, -1)
                                tf.add(p, arcname=p.name)
                except Exception as e:
                    GLib.idle_add(_show_error, self._get_window(), tr("Erreur"), str(e))
                    if archive_path.exists():
                        archive_path.unlink()
                GLib.idle_add(prog.close)
                GLib.idle_add(self._refresh)

            threading.Thread(target=work, daemon=True).start()

        create_btn.connect("clicked", do_compress)
        name_row.connect("apply", do_compress)
        name_row.grab_focus()
        dlg.present(self._get_window())

    def _extract_items(self, items):
        """Extrait chaque archive dans un sous-dossier du même nom."""
        win = self._get_window()
        prog = ProgressDialog(win, tr("Extraction en cours…"))

        def work():
            for item in items:
                if prog.cancelled:
                    break
                prog.update(item.name, -1)
                p = item.path
                # Dossier de destination : même nom sans extension(s)
                stem = p.name
                for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tgz", ".tbz2", ".txz"):
                    if stem.lower().endswith(ext):
                        stem = stem[: -len(ext)]
                        break
                else:
                    stem = Path(stem).stem
                dst = p.parent / stem
                dst.mkdir(exist_ok=True)
                try:
                    suf = "".join(p.suffixes[-2:]).lower()
                    ext1 = p.suffix.lower()
                    if ext1 == ".zip":
                        with zipfile.ZipFile(p) as zf:
                            zf.extractall(dst)
                    elif tarfile.is_tarfile(p):
                        with tarfile.open(p) as tf:
                            tf.extractall(dst)
                    elif ext1 in (".7z",):
                        subprocess.run(["7z", "x", str(p), f"-o{dst}", "-y"],
                                       check=True, capture_output=True)
                    elif ext1 in (".rar",):
                        subprocess.run(["unrar", "x", "-y", str(p), str(dst) + "/"],
                                       check=True, capture_output=True)
                    elif ext1 in (".gz", ".bz2", ".xz"):
                        import gzip, bz2, lzma
                        openers = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}
                        out_path = dst / Path(p.name).stem
                        with openers[ext1](p, "rb") as fi, open(out_path, "wb") as fo:
                            shutil.copyfileobj(fi, fo)
                    else:
                        GLib.idle_add(_show_error, win, tr("Format non supporté"), p.name)
                except Exception as e:
                    GLib.idle_add(_show_error, win, tr("Erreur d'extraction"), str(e))
            GLib.idle_add(prog.close)
            GLib.idle_add(self._refresh)

        threading.Thread(target=work, daemon=True).start()

    def open_terminal(self):
        if not self._current:
            return
        cfg = core.load()
        term = cfg.get("files", {}).get("terminal", "kitty")
        subprocess.Popen([term], cwd=str(self._current), start_new_session=True)

    def _open_with_dialog(self, items):
        if not items:
            return
        item = items[0]
        apps = Gio.AppInfo.get_all_for_type(item.ctype)
        if not apps:
            apps = Gio.AppInfo.get_all()[:20]

        dlg = Adw.Dialog(title=tr("Ouvrir avec"), content_width=380)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=item.name)
        for app_info in apps[:20]:
            row = Adw.ActionRow(title=app_info.get_display_name(),
                                activatable=True)
            if app_info.get_icon():
                row.add_prefix(Gtk.Image.new_from_gicon(app_info.get_icon()))
            def on_activated(_row, ai=app_info, it=item):
                try:
                    ai.launch([Gio.File.new_for_path(str(it.path))], None)
                except GLib.Error as e:
                    pass
                dlg.close()
            row.connect("activated", on_activated)
            g.add(row)
        page.add(g)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        dlg.set_child(view)
        dlg.present(self._get_window())

    # ---- menu contextuel ────────────────────────────────────────────────────

    def _show_context_menu(self, x, y, items):
        popover = Gtk.Popover(has_arrow=False, halign=Gtk.Align.START)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=4, margin_bottom=4,
                      margin_start=4, margin_end=4, spacing=0)

        def add_item(label, fn, destructive=False):
            css = ["flat"] + (["destructive-action"] if destructive else [])
            btn = Gtk.Button(css_classes=css, hexpand=True)
            lbl = Gtk.Label(label=label, xalign=0, hexpand=True)
            btn.set_child(lbl)
            btn.connect("clicked", lambda _: (fn(), popover.popdown()))
            box.append(btn)

        def sep():
            box.append(Gtk.Separator(margin_top=4, margin_bottom=4))

        if items:
            if len(items) == 1 and items[0].is_dir:
                add_item(tr("Ouvrir"), lambda: self._open_items(items))
                add_item(tr("Ouvrir dans un nouvel onglet"),
                         lambda: self._get_window()._new_tab(items[0].path))
            elif len(items) == 1:
                add_item(tr("Ouvrir"), lambda: self._open_items(items))
                add_item(tr("Ouvrir avec…"), lambda: self._open_with_dialog(items))
            else:
                add_item(tr("Ouvrir"), lambda: self._open_items(items))

            sep()
            add_item(tr("Copier") + "\tCtrl+C", lambda: self._copy(items))
            add_item(tr("Couper") + "\tCtrl+X", lambda: self._cut(items))

            if len(items) == 1:
                sep()
                add_item(tr("Renommer") + "\tF2", lambda: self._rename_item(items[0]))

            # Archivage
            archives = [i for i in items if self._is_archive(i)]
            sep()
            if archives:
                add_item(tr("Extraire ici"), lambda: self._extract_items(archives))
            add_item(tr("Compresser…"), lambda: self._compress_items(items))

            sep()
            add_item(tr("Propriétés") + "\tCtrl+I",
                     lambda: PropertiesDialog(self._get_window(), items))
            sep()
            add_item(tr("Mettre à la corbeille") + "\tSuppr",
                     lambda: self._trash_items(items), destructive=True)
        else:
            add_item(tr("Coller") + "\tCtrl+V", self._paste,
                     ) if self._clipboard else None
            add_item(tr("Nouveau dossier") + "\tCtrl+Maj+N", self.new_folder)
            add_item(tr("Ouvrir un terminal ici"), self.open_terminal)
            sep()
            add_item(tr("Tout sélectionner") + "\tCtrl+A",
                     lambda: self._selection.select_all())

        popover.set_child(box)
        popover.set_parent(self._stack)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    # ---- glisser-déposer ────────────────────────────────────────────────────

    def _add_dnd(self, scroll_win):
        # Source (glisser depuis la vue)
        drag_src = Gtk.DragSource()
        drag_src.set_actions(Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drag_src.connect("prepare", self._on_drag_prepare)
        scroll_win.add_controller(drag_src)

        # Cible (déposer dans la vue)
        drop_tgt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop_tgt.connect("drop", self._on_drop)
        scroll_win.add_controller(drop_tgt)

    def _on_drag_prepare(self, source, x, y):
        items = self._get_selected()
        if not items:
            return None
        gfiles = [Gio.File.new_for_path(str(i.path)) for i in items]
        flist = Gdk.FileList.new_from_array(gfiles)
        return Gdk.ContentProvider.new_for_value(flist)

    def _on_drop(self, target, value, x, y):
        if not isinstance(value, Gdk.FileList):
            return False
        gfiles = value.get_files()
        paths = [Path(gf.get_path()) for gf in gfiles if gf.get_path()]
        if not paths or not self._current:
            return False
        self._clipboard = (paths, False)
        self._paste()
        return True

    # ---- utilitaires ────────────────────────────────────────────────────────

    def _refresh(self):
        if self._current:
            self._load_directory(self._current)
        return False

    def _get_window(self):
        parent = self.get_root()
        return parent if isinstance(parent, FichiersWindow) else None


# ─── Barre latérale ──────────────────────────────────────────────────────────

class Sidebar(Gtk.Box):
    def __init__(self, on_navigate):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._navigate = on_navigate
        self._vol_rows = {}

        lb = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.SINGLE)
        lb.connect("row-activated", self._on_row)

        # En-tête section dossiers
        lb.set_header_func(self._header_func)

        self._rows = {}
        self._sections = {}
        bookmarks_header = "bookmarks"
        devices_header = "devices"

        # Marque-pages
        for i, (name, path, icon) in enumerate(BOOKMARKS):
            if not path.is_dir():
                continue
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=10, margin_start=12, margin_top=3, margin_bottom=3)
            box.append(Gtk.Image(icon_name=icon, pixel_size=16))
            box.append(Gtk.Label(label=tr(name), xalign=0, hexpand=True))
            row.set_child(box)
            row._path = path
            row._section = bookmarks_header if i == 0 else None
            if i == 0:
                self._sections[row] = tr("Dossiers")
            lb.append(row)
            self._rows[str(path)] = row

        # Disques (GVolumeMonitor)
        self._lb = lb
        self._devices_first_row = None
        self._refresh_drives()

        vm = Gio.VolumeMonitor.get()
        vm.connect("mount-added",   lambda _v, m: GLib.idle_add(self._refresh_drives))
        vm.connect("mount-removed", lambda _v, m: GLib.idle_add(self._refresh_drives))

        sw = Gtk.ScrolledWindow(child=lb, vexpand=True, has_frame=False,
                                hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(sw)

    def _header_func(self, row, before):
        sec = self._sections.get(row)
        row.set_header(
            Gtk.Label(label=sec, xalign=0, css_classes=["heading", "dim-label"],
                      margin_start=12, margin_top=14, margin_bottom=4)
            if sec else None
        )

    def _on_row(self, lb, row):
        if hasattr(row, "_path"):
            self._navigate(row._path)

    def _refresh_drives(self):
        # Supprime les anciennes lignes de disques
        for row in list(self._vol_rows.values()):
            self._lb.remove(row)
        self._vol_rows = {}
        if self._devices_first_row:
            self._sections.pop(self._devices_first_row, None)
            self._devices_first_row = None

        vm = Gio.VolumeMonitor.get()
        first = True
        for mount in vm.get_mounts():
            root = mount.get_root()
            if not root:
                continue
            path = root.get_path()
            if not path:
                continue
            path = Path(path)
            # Exclut / et ~
            if path == Path("/") or path == Path.home():
                continue
            icon_names = ["drive-removable-media-symbolic"]
            g_icon = mount.get_icon()
            if g_icon:
                icon_names = Gio.ThemedIcon.new_from_names(icon_names)

            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=10, margin_start=12, margin_top=3, margin_bottom=3)
            box.append(Gtk.Image(icon_name="drive-removable-media-symbolic", pixel_size=16))
            lbl = Gtk.Label(label=mount.get_name(), xalign=0, hexpand=True)
            box.append(lbl)

            # Bouton éjecter
            eject_btn = Gtk.Button(icon_name="media-eject-symbolic",
                                   css_classes=["flat", "circular"],
                                   valign=Gtk.Align.CENTER)
            eject_btn.connect("clicked", lambda _b, m=mount: self._eject(m))
            box.append(eject_btn)

            row.set_child(box)
            row._path = path
            if first:
                self._sections[row] = tr("Appareils")
                self._devices_first_row = row
                first = False
            self._lb.append(row)
            self._vol_rows[str(path)] = row

        self._lb.invalidate_headers()

    def _eject(self, mount):
        mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, None, None, None)

    def highlight(self, path):
        path_str = str(path)
        for str_p, row in {**self._rows, **self._vol_rows}.items():
            if path_str == str_p or path_str.startswith(str_p + "/"):
                self._lb.select_row(row)
                return
        self._lb.select_row(None)


# ─── Fenêtre principale ───────────────────────────────────────────────────────

class FichiersWindow(Adw.ApplicationWindow):
    def __init__(self, app, start_path=None):
        super().__init__(application=app, title=tr("Fichiers"),
                         default_width=1200, default_height=720)
        self._app = app
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._build_layout()
        self.restyle()
        self._watch_theme()

        path = start_path or Path.home()
        self._new_tab(path)
        self.present()

    def _build_layout(self):
        # Barre onglets + zone principale
        self._tab_view = Adw.TabView()
        self._tab_bar = Adw.TabBar(view=self._tab_view, expand_tabs=False)
        self._tab_view.connect("page-attached", self._on_tab_attached)
        self._tab_view.connect("close-page", self._on_close_page)
        self._tab_view.connect("notify::selected-page", self._on_tab_switched)

        # Bouton nouvel onglet dans la barre des onglets
        new_tab_btn = Gtk.Button(icon_name="tab-new-symbolic", css_classes=["flat"],
                                  tooltip_text=tr("Nouvel onglet") + " (Ctrl+T)",
                                  valign=Gtk.Align.CENTER)
        new_tab_btn.connect("clicked", lambda _: self._new_tab())
        self._tab_bar.set_end_action_widget(new_tab_btn)

        self._sidebar = Sidebar(self._navigate_active)

        # Paned horizontal (barre latérale gauche)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                          wide_handle=False, position=200)
        paned.set_start_child(self._sidebar)
        paned.set_end_child(self._tab_view)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)

        # Mise en page principale : header + tab_bar + paned
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._tab_bar)
        outer.append(paned)

        # Fenêtre : headerbar commune en haut
        toolbar_view = Adw.ToolbarView(content=outer)
        toolbar_view.add_top_bar(self._build_header())
        self.set_content(toolbar_view)

        # Raccourcis globaux (onglets)
        sc = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        CTRL = Gdk.ModifierType.CONTROL_MASK
        SHIFT = Gdk.ModifierType.SHIFT_MASK

        def add(key, mods, fn):
            sc.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.KeyvalTrigger(keyval=key, modifiers=mods),
                action=Gtk.CallbackAction.new(lambda *_: fn() or True)
            ))
        add(Gdk.KEY_t, CTRL, lambda: self._new_tab())
        add(Gdk.KEY_w, CTRL, self._close_current_tab)
        add(Gdk.KEY_Tab, CTRL, self._next_tab)
        add(Gdk.KEY_Tab, CTRL | SHIFT, self._prev_tab)
        self.add_controller(sc)

    def _build_header(self):
        hb = Adw.HeaderBar()
        # Bouton fermer onglet (apparaît seulement quand plusieurs onglets)
        self._close_tab_btn = Gtk.Button(icon_name="window-close-symbolic",
                                          css_classes=["flat"],
                                          tooltip_text=tr("Fermer l'onglet") + " (Ctrl+W)")
        self._close_tab_btn.connect("clicked", lambda _: self._close_current_tab())
        hb.pack_end(self._close_tab_btn)
        return hb

    # ---- onglets ─────────────────────────────────────────────────────────────

    def _new_tab(self, path=None):
        browser = FileBrowser(self._app, path)
        page = self._tab_view.append(browser)
        page.set_title((path or Path.home()).name or "/")
        page.set_icon(Gio.ThemedIcon.new("folder-symbolic"))
        self._tab_view.set_selected_page(page)
        return browser

    def _on_tab_attached(self, tab_view, page, pos):
        self._close_tab_btn.set_sensitive(tab_view.get_n_pages() > 1)

    def _on_close_page(self, tab_view, page):
        tab_view.close_page_finish(page, True)
        if tab_view.get_n_pages() == 0:
            self._new_tab()
        self._close_tab_btn.set_sensitive(tab_view.get_n_pages() > 1)
        return True

    def _on_tab_switched(self, tab_view, _param):
        browser = self._active_browser()
        if browser and browser._current:
            self._sidebar.highlight(browser._current)

    def _close_current_tab(self):
        page = self._tab_view.get_selected_page()
        if page:
            self._tab_view.close_page(page)

    def _next_tab(self):
        self._tab_view.select_next_page()

    def _prev_tab(self):
        self._tab_view.select_previous_page()

    def _active_browser(self):
        page = self._tab_view.get_selected_page()
        return page.get_child() if page else None

    def _navigate_active(self, path):
        b = self._active_browser()
        if b:
            b.navigate(path)

    # ---- thème ───────────────────────────────────────────────────────────────

    def restyle(self):
        cfg = core.load()
        self._app.cfg = cfg
        p = core.palette(cfg)
        css = f""":root {{
  --accent-bg-color: {p['accent']}; --accent-color: {core.mix(p['accent'], '#ffffff', 0.15)};
  --accent-fg-color: {p['on_accent']};
  --window-bg-color: {p['bg']}; --view-bg-color: {p['bg']};
  --headerbar-bg-color: {p['bg']}; --sidebar-bg-color: {p['surface']};
  --card-bg-color: {core.css_rgba(p['surface'], 1)}; --popover-bg-color: {p['elevated']};
  --dialog-bg-color: {p['elevated']};
}}
.navigation-sidebar {{ background: {p['surface']}; }}
.navigation-sidebar row:selected {{ background: {core.css_rgba(p['accent'], 0.18)}; }}
"""
        self._css.load_from_string(css)

    def _watch_theme(self):
        gfile = Gio.File.new_for_path(str(_STUDIO_CFG))
        self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", lambda *_: GLib.idle_add(self.restyle))


# ─── Application ─────────────────────────────────────────────────────────────

class Fichiers(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = core.load()

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        path = Path(args[0]).expanduser() if args else None
        self.activate_with_path(path)
        return 0

    def do_open(self, files, n_files, hint):
        path = Path(files[0].get_path()) if files else None
        self.activate_with_path(path)

    def activate_with_path(self, path=None):
        # Réutilise la fenêtre existante si déjà ouverte
        win = self.get_active_window()
        if win:
            if path:
                win._navigate_active(path)
            win.present()
        else:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            FichiersWindow(self, path)

    def do_activate(self):
        self.activate_with_path()


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(Fichiers().run(_sys.argv))
