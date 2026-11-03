"""Pages « Système » du Studio : écrans, clavier et souris, applis par défaut, démarrage."""
import copy
import shutil
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

import core
import session
from i18n import tr

SCALES = [1.0, 1.25, 1.5, 1.6, 1.75, 2.0]
VRR = {0: "Désactivé", 1: "Activé", 2: "Seulement en plein écran"}
LAYOUTS = {"fr": "Français (AZERTY)", "be": "Belge", "ch": "Suisse", "ca": "Canadien français",
           "us": "Anglais US (QWERTY)", "gb": "Anglais UK", "de": "Allemand", "es": "Espagnol", "it": "Italien"}
CAPS = {"": "Normal", "caps:escape": "Échap", "ctrl:nocaps": "Ctrl", "caps:none": "Désactivé"}
ACCEL = {"": "Par défaut", "flat": "Désactivée (précis, jeux)", "adaptive": "Adaptative"}
FOCUS = {1: "Suit la souris", 2: "Suit le clic (souris libre)", 0: "Au clic seulement"}


def logical(m):
    """Taille à l'écran (pixels logiques) en tenant compte de la rotation et de l'échelle."""
    w, h = (int(x) for x in m["mode"].split("@")[0].split("x"))
    if m["transform"] % 2:
        w, h = h, w
    return round(w / m["scale"]), round(h / m["scale"])


class SystemPages:
    """Mélangé dans l'appli Studio (utilise self.cfg, self.set, self.toast, self.win…)."""

    # ================================================================ ÉCRANS
    def page_ecrans(self):
        page = Adw.PreferencesPage()
        if not self.cfg["monitors"]:
            self.cfg["monitors"] = core.import_monitors()
        self.draft = copy.deepcopy(self.cfg["monitors"])
        self.sel = next(iter(self.draft), None)

        g = Adw.PreferencesGroup(title=tr("Disposition"),
                                 description=tr("Fais glisser les écrans pour les placer. Clique sur un écran pour le régler."))
        self.canvas = Gtk.DrawingArea(content_height=280, hexpand=True, css_classes=["card"])
        self.canvas.set_draw_func(self.draw_monitors)
        click = Gtk.GestureClick()
        click.connect("pressed", self.canvas_click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.drag_begin)
        drag.connect("drag-update", self.drag_update)
        drag.connect("drag-end", self.drag_end)
        self.canvas.add_controller(click)
        self.canvas.add_controller(drag)
        g.add(self.canvas)
        page.add(g)

        self.mon_group = Adw.PreferencesGroup()
        detect = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=tr("Redétecter les écrans"),
                            css_classes=["flat"])
        detect.connect("clicked", lambda *_: self.redetect())
        self.mon_group.set_header_suffix(detect)
        self.mon_on = Adw.SwitchRow(title=tr("Écran allumé"))
        self.mon_res = Adw.ComboRow(title=tr("Résolution"))
        self.mon_hz = Adw.ComboRow(title=tr("Fréquence"))
        self.mon_scale = Adw.ComboRow(title=tr("Échelle"), subtitle=tr("Agrandit tout (texte, fenêtres)"),
                                      model=Gtk.StringList.new([f"{int(s * 100)} %" for s in SCALES]))
        self.mon_rot = Adw.ComboRow(title=tr("Orientation"), model=Gtk.StringList.new([tr(v) for v in list(core.TRANSFORMS.values())[:4]]))
        self.mon_vrr = Adw.ComboRow(title=tr("Fréquence variable (FreeSync / G-Sync)"),
                                    model=Gtk.StringList.new([tr(v) for v in VRR.values()]))
        self.mon_10 = Adw.SwitchRow(title=tr("Couleurs 10 bits"), subtitle=tr("Plus de nuances, si l'écran le gère"))
        for w in (self.mon_on, self.mon_res, self.mon_hz, self.mon_scale, self.mon_rot, self.mon_vrr, self.mon_10):
            self.mon_group.add(w)
        self.mon_lock = False
        self.mon_on.connect("notify::active", lambda r, _: self.mon_edit("enabled", r.get_active()))
        self.mon_res.connect("notify::selected", lambda *_: self.mon_res_changed())
        self.mon_hz.connect("notify::selected", lambda *_: self.mon_hz_changed())
        self.mon_scale.connect("notify::selected", lambda r, _: self.mon_edit("scale", SCALES[r.get_selected()]))
        self.mon_rot.connect("notify::selected", lambda r, _: self.mon_edit("transform", r.get_selected()))
        self.mon_vrr.connect("notify::selected", lambda r, _: self.mon_edit("vrr", r.get_selected()))
        self.mon_10.connect("notify::active", lambda r, _: self.mon_edit("bitdepth10", r.get_active()))
        page.add(self.mon_group)

        g = Adw.PreferencesGroup()
        self.mon_apply = Adw.ButtonRow(title=tr("Appliquer"), start_icon_name="emblem-ok-symbolic",
                                       css_classes=["suggested-action"], sensitive=False)
        self.mon_apply.connect("activated", lambda *_: self.mon_commit())
        g.add(self.mon_apply)
        page.add(g)

        g = Adw.PreferencesGroup(title=tr("Veilleuse"), description=tr("Écran plus chaud le soir, moins de lumière bleue."))
        if not shutil.which("hyprsunset"):
            g.set_description(tr("Installe hyprsunset pour l'activer : sudo pacman -S hyprsunset"))
        self.switch(g, "Activer la veilleuse", ("sunset", "enabled"))
        self.spin(g, "Température", ("sunset", "temp"), 2500, 6000, 100, subtitle=tr("Plus bas = plus orangé"))
        for key, title in (("start", "Début"), ("end", "Fin")):
            e = Adw.EntryRow(title=tr(title) + " (HH:MM)", text=self.cfg["sunset"][key], show_apply_button=True)
            e.connect("apply", lambda r, k=key: self.set_time(k, r.get_text()))
            g.add(e)
        page.add(g)
        self.fill_monitor()
        return page

    def set_time(self, key, txt):
        try:
            h, m = (int(x) for x in txt.strip().split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            self.toast("Format attendu : 21:00")
            return
        self.set(("sunset", key), f"{h:02d}:{m:02d}")

    # -- dessin et glisser
    def _layout(self):
        W, H = self.canvas.get_width(), self.canvas.get_height()
        rects = {n: (m["x"], m["y"], *logical(m)) for n, m in self.draft.items() if m.get("enabled", True)}
        if not rects:
            return 1, 0, 0, rects
        x0 = min(r[0] for r in rects.values())
        y0 = min(r[1] for r in rects.values())
        x1 = max(r[0] + r[2] for r in rects.values())
        y1 = max(r[1] + r[3] for r in rects.values())
        k = min((W - 60) / max(1, x1 - x0), (H - 50) / max(1, y1 - y0))
        ox = (W - (x1 - x0) * k) / 2 - x0 * k
        oy = (H - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy, rects

    def draw_monitors(self, area, cr, W, H):
        if getattr(self, "_frozen", None):  # pendant un glisser, l'échelle ne bouge pas
            k, ox, oy, _ = self._frozen
            rects = {n: (m["x"], m["y"], *logical(m)) for n, m in self.draft.items() if m.get("enabled", True)}
        else:
            k, ox, oy, rects = self._layout()
        self._geom = (k, ox, oy, rects)
        p = core.palette(self.cfg)
        for n, (x, y, w, h) in rects.items():
            X, Y, Wd, Hd = ox + x * k + 3, oy + y * k + 3, w * k - 6, h * k - 6
            sel = n == self.sel
            col = core.rgb(p["accent"] if sel else p["elevated"])
            cr.set_source_rgba(*(c / 255 for c in col), 0.95 if sel else 1)
            self._round(cr, X, Y, Wd, Hd, 10)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.18)
            self._round(cr, X, Y, Wd, Hd, 10)
            cr.set_line_width(1)
            cr.stroke()
            fg = core.rgb(p["on_accent"] if sel else p["text"])
            cr.set_source_rgb(*(c / 255 for c in fg))
            cr.select_font_face(self.cfg["font"], 0, 1)
            res, hz = self.draft[n]["mode"].split("@")
            for i, txt in enumerate((n, self.draft[n].get("desc", ""), f"{res.replace('x', '×')} · {float(hz):.0f} Hz")):
                size = 15 if i == 0 else 11
                cr.set_font_size(size)
                while cr.text_extents(txt).width > Wd - 12 and size > 7:  # rétrécit pour tenir dans l'écran
                    size -= 0.5
                    cr.set_font_size(size)
                ext = cr.text_extents(txt)
                cr.move_to(X + (Wd - ext.width) / 2, Y + Hd / 2 - 14 + i * 17)
                cr.show_text(txt)

    @staticmethod
    def _round(cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _hit(self, px, py):
        k, ox, oy, rects = self._geom
        for n, (x, y, w, h) in rects.items():
            if ox + x * k <= px <= ox + (x + w) * k and oy + y * k <= py <= oy + (y + h) * k:
                return n
        return None

    def canvas_click(self, _g, _n, px, py):
        n = self._hit(px, py)
        if n:
            self.sel = n
            self.fill_monitor()
            self.canvas.queue_draw()

    def drag_begin(self, _g, px, py):
        self._drag = self._hit(px, py)
        if self._drag:
            self.sel = self._drag
            self._frozen = self._geom
            self._start = (self.draft[self._drag]["x"], self.draft[self._drag]["y"])
            self.fill_monitor()

    def drag_update(self, _g, dx, dy):
        if not getattr(self, "_drag", None):
            return
        k = self._frozen[0]
        m = self.draft[self._drag]
        m["x"], m["y"] = round(self._start[0] + dx / k), round(self._start[1] + dy / k)
        self.canvas.queue_draw()

    def drag_end(self, *_):
        if not getattr(self, "_drag", None):
            return
        self.snap(self._drag)
        self._drag = self._frozen = None
        self.mon_apply.set_sensitive(True)
        self.canvas.queue_draw()

    def snap(self, name):
        """Colle l'écran déplacé au bord de l'écran le plus proche, puis ramène l'ensemble à (0,0)."""
        a = self.draft[name]
        aw, ah = logical(a)
        best, dist = None, None
        for n, b in self.draft.items():
            if n == name or not b.get("enabled", True):
                continue
            bw, bh = logical(b)
            cands = [(b["x"] + bw, None), (b["x"] - aw, None), (None, b["y"] + bh), (None, b["y"] - ah)]
            for cx, cy in cands:
                if cx is not None:  # côte à côte : y libre, mais il faut se toucher
                    y = min(max(a["y"], b["y"] - ah + 1), b["y"] + bh - 1)
                    y = min((b["y"], b["y"] + bh - ah, b["y"] + (bh - ah) // 2, y), key=lambda v: abs(v - y)) \
                        if min(abs(y - v) for v in (b["y"], b["y"] + bh - ah, b["y"] + (bh - ah) // 2)) < 80 else y
                    pos = (cx, y)
                else:
                    x = min(max(a["x"], b["x"] - aw + 1), b["x"] + bw - 1)
                    x = min((b["x"], b["x"] + bw - aw, b["x"] + (bw - aw) // 2, x), key=lambda v: abs(v - x)) \
                        if min(abs(x - v) for v in (b["x"], b["x"] + bw - aw, b["x"] + (bw - aw) // 2)) < 80 else x
                    pos = (x, cy)
                d = abs(pos[0] - a["x"]) + abs(pos[1] - a["y"])
                if dist is None or d < dist:
                    best, dist = pos, d
        if best:
            a["x"], a["y"] = best
        on = [m for m in self.draft.values() if m.get("enabled", True)]
        x0, y0 = min(m["x"] for m in on), min(m["y"] for m in on)
        for m in on:
            m["x"] -= x0
            m["y"] -= y0

    # -- réglages de l'écran sélectionné
    def fill_monitor(self):
        if not self.sel:
            return
        m = self.draft[self.sel]
        self.mon_lock = True
        self.mon_group.set_title(f"{self.sel} — {m.get('desc', '')}")
        self.mon_on.set_active(m.get("enabled", True))
        modes = m.get("modes") or [m["mode"]]
        self._res = sorted({x.split("@")[0] for x in modes}, key=lambda r: -eval(r.replace("x", "*")))
        cur_res, cur_hz = m["mode"].split("@")
        self.mon_res.set_model(Gtk.StringList.new([r.replace("x", " × ") for r in self._res]))
        self.mon_res.set_selected(self._res.index(cur_res) if cur_res in self._res else 0)
        self._fill_hz(cur_hz)
        sc = min(range(len(SCALES)), key=lambda i: abs(SCALES[i] - m["scale"]))
        self.mon_scale.set_selected(sc)
        self.mon_rot.set_selected(m["transform"] % 4)
        self.mon_vrr.set_selected(m.get("vrr", 0))
        self.mon_10.set_active(m.get("bitdepth10", False))
        self.mon_lock = False

    def _fill_hz(self, want=None):
        m = self.draft[self.sel]
        res = self._res[self.mon_res.get_selected()]
        self._hz = sorted({x.split("@")[1] for x in (m.get("modes") or [m["mode"]]) if x.startswith(res + "@")},
                          key=lambda h: -float(h))
        self.mon_hz.set_model(Gtk.StringList.new([f"{float(h):.0f} Hz" for h in self._hz]))
        if want in self._hz:
            self.mon_hz.set_selected(self._hz.index(want))

    def mon_res_changed(self):
        if self.mon_lock:
            return
        self.mon_lock = True
        self._fill_hz()
        self.mon_hz.set_selected(0)  # la plus haute fréquence dispo
        self.mon_lock = False
        self.mon_hz_changed()

    def mon_hz_changed(self):
        if self.mon_lock or not self._hz:
            return
        self.mon_edit("mode", f"{self._res[self.mon_res.get_selected()]}@{self._hz[self.mon_hz.get_selected()]}")

    def mon_edit(self, key, value):
        if self.mon_lock or not self.sel:
            return
        self.draft[self.sel][key] = value
        if key in ("mode", "scale", "transform", "enabled"):
            self.snap(self.sel)  # la taille a changé : on recolle
        self.mon_apply.set_sensitive(True)
        self.canvas.queue_draw()

    def redetect(self):
        fresh = core.import_monitors()
        for n, m in fresh.items():
            if n in self.draft:
                self.draft[n]["modes"] = m["modes"]
            else:
                self.draft[n] = m
        self.sel = self.sel if self.sel in self.draft else next(iter(self.draft), None)
        self.fill_monitor()
        self.canvas.queue_draw()
        self.toast(tr("{n} écran(s) détecté(s)", n=len(fresh)))

    def _push(self, monitors):
        for n, m in monitors.items():
            core.hypr_eval(core.monitor_lua(n, m))

    def mon_commit(self):
        old = copy.deepcopy(self.cfg["monitors"])
        new = copy.deepcopy(self.draft)
        if not any(m.get("enabled", True) for m in new.values()):
            self.toast("Il faut au moins un écran allumé")
            return
        self._push(new)
        left = {"s": 15}
        dlg = Adw.AlertDialog(heading=tr("Garder ces réglages ?"),
                              body=tr("Retour automatique aux anciens réglages dans {n} s.", n=left["s"]))
        dlg.add_response("annuler", tr("Revenir"))
        dlg.add_response("garder", tr("Garder"))
        dlg.set_response_appearance("garder", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("annuler")
        state = {"done": False}

        def finish(keep):
            if state["done"]:
                return
            state["done"] = True
            if keep:
                self.cfg["monitors"] = new
                self.schedule()
                self.mon_apply.set_sensitive(False)
                self.toast("Écrans enregistrés")
            else:
                self._push(old)
                self.draft = copy.deepcopy(old)
                self.fill_monitor()
                self.canvas.queue_draw()
                self.toast("Anciens réglages rétablis")

        def countdown():
            if state["done"]:
                return False
            left["s"] -= 1
            if left["s"] <= 0:
                dlg.close()
                finish(False)
                return False
            dlg.set_body(tr("Retour automatique aux anciens réglages dans {n} s.", n=left["s"]))
            return True

        dlg.connect("response", lambda _d, r: finish(r == "garder"))
        GLib.timeout_add_seconds(1, countdown)
        dlg.present(self.win)

    # ================================================================ CLAVIER ET SOURIS
    def page_clavier(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Clavier"))
        self.combo(g, "Disposition", ("input", "kb_layout"), LAYOUTS)
        self.combo(g, "Touche Verr. Maj", ("input", "kb_options"), CAPS)
        self.switch(g, "Verr. Num activé au démarrage", ("input", "numlock"))
        self.spin(g, "Délai avant répétition", ("input", "repeat_delay"), 150, 1000, 25, subtitle=tr("En millisecondes"))
        self.spin(g, "Vitesse de répétition", ("input", "repeat_rate"), 10, 80, 1, subtitle=tr("Caractères par seconde"))
        g.add(Adw.EntryRow(title=tr("Zone de test")))
        page.add(g)
        g = Adw.PreferencesGroup(title=tr("Souris"))
        self.spin(g, "Vitesse du pointeur", ("input", "sensitivity"), -1, 1, 0.05, 2, subtitle=tr("0 = vitesse normale"))
        self.combo(g, "Accélération", ("input", "accel"), ACCEL)
        self.spin(g, "Vitesse de défilement", ("input", "scroll_factor"), 0.2, 3, 0.1, 1)
        self.switch(g, "Défilement naturel", ("input", "natural_scroll"), "Comme sur un téléphone")
        self.switch(g, "Mode gaucher", ("input", "left_handed"))
        self.combo(g, "Fenêtre active", ("input", "follow_mouse"), FOCUS)
        page.add(g)
        return page

    # ================================================================ APPLIS PAR DÉFAUT
    def page_applis(self):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title=tr("Applis par défaut"),
                                 description=tr("Ouvrent les liens et les fichiers. Les raccourcis Navigateur, Fichiers et Terminal suivent."))
        for cat, (title, _m) in session.CATEGORIES.items():
            apps, cur = session.apps_for(cat)
            if not apps:
                g.add(Adw.ActionRow(title=tr(title), subtitle=tr("Aucune appli installée pour ça")))
                continue
            ids = [a.get_id() for a in apps]
            row = Adw.ComboRow(title=tr(title), model=Gtk.StringList.new([a.get_display_name() for a in apps]))
            if cur in ids:
                row.set_selected(ids.index(cur))
            row.connect("notify::selected", lambda r, _p, c=cat, i=ids: self.app_pick(c, i[r.get_selected()]))
            g.add(row)
        terms = session.terminals()
        if terms:
            cur = next((b.get("arg") for b in self.cfg["binds"] if b.get("label") == "Terminal"), terms[0])
            row = Adw.ComboRow(title=tr("Terminal"), model=Gtk.StringList.new(terms))
            if cur in terms:
                row.set_selected(terms.index(cur))
            row.connect("notify::selected", lambda r, _p: self.app_pick("terminal", terms[r.get_selected()]))
            g.add(row)
        page.add(g)
        return page

    def app_pick(self, cat, app_id):
        if cat != "terminal":
            session.set_default(cat, app_id)
            cmd = "gtk-launch " + app_id.removesuffix(".desktop")
        else:
            cmd = app_id
            (Path.home() / ".config" / "xdg-terminals.list").write_text(app_id + ".desktop\n")
        label = session.BIND_FOR.get(cat)
        if label:
            binds = [dict(b, arg=cmd) if b.get("label") == label and b["action"] == "exec" else b
                     for b in self.cfg["binds"]]
            if binds != self.cfg["binds"]:
                self.cfg["binds"] = binds
                self.schedule()
                if hasattr(self, "bind_group"):
                    self.fill_binds()
        self.toast("Appli par défaut changée")

    # ================================================================ DÉMARRAGE
    def page_demarrage(self):
        page = Adw.PreferencesPage()
        self.auto_sys = Adw.PreferencesGroup(title=tr("Programmes du système"),
                                             description=tr("Lancés à l'ouverture de session. Les bots se règlent dans « Bots »."))
        self.auto_sys_rows = []
        page.add(self.auto_sys)
        self.auto_mine = Adw.PreferencesGroup(title=tr("Mes programmes"))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr("Ajouter"), css_classes=["flat"])
        add.connect("clicked", lambda *_: self.auto_add())
        self.auto_mine.set_header_suffix(add)
        self.auto_mine_rows = []
        page.add(self.auto_mine)
        self.fill_autostart()
        return page

    def fill_autostart(self):
        for grp, rows in ((self.auto_sys, self.auto_sys_rows), (self.auto_mine, self.auto_mine_rows)):
            for r in rows:
                grp.remove(r)
            rows.clear()
        for e in session.xdg_entries():
            r = Adw.SwitchRow(title=e["name"], subtitle=e["exec"], active=e["enabled"])
            r.connect("notify::active", lambda row, _p, i=e["id"]: session.set_xdg_enabled(i, row.get_active()))
            self.auto_sys.add(r)
            self.auto_sys_rows.append(r)
        for idx, a in enumerate(self.cfg["autostart"]):
            r = Adw.SwitchRow(title=a.get("name") or a["cmd"], subtitle=a["cmd"], active=a.get("enabled", True))
            r.connect("notify::active", lambda row, _p, i=idx: self.auto_edit(i, enabled=row.get_active()))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
            rm.connect("clicked", lambda _b, i=idx: self.auto_del(i))
            r.add_suffix(rm)
            self.auto_mine.add(r)
            self.auto_mine_rows.append(r)
        if not self.cfg["autostart"]:
            r = Adw.ActionRow(title=tr("Rien pour l'instant"), subtitle=tr("Clique sur + pour ajouter une appli ou une commande"))
            self.auto_mine.add(r)
            self.auto_mine_rows.append(r)

    def auto_edit(self, i, **kw):
        lst = copy.deepcopy(self.cfg["autostart"])
        lst[i].update(kw)
        self.set(("autostart",), lst)

    def auto_del(self, i):
        self.set(("autostart",), [a for n, a in enumerate(self.cfg["autostart"]) if n != i])
        self.fill_autostart()

    def auto_add(self):
        dlg = Adw.Dialog(title=tr("Lancer au démarrage"), content_width=460, content_height=560)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=14, margin_end=14,
                      margin_bottom=14)
        search = Gtk.SearchEntry(placeholder_text=tr("Chercher une appli…"))
        lb = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show()), key=lambda a: a.get_display_name().lower())
        for a in apps:
            row = Adw.ActionRow(title=a.get_display_name(), activatable=True)
            if a.get_icon():
                row.add_prefix(Gtk.Image(gicon=a.get_icon(), pixel_size=24))
            row._app = a
            row.connect("activated", lambda r: pick(r._app.get_display_name(),
                                                    "gtk-launch " + r._app.get_id().removesuffix(".desktop")))
            lb.append(row)
        lb.set_filter_func(lambda r: search.get_text().lower() in r._app.get_display_name().lower())
        search.connect("search-changed", lambda *_: lb.invalidate_filter())
        cmd = Adw.EntryRow(title=tr("…ou une commande"), show_apply_button=True)
        cmd.connect("apply", lambda e: pick(None, e.get_text().strip()))

        def pick(name, command):
            if not command:
                return
            self.set(("autostart",), self.cfg["autostart"] + [{"name": name, "cmd": command, "enabled": True}])
            self.fill_autostart()
            dlg.close()

        box.append(search)
        box.append(Gtk.ScrolledWindow(child=lb, vexpand=True))
        box.append(Gtk.ListBox(css_classes=["boxed-list"]))
        box.get_last_child().append(cmd)
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(Adw.HeaderBar())
        dlg.set_child(view)
        dlg.present(self.win)
