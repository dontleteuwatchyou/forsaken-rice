"""Studio — fenêtre de réglage du bureau (GTK4 + libadwaita). Tout s'applique en direct."""
import hashlib
import os
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import audio  # noqa: E402
import bots  # noqa: E402
import core  # noqa: E402
from i18n import LANGS, tr  # noqa: E402
from pages_systeme import SystemPages  # noqa: E402
import ram  # noqa: E402

THUMBS = Path.home() / ".cache" / "studio" / "thumbs"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def thumb(path):
    """Vignette 320 px en cache (les fonds font souvent 8K)."""
    from PIL import Image
    p = Path(path)
    key = hashlib.sha1(f"{p}{p.stat().st_mtime}".encode()).hexdigest()[:16]
    out = THUMBS / f"{key}.png"
    if not out.exists():
        THUMBS.mkdir(parents=True, exist_ok=True)
        im = Image.open(p)
        im.thumbnail((320, 180))
        im.convert("RGB").save(out)
    return str(out)


class Studio(Adw.Application, SystemPages):
    def __init__(self):
        super().__init__(application_id="fr.forsaken.Studio",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = core.load()
        self.win = None
        self._pending = 0
        self._css = Gtk.CssProvider()

    # ------------------------------------------------------------ cycle de vie
    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        page = args[args.index("--page") + 1] if "--page" in args and len(args) > args.index("--page") + 1 else None
        self.activate()
        if page in getattr(self, "nav_rows", {}):
            self.nav.select_row(self.nav_rows[page])
        return 0

    def do_activate(self):
        if self.win:
            self.win.present()
            return
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = Adw.ApplicationWindow(application=self, title="Studio", default_width=1120, default_height=800)
        self.stack = Adw.ViewStack()
        sections = [
            ("Général", [
                ("general", "Langue", "preferences-desktop-locale-symbolic", self.page_general),
            ]),
            ("Apparence", [
                ("couleurs", "Couleurs", "applications-graphics-symbolic", self.page_couleurs),
                ("fenetres", "Fenêtres", "view-dual-symbolic", self.page_fenetres),
                ("barre", "Barre", "view-continuous-symbolic", self.page_barre),
                ("fond", "Fond d'écran", "image-x-generic-symbolic", self.page_fond),
                ("terminal", "Terminal", "utilities-terminal-symbolic", self.page_terminal),
            ]),
            ("Système", [
                ("ecrans", "Écrans", "video-display-symbolic", self.page_ecrans),
                ("son", "Son", "audio-volume-high-symbolic", self.page_son),
                ("clavier", "Clavier et souris", "input-keyboard-symbolic", self.page_clavier),
                ("applis", "Applis par défaut", "starred-symbolic", self.page_applis),
                ("demarrage", "Démarrage", "system-run-symbolic", self.page_demarrage),
                ("raccourcis", "Raccourcis", "preferences-desktop-keyboard-shortcuts-symbolic", self.page_raccourcis),
                ("veille", "Veille et verrouillage", "system-lock-screen-symbolic", self.page_veille),
            ]),
            ("Outils", [
                ("bots", "Bots", "application-x-executable-symbolic", self.page_bots),
                ("ram", "Mémoire", "drive-harddisk-solidstate-symbolic", self.page_ram),
                ("fichiers", "Fichiers", "system-file-manager-symbolic", self.page_fichiers),
            ]),
        ]
        self.nav = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.nav_rows, titles, first_of = {}, {}, {}
        for sec, pages in sections:
            for i, (name, title, icon, build) in enumerate(pages):
                self.stack.add_named(build(), name)
                box = Gtk.Box(spacing=12, margin_top=2, margin_bottom=2)
                box.append(Gtk.Image(icon_name=icon))
                box.append(Gtk.Label(label=tr(title), xalign=0))
                row = Gtk.ListBoxRow(child=box)
                row._page = name
                if i == 0:
                    first_of[row] = sec
                self.nav.append(row)
                self.nav_rows[name] = row
                titles[name] = tr(title)

        def header(row, _before):
            sec = first_of.get(row)
            row.set_header(Gtk.Label(label=tr(sec), xalign=0, css_classes=["heading", "dim-label"],
                                     margin_start=12, margin_top=14, margin_bottom=4) if sec else None)

        self.nav.set_header_func(header)
        self.content_page = Adw.NavigationPage(title="Studio")

        def go(_lb, row):
            if row:
                self.stack.set_visible_child_name(row._page)
                self.content_page.set_title(titles[row._page])

        self.nav.connect("row-selected", go)
        side_view = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.nav, vexpand=True))
        side_view.add_top_bar(Adw.HeaderBar(show_title=True))
        sidebar = Adw.NavigationPage(title="Studio", child=side_view)
        content_view = Adw.ToolbarView(content=self.stack)
        content_view.add_top_bar(Adw.HeaderBar())
        self.content_page.set_child(content_view)
        split = Adw.NavigationSplitView(sidebar=sidebar, content=self.content_page,
                                        min_sidebar_width=230, max_sidebar_width=260)
        self.toasts = Adw.ToastOverlay(child=split)
        self.win.set_content(self.toasts)
        self.nav.select_row(self.nav_rows["couleurs"])
        self.restyle()
        self.win.present()
        GLib.timeout_add_seconds(3, self.tick)

    # ------------------------------------------------------------ état
    def get(self, path):
        v = self.cfg
        for k in path:
            v = v[k]
        return v

    def set(self, path, value):
        d = self.cfg
        for k in path[:-1]:
            d = d[k]
        if d[path[-1]] == value:
            return
        d[path[-1]] = value
        self.schedule()

    def schedule(self):
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(250, self.commit)

    def commit(self):
        self._pending = 0
        core.save(self.cfg)
        self.restyle()
        cfg = core.copy.deepcopy(self.cfg)
        def work():
            core.apply(cfg)
            GLib.idle_add(self.refresh_preview)

        threading.Thread(target=work, daemon=True).start()
        return False

    def restyle(self):
        """La fenêtre du Studio prend elle-même les couleurs du thème."""
        p = core.palette(self.cfg)
        css = f""":root {{
  --accent-bg-color: {p['accent']}; --accent-color: {core.mix(p['accent'], '#ffffff', 0.15)};
  --accent-fg-color: {p['on_accent']};
  --window-bg-color: {p['bg']}; --view-bg-color: {p['bg']};
  --headerbar-bg-color: {p['bg']}; --sidebar-bg-color: {p['surface']};
  --card-bg-color: {core.css_rgba(p['surface'], 1)}; --popover-bg-color: {p['elevated']};
  --dialog-bg-color: {p['elevated']};
}}
.swatch {{ min-width: 116px; min-height: 64px; border-radius: 14px; padding: 0; }}
.swatch label {{ font-weight: 700; text-shadow: 0 1px 3px rgba(0,0,0,.6); color: white; }}
.swatch.selected {{ box-shadow: 0 0 0 3px {p['text']}; }}
.wall {{ border-radius: 12px; padding: 0; }}
.wall picture {{ border-radius: 12px; }}
.wall.selected {{ box-shadow: 0 0 0 3px {p['accent']}; }}
.wallprev {{ border-radius: 14px; }}
.sidebar-pane, .sidebar-pane headerbar, .navigation-sidebar {{ background: {p['surface']}; }}
.navigation-sidebar row:selected {{ background: {core.css_rgba(p['accent'], 0.18)}; }}
.bigram {{ font-size: 30px; font-weight: 800; }}
.keycap {{ font-family: "{self.cfg['mono']}"; font-weight: 700; padding: 3px 9px; border-radius: 8px;
          background: {core.css_rgba(p['accent'], 0.14)}; color: {core.mix(p['accent'], '#ffffff', 0.35)};
          box-shadow: inset 0 0 0 1px {core.css_rgba(p['accent'], 0.35)}; }}
"""
        for k, v in core.PRESETS.items():
            css += f".preset-{k} {{ background: linear-gradient(135deg, {v['accent']}, {v['accent2']} 60%, {v['bg']}); }}\n"
        self._css.load_from_string(css)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=tr(text), timeout=2))

    # ------------------------------------------------------------ fabriques de lignes
    def spin(self, group, title, path, lo, hi, step=1, digits=0, subtitle=None):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(tr(title))
        row.set_digits(digits)
        if subtitle:
            row.set_subtitle(tr(subtitle))
        row.set_value(self.get(path))
        row.connect("notify::value", lambda r, _: self.set(path, round(r.get_value(), digits) if digits else int(r.get_value())))
        group.add(row)
        return row

    def switch(self, group, title, path, subtitle=None):
        row = Adw.SwitchRow(title=tr(title), active=self.get(path))
        if subtitle:
            row.set_subtitle(tr(subtitle))
        row.connect("notify::active", lambda r, _: self.set(path, r.get_active()))
        group.add(row)
        return row

    def combo(self, group, title, path, options):
        keys, labels = list(options), [tr(v) for v in options.values()]
        row = Adw.ComboRow(title=tr(title), model=Gtk.StringList.new(labels))
        row.set_selected(keys.index(self.get(path)) if self.get(path) in keys else 0)
        row.connect("notify::selected", lambda r, _: self.set(path, keys[r.get_selected()]))
        group.add(row)
        return row

    def color(self, group, title, key, subtitle=None):
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg[key])
        btn.set_rgba(rgba)

        def changed(b, _):
            c = b.get_rgba()
            self.cfg["preset"] = "perso"
            self.set((key,), core.hexc((c.red * 255, c.green * 255, c.blue * 255)))
            self.mark_preset()

        btn.connect("notify::rgba", changed)
        row = Adw.ActionRow(title=tr(title), subtitle=tr(subtitle) if subtitle else "")
        row.add_suffix(btn)
        row.set_activatable_widget(btn)
        group.add(row)
        self.color_btns[key] = btn
        return row

    # ------------------------------------------------------------ pages
    def page_couleurs(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Thèmes"), description=tr("Un clic applique tout le bureau."))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8,
                           min_children_per_line=2, row_spacing=10, column_spacing=10, homogeneous=True)
        self.swatches = {}
        for k, v in core.PRESETS.items():
            b = Gtk.Button(child=Gtk.Label(label=tr(v["label"])), css_classes=["swatch", f"preset-{k}"])
            b.connect("clicked", lambda _b, key=k: self.pick_preset(key))
            self.swatches[k] = b
            flow.append(b)
        g.add(flow)
        page.add(g)

        self.color_btns = {}
        g = Adw.PreferencesGroup(title=tr("Couleurs perso"))
        self.color(g, "Accent", "accent", "Bordure active, espaces de travail, curseur…")
        self.color(g, "Accent 2", "accent2", "Second ton du dégradé")
        self.color(g, "Fond", "bg", "Barre, menus, terminal")
        row = Adw.SpinRow.new_with_range(0, 1, 0.05)
        row.set_title(tr("Teinte des surfaces"))
        row.set_subtitle(tr("0 = gris neutre, 1 = surfaces teintées par l'accent"))
        row.set_digits(2)
        row.set_value(self.cfg["tint"])
        row.connect("notify::value", lambda r, _: self.set(("tint",), round(r.get_value(), 2)))
        self.tint_row = row
        g.add(row)
        wall = Adw.ButtonRow(title=tr("Prendre les couleurs du fond d'écran"), start_icon_name="color-select-symbolic")
        wall.connect("activated", lambda *_: self.colors_from_wallpaper())
        g.add(wall)
        page.add(g)

        g = Adw.PreferencesGroup(title=tr("Texte"))
        fonts = {"Inter": "Inter", "Fira Sans": "Fira Sans", "JetBrainsMono Nerd Font": "JetBrains Mono"}
        self.combo(g, "Police de l'interface", ("font",), fonts)
        self.spin(g, "Taille", ("font_size",), 10, 18)
        self.spin(g, "Opacité du terminal", ("term_opacity",), 0.5, 1, 0.02, 2)
        page.add(g)
        self.mark_preset()
        return page

    def mark_preset(self):
        for k, b in self.swatches.items():
            (b.add_css_class if k == self.cfg["preset"] else b.remove_css_class)("selected")

    def pick_preset(self, key):
        pr = core.PRESETS[key]
        for k in ("accent", "accent2", "bg"):
            self.cfg[k] = pr[k]
            c = Gdk.RGBA()
            c.parse(pr[k])
            self.color_btns[k].set_rgba(c)
        self.cfg["preset"] = key  # set_rgba ci-dessus repasse en « perso »
        self.cfg["tint"] = pr["tint"]
        self.tint_row.set_value(pr["tint"])
        self.mark_preset()
        self.schedule()

    def colors_from_wallpaper(self):
        if not self.cfg["wallpaper"]:
            self.toast("Choisis d'abord un fond d'écran")
            return
        a, a2, bg = core.accent_from_image(self.cfg["wallpaper"])
        for k, v in (("accent", a), ("accent2", a2), ("bg", bg)):
            c = Gdk.RGBA()
            c.parse(v)
            self.color_btns[k].set_rgba(c)
        self.toast("Couleurs prises sur le fond")

    # ------------------------------------------------------------ général
    def page_general(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Langue"),
                                 description=tr("Change tous les textes du bureau : Studio, barre, menus, notifications, "
                                                "écran de verrouillage et terminal. Studio redémarre pour l'appliquer."))
        codes = list(LANGS)
        row = Adw.ComboRow(title=tr("Langue"), model=Gtk.StringList.new(list(LANGS.values())))
        row.set_selected(codes.index(self.cfg.get("lang", "fr")) if self.cfg.get("lang") in codes else 0)
        row.connect("notify::selected", lambda r, _: self.set_lang(codes[r.get_selected()]))
        g.add(row)
        page.add(g)
        return page

    def set_lang(self, code):
        if code == self.cfg.get("lang", "fr"):
            return
        self.cfg["lang"] = code
        core.save(self.cfg)
        cfg = core.copy.deepcopy(self.cfg)

        def work():
            core.set_lang(code)             # les fichiers générés (barre, menus…) passent dans la nouvelle langue
            core.apply(cfg)
            GLib.idle_add(self.restart)

        threading.Thread(target=work, daemon=True).start()

    def restart(self):
        """Relance Studio pour reconstruire toute l'interface dans la nouvelle langue."""
        page = self.stack.get_visible_child_name() or "general"
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "--page", page])

    # ------------------------------------------------------------ terminal
    def page_terminal(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(
            title=tr("Animation"),
            description=tr("En boucle : kitty s'ouvre coupé en deux, l'animation tourne sans fin dans un panneau en haut, "
                           "séparé de ton shell par une barre. Seulement à l'ouverture : elle joue quelques secondes "
                           "au-dessus du premier prompt, puis s'arrête. Image fixe : pareil, sans mouvement."))
        anim = self.combo(g, "Animation", ("term", "anim"), core.TERM_ANIMS)
        mode = self.combo(g, "Affichage", ("term", "mode"), core.TERM_MODES)
        panel = self.spin(g, "Hauteur du panneau", ("term", "panel"), 15, 50, 5,
                          subtitle="En % de la fenêtre (affichage en boucle)")
        self.spin(g, "Vitesse", ("term", "speed"), 0.3, 3, 0.1, 1, subtitle="1 = normale")
        self.spin(g, "Taille des personnages", ("term", "size"), 0.6, 1.6, 0.1, 1,
                  subtitle="Araignée, corbeau, chauves-souris, forme 3D… 1 = normale")
        self.spin(g, "Fluidité", ("term", "fps"), 10, 30, 5,
                  subtitle="Images par seconde : plus = plus fluide, mais un peu plus de processeur")
        page.add(g)

        rnd = Adw.PreferencesGroup(title=tr("Aléatoire"),
                                   description=tr("Choisis « Aléatoire » comme animation : chaque nouveau terminal en tire "
                                                  "une au hasard parmi celles cochées ici, jamais deux fois la même de suite."))
        every = self.spin(rnd, "Changer d'animation toutes les", ("term", "random_every"), 0, 60, 1,
                          subtitle="En minutes, dans le panneau en boucle — 0 = jamais")
        for key, label in core._anims.LABELS.items():
            self.switch(rnd, label, ("term", "random", key))
        page.add(rnd)

        def sync(*_):
            panel.set_sensitive(self.cfg["term"]["mode"] == "boucle")
            rnd.set_sensitive(self.cfg["term"]["anim"] == "aleatoire")
            every.set_sensitive(self.cfg["term"]["mode"] == "boucle")
        for row in (mode, anim):
            row.connect("notify::selected", lambda *_: GLib.idle_add(sync))
        sync()

        # réglages propres à chaque animation (déclarés dans animations.py)
        g = Adw.PreferencesGroup(title=tr("Réglages de chaque animation"))
        for key, (cls, label) in core._anims.ANIMS.items():
            opts = getattr(cls, "OPTIONS", [])
            if not opts:
                continue
            exp = Adw.ExpanderRow(title=tr(label))
            rows = type("Lignes", (), {"add": staticmethod(exp.add_row)})   # les fabriques de lignes appellent .add
            for okey, olabel, kind, _default, extra in opts:
                path = ("term", "opts", key, okey)
                if kind == "choice":
                    self.combo(rows, olabel, path, extra)
                elif kind == "bool":
                    self.switch(rows, olabel, path)
                else:
                    lo, hi, step, digits = extra
                    self.spin(rows, olabel, path, lo, hi, step, digits)
            g.add(exp)
        page.add(g)

        g = Adw.PreferencesGroup(title=tr("Infos à côté de l'animation"),
                                 description=tr("Couleur des icônes : l'accent du thème. La toile, elle, reste grise."))
        for key, label in core.TERM_INFOS.items():
            self.switch(g, label, ("term", "info", key))
        page.add(g)

        g = Adw.PreferencesGroup(description=tr("S'applique aux nouveaux terminaux. Le panneau en boucle déjà ouvert "
                                                "se met à jour tout seul."))
        b = Adw.ButtonRow(title=tr("Ouvrir un terminal pour voir"), start_icon_name="utilities-terminal-symbolic")
        b.connect("activated", lambda *_: GLib.spawn_command_line_async("kitty"))
        g.add(b)
        page.add(g)
        return page

    def page_fenetres(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Forme"))
        self.spin(g, "Arrondi des coins", ("win", "rounding"), 0, 30)
        self.spin(g, "Épaisseur de bordure", ("win", "border"), 0, 6)
        self.spin(g, "Espace entre fenêtres", ("win", "gap_in"), 0, 30)
        self.spin(g, "Marge au bord de l'écran", ("win", "gap_out"), 0, 60)
        self.switch(g, "Bordure en dégradé", ("win", "gradient"))
        self.spin(g, "Angle du dégradé", ("win", "angle"), 0, 360, 15)
        page.add(g)
        g = Adw.PreferencesGroup(title=tr("Verre et lumière"))
        self.switch(g, "Flou derrière les fenêtres", ("win", "blur"))
        self.spin(g, "Taille du flou", ("win", "blur_size"), 1, 20)
        self.spin(g, "Passes de flou", ("win", "blur_passes"), 1, 6, subtitle=tr("Plus = plus doux, mais plus coûteux"))
        self.spin(g, "Opacité fenêtre active", ("win", "opacity_active"), 0.5, 1, 0.01, 2)
        self.spin(g, "Opacité fenêtres inactives", ("win", "opacity_inactive"), 0.5, 1, 0.01, 2)
        self.spin(g, "Assombrir les inactives", ("win", "dim_inactive"), 0, 0.5, 0.02, 2)
        self.switch(g, "Ombres", ("win", "shadow"))
        self.switch(g, "Halo coloré autour de la fenêtre active", ("win", "glow"))
        page.add(g)
        g = Adw.PreferencesGroup(title=tr("Mouvement"))
        self.combo(g, "Animations", ("win", "anim"), {k: v["label"] for k, v in core.ANIMS.items()})
        page.add(g)
        return page

    def page_barre(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Barre"))
        self.combo(g, "Position", ("bar", "position"), {"top": "En haut", "bottom": "En bas"})
        self.combo(g, "Style", ("bar", "style"), core.BAR_STYLES)
        self.combo(g, "Espaces de travail", ("bar", "ws_style"), core.WS_STYLES)
        self.spin(g, "Hauteur", ("bar", "height"), 26, 52)
        page.add(g)
        g = Adw.PreferencesGroup(title=tr("Modules"),
                                 description=tr("Processeur, carte graphique et disque se déplient au survol de la mémoire."))
        for k, label in (("mpris", "Lecteur (musique, vidéo)"),
                         ("actions", "Raccourcis rapides (presse-papiers, capture, ne pas déranger)"),
                         ("tray", "Icônes des applis (Discord, Steam…)"), ("bots", "Bots"),
                         ("ram", "Mémoire"), ("cpu", "Processeur"), ("gpu", "Carte graphique"), ("disk", "Disque"),
                         ("audio", "Son et micro"), ("network", "Réseau")):
            self.switch(g, label, ("bar", "modules", k))
        page.add(g)
        g = Adw.PreferencesGroup()
        btn = Adw.ButtonRow(title=tr("Relancer la barre"), start_icon_name="view-refresh-symbolic")
        btn.connect("activated", lambda *_: core.restart_waybar())
        g.add(btn)
        page.add(g)
        return page

    def page_fond(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Fond assorti au thème"),
                                 description=tr("Régénéré tout seul quand tu changes de couleurs."))
        self.wall_auto = Adw.SwitchRow(title=tr("Suivre les couleurs du thème"),
                                       active=self.cfg["wall_mode"] == "auto")
        self.wall_auto.connect("notify::active", lambda r, _: self.set_wall_mode("auto" if r.get_active() else "image"))
        g.add(self.wall_auto)
        self.combo(g, "Style", ("wall_style",), core.WALL_STYLES)
        var = Adw.ButtonRow(title=tr("Nouvelle variante"), start_icon_name="view-refresh-symbolic")
        var.connect("activated", lambda *_: self.set(("wall_seed",), self.cfg["wall_seed"] + 1))
        g.add(var)
        keep = Adw.ButtonRow(title=tr("Garder ce fond dans mes images"), start_icon_name="document-save-symbolic")
        keep.connect("activated", lambda *_: self.keep_auto_wall())
        g.add(keep)
        self.wall_preview = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, height_request=200,
                                        css_classes=["wallprev"], margin_top=10)
        g.add(self.wall_preview)
        page.add(g)

        g = Adw.PreferencesGroup(title=tr("Mes images"),
                                 description=tr("{dossier} et ~/Images — un clic pour l'utiliser", dossier=core.WALLDIR))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr("Ajouter une image"), css_classes=["flat"])
        add.connect("clicked", lambda *_: self.add_wall())
        g.set_header_suffix(add)
        self.walls = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                 min_children_per_line=2, row_spacing=12, column_spacing=12, homogeneous=True)
        g.add(self.walls)
        page.add(g)
        self.fill_walls()
        self.refresh_preview()
        return page

    def set_wall_mode(self, mode):
        self.set(("wall_mode",), mode)
        self.fill_walls()

    def refresh_preview(self):
        if not hasattr(self, "wall_preview"):
            return False
        path = core.current_wall(self.cfg)
        if path and Path(path).exists():
            self.wall_preview.set_filename(thumb(path))
        return False

    def keep_auto_wall(self):
        src = core.auto_wall(self.cfg)
        if not src.exists():
            self.toast("Le fond n'est pas encore prêt")
            return
        core.WALLDIR.mkdir(parents=True, exist_ok=True)
        dst = core.WALLDIR / f"assorti-{self.cfg['preset']}-{self.cfg['wall_style']}-{self.cfg['wall_seed']}.png"
        dst.write_bytes(src.read_bytes())
        self.fill_walls()
        self.toast(tr("Enregistré : {nom}", nom=dst.name))

    def fill_walls(self):
        while (c := self.walls.get_first_child()):
            self.walls.remove(c)
        files = []
        for d in (core.WALLDIR, Path.home() / "Images"):
            if d.is_dir():
                files += sorted((f for f in d.iterdir() if f.suffix.lower() in IMG_EXT),
                                key=lambda f: -f.stat().st_mtime)
        for f in files[:60]:
            try:
                pic = Gtk.Picture.new_for_filename(thumb(f))
            except Exception:
                continue
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(220, 124)
            b = Gtk.Button(child=pic, css_classes=["wall"] + (["selected"] if self.cfg["wall_mode"] == "image"
                                                        and str(f) == self.cfg["wallpaper"] else []),
                           tooltip_text=f.name)
            b.connect("clicked", lambda _b, path=str(f): self.pick_wall(path))
            self.walls.append(b)

    def pick_wall(self, path):
        self.cfg["wallpaper"] = path
        self.wall_auto.set_active(False)  # repasse en mode image (et applique)
        self.set_wall_mode("image")
        self.schedule()

    def add_wall(self):
        dlg = Gtk.FileDialog(title=tr("Choisir une image"))
        f = Gtk.FileFilter(name=tr("Images"))
        for e in IMG_EXT:
            f.add_suffix(e.lstrip("."))
        dlg.set_default_filter(f)

        def done(d, res):
            try:
                src = Path(d.open_finish(res).get_path())
            except GLib.Error:
                return
            core.WALLDIR.mkdir(parents=True, exist_ok=True)
            dst = core.WALLDIR / src.name
            if src != dst:
                dst.write_bytes(src.read_bytes())
            self.pick_wall(str(dst))

        dlg.open(self.win, None, done)

    # ------------------------------------------------------------ son
    def page_son(self):
        page = Adw.PreferencesPage()
        self.snd = {}
        for kind, title, desc in (("sink", "Sortie", "Casque, enceintes, écran…"),
                                  ("source", "Micro", "Utilisé par défaut par Discord, le navigateur, etc.")):
            g = Adw.PreferencesGroup(title=tr(title), description=tr(desc))
            combo = Adw.ComboRow(title=tr("Appareil par défaut"))
            vol_row = Adw.ActionRow(title=tr("Volume"))
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
            scale.set_hexpand(True)
            scale.set_size_request(320, -1)
            scale.add_mark(100, Gtk.PositionType.BOTTOM, None)
            pct = Gtk.Label(width_chars=5, xalign=1)
            vol_row.add_suffix(scale)
            vol_row.add_suffix(pct)
            mute = Adw.SwitchRow(title=tr("Couper") if kind == "sink" else tr("Couper le micro"))
            for w in (combo, vol_row, mute):
                g.add(w)
            if kind == "sink":
                t = Adw.ButtonRow(title=tr("Tester le son"), start_icon_name="audio-speakers-symbolic")
                t.connect("activated", lambda *_: audio.test_sound())
                g.add(t)
            page.add(g)
            st = {"combo": combo, "scale": scale, "pct": pct, "mute": mute, "names": [], "busy": 0, "lock": False}
            self.snd[kind] = st

            def on_dev(r, _p, k=kind):
                s_ = self.snd[k]
                if s_["lock"] or r.get_selected() >= len(s_["names"]):
                    return
                audio.set_default(k, s_["names"][r.get_selected()])
                self.toast("Appareil par défaut changé")
                GLib.timeout_add(300, lambda: (self.refresh_son(), False)[1])

            def on_vol(sc, k=kind):
                s_ = self.snd[k]
                s_["pct"].set_label(f"{int(sc.get_value())} %")
                if s_["lock"] or not s_["names"]:
                    return
                s_["busy"] = GLib.get_monotonic_time()
                audio.set_volume(k, s_["names"][s_["combo"].get_selected()], sc.get_value())

            def on_mute(r, _p, k=kind):
                s_ = self.snd[k]
                if not s_["lock"] and s_["names"]:
                    audio.set_mute(k, s_["names"][s_["combo"].get_selected()], r.get_active())

            combo.connect("notify::selected", on_dev)
            scale.connect("value-changed", on_vol)
            mute.connect("notify::active", on_mute)
        g = Adw.PreferencesGroup()
        if GLib.find_program_in_path("pavucontrol"):
            b = Adw.ButtonRow(title=tr("Mixeur avancé (volume par appli)"), start_icon_name="multimedia-volume-control-symbolic")
            b.connect("activated", lambda *_: GLib.spawn_command_line_async("pavucontrol"))
            g.add(b)
            page.add(g)
        self.refresh_son()
        return page

    def refresh_son(self):
        for kind, st in self.snd.items():
            devs = audio.devices(kind)
            cur = next((d for d in devs if d["default"]), devs[0] if devs else None)
            st["lock"] = True
            names = [d["name"] for d in devs]
            if names != st["names"]:
                st["names"] = names
                st["combo"].set_model(Gtk.StringList.new([d["label"] for d in devs]))
            if cur:
                st["combo"].set_selected(names.index(cur["name"]))
                # ne pas reprendre la main pendant qu'on fait glisser le curseur
                if GLib.get_monotonic_time() - st["busy"] > 1_500_000:
                    st["scale"].set_value(cur["volume"])
                st["pct"].set_label(f"{int(st['scale'].get_value())} %")
                st["mute"].set_active(cur["mute"])
            st["lock"] = False

    def page_veille(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Inactivité"), description=tr("En minutes — 0 = jamais"))
        self.spin(g, "Verrouiller après", ("idle", "lock"), 0, 240)
        self.spin(g, "Éteindre les écrans après", ("idle", "screen_off"), 0, 240)
        self.spin(g, "Mettre en veille après", ("idle", "suspend"), 0, 480)
        page.add(g)
        g = Adw.PreferencesGroup()
        b = Adw.ButtonRow(title=tr("Verrouiller maintenant"), start_icon_name="system-lock-screen-symbolic")
        b.connect("activated", lambda *_: GLib.spawn_command_line_async("loginctl lock-session"))
        g.add(b)
        page.add(g)
        return page

    # ------------------------------------------------------------ raccourcis
    MODS = ("SUPER", "CTRL", "ALT", "SHIFT")
    FIXED = [
        ("SUPER + flèches", "Passer d'une fenêtre à l'autre"),
        ("SUPER + & é \" ' ( - è _ ç à", "Aller à l'espace de travail 1 à 10"),
        ("SUPER + SHIFT + & é \" …", "Envoyer la fenêtre sur l'espace 1 à 10"),
        ("SUPER + molette", "Espace de travail suivant / précédent"),
        ("SUPER + clic gauche / droit", "Déplacer / redimensionner à la souris"),
        ("Touches de volume", "Monter, baisser, couper le son"),
    ]
    FIXED_KEYS = ({f"SUPER + {k}".upper() for k in ("left", "right", "up", "down")}
                  | {f"{m}{k}".upper() for m in ("SUPER + ", "SUPER + SHIFT + ")
                     for k in ("ampersand", "eacute", "quotedbl", "apostrophe", "parenleft",
                               "minus", "egrave", "underscore", "ccedilla", "agrave")})

    @staticmethod
    def pretty_keys(keys):
        out = []
        for part in keys.split(" + "):
            kv = Gdk.keyval_from_name(part)
            ch = chr(Gdk.keyval_to_unicode(kv)) if kv and Gdk.keyval_to_unicode(kv) > 32 else ""
            out.append(tr({"SUPER": "Super", "SHIFT": "Maj", "CTRL": "Ctrl", "ALT": "Alt",
                           "Return": "Entrée", "space": "Espace", "Tab": "Tab", "Escape": "Échap",
                           "Print": "Impr. écran"}.get(part, ch.upper() if ch else part)))
        return " + ".join(out)

    def page_raccourcis(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Mes raccourcis"),
                                 description=tr("Clique sur un raccourci pour le modifier. Actif dès l'enregistrement."))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr("Nouveau raccourci"), css_classes=["flat"])
        add.connect("clicked", lambda *_: self.edit_bind(None))
        g.set_header_suffix(add)
        self.bind_group, self.bind_rows = g, []
        page.add(g)
        fixed = Adw.PreferencesGroup(title=tr("Raccourcis fixes"), description=tr("Définis dans hyprland.lua"))
        for k, d in self.FIXED:
            fixed.add(Adw.ActionRow(title=tr(d), subtitle=tr(k)))
        page.add(fixed)
        g3 = Adw.PreferencesGroup()
        reset = Adw.ButtonRow(title=tr("Rétablir les raccourcis par défaut"), start_icon_name="edit-undo-symbolic")
        reset.connect("activated", lambda *_: self.reset_binds())
        g3.add(reset)
        page.add(g3)
        self.fill_binds()
        return page

    def fill_binds(self):
        for r in self.bind_rows:
            self.bind_group.remove(r)
        self.bind_rows = []
        for i, b in enumerate(self.cfg["binds"]):
            row = Adw.ActionRow(title=core.bind_label(b), activatable=True,
                                subtitle=b.get("arg", "") if b["action"] == "exec" else "")
            keys = Gtk.Label(label=self.pretty_keys(b["keys"]), css_classes=["keycap"], valign=Gtk.Align.CENTER)
            row.add_suffix(keys)
            rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=tr("Supprimer"), valign=Gtk.Align.CENTER,
                            css_classes=["flat"])
            rm.connect("clicked", lambda _b, idx=i: self.del_bind(idx))
            row.add_suffix(rm)
            row.connect("activated", lambda _r, idx=i: self.edit_bind(idx))
            self.bind_group.add(row)
            self.bind_rows.append(row)

    def save_binds(self, binds):
        self.cfg["binds"] = binds
        self.schedule()
        self.fill_binds()

    def del_bind(self, idx):
        self.save_binds([b for i, b in enumerate(self.cfg["binds"]) if i != idx])
        self.toast("Raccourci supprimé")

    def reset_binds(self):
        self.save_binds(core.copy.deepcopy(core.DEFAULT_BINDS))
        self.toast("Raccourcis par défaut rétablis")

    def edit_bind(self, idx):
        cur = dict(self.cfg["binds"][idx]) if idx is not None else {"keys": "SUPER", "action": "exec", "arg": ""}
        parts = cur["keys"].split(" + ")
        state = {"mods": [m for m in parts if m in self.MODS], "key": next((p for p in parts if p not in self.MODS), "")}

        dlg = Adw.Dialog(title=tr("Modifier le raccourci") if idx is not None else tr("Nouveau raccourci"),
                         content_width=520)
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        ids = list(core.ACTIONS)
        action = Adw.ComboRow(title=tr("Action"), model=Gtk.StringList.new([tr(core.ACTIONS[a][0]) for a in ids]))
        action.set_selected(ids.index(cur["action"]) if cur["action"] in ids else 0)
        cmd = Adw.EntryRow(title=tr("Commande à lancer"), text=cur.get("arg", ""))
        name = Adw.EntryRow(title=tr("Nom affiché (facultatif)"), text=cur.get("label", ""))
        for w in (action, cmd, name):
            g.add(w)
        page.add(g)

        kg = Adw.PreferencesGroup(title=tr("Touches"),
                                  description=tr("Active les modificateurs, puis clique sur « Touche » et appuie sur la touche seule."))
        mods_row = Adw.ActionRow(title=tr("Modificateurs"))
        toggles = {}
        for m in self.MODS:
            t = Gtk.ToggleButton(label=self.pretty_keys(m), active=m in state["mods"], valign=Gtk.Align.CENTER)
            toggles[m] = t
            mods_row.add_suffix(t)
        key_btn = Gtk.Button(label=self.pretty_keys(state["key"]) if state["key"] else tr("Choisir…"),
                             valign=Gtk.Align.CENTER)
        key_row = Adw.ActionRow(title=tr("Touche"))
        key_row.add_suffix(key_btn)
        result = Adw.ActionRow(title=tr("Raccourci"), css_classes=["property"])
        warn = Gtk.Label(css_classes=["error"], wrap=True, xalign=0, margin_top=6)
        for w in (mods_row, key_row, result):
            kg.add(w)
        kg.add(warn)
        page.add(kg)

        save = Gtk.Button(label=tr("Enregistrer"), css_classes=["suggested-action"])
        head = Adw.HeaderBar()
        head.pack_end(save)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(head)
        dlg.set_child(view)

        def combo():
            mods = [m for m in self.MODS if toggles[m].get_active()]
            return " + ".join(mods + ([state["key"]] if state["key"] else []))

        def refresh(*_):
            is_exec = ids[action.get_selected()] == "exec"
            cmd.set_visible(is_exec)
            k = combo()
            result.set_subtitle(self.pretty_keys(k) if state["key"] else "—")
            clash = next((core.bind_label(b) for i, b in enumerate(self.cfg["binds"])
                          if i != idx and b["keys"].upper() == k.upper()), None)
            if not clash and k.upper() in self.FIXED_KEYS:
                clash = tr("un raccourci fixe")
            msg = (tr("Déjà utilisé par « {nom} ».", nom=clash) if clash else
                   tr("Choisis une touche.") if not state["key"] else
                   tr("Indique la commande à lancer.") if is_exec and not cmd.get_text().strip() else "")
            warn.set_label(msg)
            save.set_sensitive(not msg)

        capturing = {"on": False}

        def start_capture(*_):
            capturing["on"] = True
            key_btn.set_label(tr("Appuie sur une touche…"))
            dlg.grab_focus()

        def on_key(_c, keyval, _code, _mods):
            if not capturing["on"]:
                return False
            name_ = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
            if name_.startswith(("Shift", "Control", "Alt", "Super", "Meta", "ISO_", "Caps")):
                return True
            state["key"] = name_.upper() if len(name_) == 1 else name_
            capturing["on"] = False
            key_btn.set_label(self.pretty_keys(state["key"]))
            refresh()
            return True

        ctl = Gtk.EventControllerKey()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("key-pressed", on_key)
        dlg.add_controller(ctl)
        key_btn.connect("clicked", start_capture)
        action.connect("notify::selected", refresh)
        cmd.connect("changed", refresh)
        for t in toggles.values():
            t.connect("toggled", refresh)

        def do_save(*_):
            act = ids[action.get_selected()]
            b = {"keys": combo(), "action": act}
            if act == "exec":
                b["arg"] = cmd.get_text().strip()
            if name.get_text().strip():
                b["label"] = name.get_text().strip()
            binds = list(self.cfg["binds"])
            if idx is None:
                binds.append(b)
            else:
                binds[idx] = b
            self.save_binds(binds)
            dlg.close()
            self.toast(f"{self.pretty_keys(b['keys'])} → {core.bind_label(b)}")

        save.connect("clicked", do_save)
        refresh()
        dlg.present(self.win)

    # ------------------------------------------------------------ bots
    def page_bots(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Bots"), description=tr("Lancés en services systemd : redémarrage auto s'ils plantent, journaux dans « Logs »."))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr("Ajouter un bot (choisir son dossier)"),
                         css_classes=["flat"])
        add.connect("clicked", lambda *_: self.add_bot())
        g.set_header_suffix(add)
        self.bot_group = g
        self.bot_rows = []
        page.add(g)
        self.fill_bots()
        return page

    def fill_bots(self):
        for r in self.bot_rows:
            self.bot_group.remove(r)
        self.bot_rows = []
        lst = bots.load()
        if not lst:
            r = Adw.ActionRow(title=tr("Aucun bot"), subtitle=tr("Clique sur + et choisis le dossier du bot"))
            self.bot_group.add(r)
            self.bot_rows.append(r)
            return
        for i, b in enumerate(lst):
            exp = Adw.ExpanderRow(title=b["name"])
            state = Gtk.Label(css_classes=["dim-label"])
            exp.add_suffix(state)
            for icon, tip, fn in (("media-playback-start-symbolic", "Démarrer", bots.start),
                                  ("view-refresh-symbolic", "Redémarrer", bots.restart),
                                  ("media-playback-stop-symbolic", "Arrêter", bots.stop),
                                  ("utilities-terminal-symbolic", "Logs", bots.logs)):
                btn = Gtk.Button(icon_name=icon, tooltip_text=tr(tip), valign=Gtk.Align.CENTER, css_classes=["flat"])
                btn.connect("clicked", lambda _b, f=fn, bot=b: self.bot_action(f, bot))
                exp.add_suffix(btn)
            cmd = Adw.EntryRow(title=tr("Commande"), text=b["cmd"], show_apply_button=True)
            cmd.connect("apply", lambda e, idx=i: self.bot_edit(idx, "cmd", e.get_text()))
            exp.add_row(cmd)
            exp.add_row(Adw.ActionRow(title=tr("Dossier"), subtitle=b["dir"]))
            auto = Adw.SwitchRow(title=tr("Lancer à l'ouverture de session"), active=b.get("autostart", False))
            auto.connect("notify::active", lambda r, _, idx=i: self.bot_edit(idx, "autostart", r.get_active()))
            exp.add_row(auto)
            rm = Adw.ButtonRow(title=tr("Retirer de la liste"), start_icon_name="user-trash-symbolic",
                               css_classes=["destructive-action"])
            rm.connect("activated", lambda *_a, bot=b: self.bot_remove(bot))
            exp.add_row(rm)
            exp._state, exp._bot = state, b
            self.bot_group.add(exp)
            self.bot_rows.append(exp)
        self.refresh_bots()

    def refresh_bots(self):
        for r in self.bot_rows:
            if not hasattr(r, "_bot"):
                continue
            s = bots.status(r._bot)
            txt = tr({"active": "● actif", "failed": "✕ planté", "activating": "… démarre"}.get(s["state"], "○ arrêté"))
            if s["state"] == "active":
                txt += f"  ·  {bots.human(s['mem'])}"
            if s["restarts"]:
                txt += "  ·  " + tr("{n} relance(s)", n=s["restarts"])
            r._state.set_label(txt)
            r.set_subtitle("")

    def bot_action(self, fn, bot):
        r = fn(bot)
        if getattr(r, "returncode", 0):
            self.toast(tr("Échec : {erreur}", erreur=r.stderr.strip()[:80]))
        GLib.timeout_add(600, lambda: (self.refresh_bots(), False)[1])

    def bot_edit(self, idx, key, value):
        lst = bots.load()
        lst[idx][key] = value
        bots.save(lst)
        self.toast("Enregistré")

    def bot_remove(self, bot):
        bots.stop(bot)
        bots.save([b for b in bots.load() if b["name"] != bot["name"]])
        self.fill_bots()

    def add_bot(self):
        def done(d, res):
            try:
                folder = Path(d.select_folder_finish(res).get_path())
            except GLib.Error:
                return
            lst = bots.load()
            name, n = folder.name, 2
            while any(b["name"] == name for b in lst):
                name, n = f"{folder.name}-{n}", n + 1
            cmd = bots.detect(folder) or ""
            lst.append({"name": name, "dir": str(folder), "cmd": cmd, "autostart": False})
            bots.save(lst)
            self.fill_bots()
            self.toast(tr("{nom} ajouté", nom=name) + ("" if cmd else tr(" — indique la commande de lancement")))

        Gtk.FileDialog(title=tr("Dossier du bot")).select_folder(self.win, None, done)

    # ------------------------------------------------------------ mémoire
    def page_ram(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6, margin_bottom=6)
        self.ram_big = Gtk.Label(css_classes=["bigram"], xalign=0)
        self.ram_bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.ram_sub = Gtk.Label(css_classes=["dim-label"], xalign=0)
        for w in (self.ram_big, self.ram_bar, self.ram_sub):
            box.append(w)
        g.add(box)
        page.add(g)
        self.ram_group = Adw.PreferencesGroup(title=tr("Applis qui consomment le plus"),
                                              description=tr("Fermer libère vraiment de la RAM. Le « cache » de Linux, lui, se libère tout seul quand il faut."))
        self.ram_rows = []
        page.add(self.ram_group)
        self.refresh_ram()
        return page

    def refresh_ram(self):
        vm = ram.psutil.virtual_memory()
        used = vm.total - vm.available
        self.ram_big.set_label(tr("{u} Go / {t} Go", u=f"{used / 1024**3:.1f}", t=f"{vm.total / 1024**3:.0f}"))
        self.ram_bar.set_value(used / vm.total)
        self.ram_sub.set_label(tr("Cache disque (récupérable) : {taille}", taille=bots.human(vm.cached + vm.buffers)))
        for r in self.ram_rows:
            self.ram_group.remove(r)
        self.ram_rows = []
        for a in ram.apps(10):
            row = Adw.ActionRow(title=a["name"], subtitle=tr("{taille} · {n} processus", taille=bots.human(a["mem"]),
                                                             n=len(a["pids"])))
            b = Gtk.Button(label=tr("Fermer"), valign=Gtk.Align.CENTER, css_classes=["flat"])
            b.connect("clicked", lambda _b, app=a: self.close_app(app))
            row.add_suffix(b)
            self.ram_group.add(row)
            self.ram_rows.append(row)

    def close_app(self, a):
        d = Adw.AlertDialog(heading=tr("Fermer {nom} ?", nom=a["name"]),
                            body=tr("{n} processus · {taille}. Le travail non enregistré sera perdu.",
                                    n=len(a["pids"]), taille=bots.human(a["mem"])))
        d.add_response("non", tr("Annuler"))
        d.add_response("oui", tr("Fermer"))
        d.set_response_appearance("oui", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: (ram.kill_app(a), GLib.timeout_add(800, lambda: (self.refresh_ram(), False)[1])) if r == "oui" else None)
        d.present(self.win)

    def tick(self):
        if not self.win or not self.win.get_visible():
            return True
        page = self.stack.get_visible_child_name()
        if page == "bots":
            self.refresh_bots()
        elif page == "son":
            self.refresh_son()
        elif page == "ram":
            self.refresh_ram()
        return True

    # ------------------------------------------------------------ page Fichiers
    def page_fichiers(self):
        page = Adw.PreferencesPage()

        g = Adw.PreferencesGroup(title=tr("Gestionnaire de fichiers"))
        self.combo(g, "Vue par défaut", ["files", "view"], {
            "list": tr("Liste"),
            "grid": tr("Grille"),
        })
        self.switch(g, "Fichiers cachés visibles", ["files", "show_hidden"])
        self.switch(g, "Ouvrir en un seul clic", ["files", "single_click"])
        page.add(g)

        g2 = Adw.PreferencesGroup(title=tr("Terminal"))
        terminals = {"kitty": "Kitty", "alacritty": "Alacritty", "foot": "Foot",
                     "wezterm": "WezTerm", "ghostty": "Ghostty"}
        self.combo(g2, "Émulateur de terminal", ["files", "terminal"], terminals)
        page.add(g2)

        g3 = Adw.PreferencesGroup(title=tr("Actions rapides"))
        open_row = Adw.ActionRow(title=tr("Ouvrir le gestionnaire"), activatable=True)
        open_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        open_row.connect("activated", lambda _: self._launch_fichiers())
        g3.add(open_row)
        page.add(g3)

        return page

    def _launch_fichiers(self):
        import subprocess
        subprocess.Popen(["studio-fichiers"], start_new_session=True)


if __name__ == "__main__":
    sys.exit(Studio().run(sys.argv))
