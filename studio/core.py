"""Studio — moteur de thème du bureau Hyprland.

Une seule source (~/.config/studio/studio.json) ; tout le reste en est généré :
Hyprland (theme.lua), waybar, wofi, mako, kitty, hyprlock, hypridle, hyprpaper.
"""
import colorsys
import copy
import hashlib
import json
import os
import random
import subprocess
from pathlib import Path

from i18n import LANGS, locale_name, set_lang, tr  # noqa: F401  (LANGS et set_lang servent à l'appli)

HOME = Path.home()
CONF = HOME / ".config"
STATE = CONF / "studio" / "studio.json"
SHARE = Path(__file__).resolve().parent
BIN = HOME / ".local" / "bin"
WALLDIR = HOME / "Images" / "Fonds"

# ---------------------------------------------------------------- préréglages
PRESETS = {
    "plume":      {"label": "Plume",      "accent": "#8b7cf6", "accent2": "#d08bf7", "bg": "#0c0a14", "tint": 0.6},
    "cyber":      {"label": "Cyber",      "accent": "#22d3ee", "accent2": "#a855f7", "bg": "#05070d", "tint": 0.5},
    "matrix":     {"label": "Matrix",     "accent": "#22c55e", "accent2": "#a3e635", "bg": "#040806", "tint": 0.45},
    "obsidienne": {"label": "Obsidienne", "accent": "#e8e8ec", "accent2": "#7c7c88", "bg": "#08080a", "tint": 0.0},
    "sang":       {"label": "Sang",       "accent": "#ef4444", "accent2": "#f97316", "bg": "#0b0506", "tint": 0.5},
    "ambre":      {"label": "Ambre",      "accent": "#f5a524", "accent2": "#fb7185", "bg": "#0b0805", "tint": 0.45},
    "glace":      {"label": "Glace",      "accent": "#7dd3fc", "accent2": "#c4b5fd", "bg": "#070a0e", "tint": 0.5},
    "sakura":     {"label": "Sakura",     "accent": "#f472b6", "accent2": "#a78bfa", "bg": "#0e0810", "tint": 0.55},
}

ANIMS = {
    "doux":   {"label": "Doux"},
    "rapide": {"label": "Rapide"},
    "rebond": {"label": "Rebond"},
    "aucune": {"label": "Aucune"},
}

# Actions possibles pour un raccourci : id -> (libellé, Lua, besoin d'une commande ?)
ACTIONS = {
    "close":      ("Fermer la fenêtre", "hl.dsp.window.close()", False),
    "kill":       ("Tuer la fenêtre (forcer)", "hl.dsp.window.kill()", False),
    "fullscreen": ("Plein écran", "hl.dsp.window.fullscreen()", False),
    "float":      ("Fenêtre flottante / en mosaïque", 'hl.dsp.window.float({ action = "toggle" })', False),
    "split":      ("Changer le sens de découpe", 'hl.dsp.layout("togglesplit")', False),
    "exec":       ("Lancer une commande", None, True),
    "exit":       ("Quitter Hyprland", "hl.dsp.exit()", False),
}
_S = str(Path.home() / ".local" / "bin") + "/"
DEFAULT_BINDS = [
    {"keys": "SUPER + Return",    "action": "exec", "arg": "kitty", "label": "Terminal"},
    {"keys": "SUPER + Q",         "action": "close"},
    {"keys": "SUPER + C",         "action": "close"},
    {"keys": "SUPER + D",         "action": "exec", "arg": "wofi --show drun", "label": "Lanceur d'applis"},
    {"keys": "SUPER + R",         "action": "exec", "arg": "wofi --show drun", "label": "Lanceur d'applis"},
    {"keys": "SUPER + E",         "action": "exec", "arg": "nautilus", "label": "Fichiers"},
    {"keys": "SUPER + B",         "action": "exec", "arg": "firefox", "label": "Navigateur"},
    {"keys": "SUPER + SHIFT + V", "action": "float"},
    {"keys": "SUPER + V",         "action": "exec", "arg": _S + "studio-clip", "label": "Historique du presse-papiers"},
    {"keys": "Print",             "action": "exec", "arg": _S + "studio-shot zone", "label": "Capture d'une zone"},
    {"keys": "SUPER + SHIFT + S", "action": "exec", "arg": _S + "studio-shot zone", "label": "Capture d'une zone"},
    {"keys": "SHIFT + Print",     "action": "exec", "arg": _S + "studio-shot ecran", "label": "Capture de l'écran"},
    {"keys": "ALT + Print",       "action": "exec", "arg": _S + "studio-shot fenetre", "label": "Capture de la fenêtre"},
    {"keys": "SUPER + F",         "action": "fullscreen"},
    {"keys": "SUPER + J",         "action": "split"},
    {"keys": "SUPER + SHIFT + M", "action": "exit"},
    {"keys": "SUPER + SHIFT + C", "action": "exec", "arg": _S + "studio", "label": "Studio"},
    {"keys": "SUPER + L",         "action": "exec", "arg": "loginctl lock-session", "label": "Verrouiller"},
    {"keys": "SUPER + X",         "action": "exec", "arg": _S + "studio-menu power", "label": "Menu session"},
    {"keys": "SUPER + SHIFT + B", "action": "exec", "arg": _S + "studio-bots menu", "label": "Menu des bots"},
    {"keys": "SUPER + SHIFT + R", "action": "exec", "arg": _S + "studio-ram menu", "label": "Menu RAM"},
]

DEFAULTS = {
    "preset": "plume",
    **{k: PRESETS["plume"][k] for k in ("accent", "accent2", "bg", "tint")},
    "font": "Inter",
    "mono": "JetBrainsMono Nerd Font",
    "font_size": 13,
    "win": {
        "rounding": 14, "gap_in": 5, "gap_out": 12, "border": 2,
        "gradient": True, "angle": 45,
        "blur": True, "blur_size": 8, "blur_passes": 3,
        "opacity_active": 1.0, "opacity_inactive": 0.94, "dim_inactive": 0.10,
        "shadow": True, "glow": False, "anim": "doux",
    },
    "bar": {
        "position": "top", "height": 36, "style": "iles",
        "ws_style": "points",
        "modules": {"mpris": True, "cpu": True, "ram": True, "gpu": True, "disk": True, "actions": True,
                    "bots": True, "tray": True, "network": True, "audio": True},
    },
    "wallpaper": "",
    "wall_mode": "auto",      # auto = fond généré qui suit les couleurs, image = fond choisi
    "wall_style": "aurore",
    "wall_seed": 1,
    "idle": {"lock": 10, "screen_off": 15, "suspend": 0},
    "term_opacity": 0.92,
    "binds": DEFAULT_BINDS,
    "monitors": {},           # vide = monitors.lua laissé tel quel (importé à la 1re ouverture de l'onglet Écrans)
    "input": {
        "kb_layout": "fr", "kb_variant": "", "kb_options": "", "numlock": False,
        "repeat_delay": 600, "repeat_rate": 25,
        "sensitivity": 0.0, "accel": "", "natural_scroll": False,
        "scroll_factor": 1.0, "follow_mouse": 1, "left_handed": False,
    },
    "sunset": {"enabled": False, "temp": 4500, "start": "21:00", "end": "07:00"},
    "autostart": [],          # commandes perso lancées à l'ouverture de session
    "lang": "fr",             # fr, en, ru, es : tous les textes du rice
    "term": {
        "anim": "toile",      # animation du terminal (voir TERM_ANIMS)
        "mode": "boucle",     # boucle = panneau animé en haut de kitty ; lancement ; fixe ; aucune
        "panel": 30,          # hauteur du panneau en boucle, en % de la fenêtre
        "speed": 1.0, "size": 1.0, "fps": 20,
        "random_every": 0,    # aléatoire en boucle : changer d'animation toutes les N minutes (0 = jamais)
        "info": {"os": True, "host": False, "kernel": False, "uptime": True, "packages": False,
                 "cpu": False, "ram": True, "disk": True, "shell": False, "date": True},
    },
}

# Terminal : animations disponibles, façons de les afficher, infos possibles à côté (dans cet ordre)
import animations as _anims  # noqa: E402

TERM_ANIMS = {"aleatoire": "Aléatoire", **_anims.LABELS}
# chaque animation a ses propres réglages (OPTIONS dans animations.py) et peut entrer ou non dans l'aléatoire
DEFAULTS["term"]["opts"] = {k: {key: d for key, _l, _k, d, _e in getattr(cls, "OPTIONS", [])}
                            for k, (cls, _label) in _anims.ANIMS.items()}
DEFAULTS["term"]["random"] = {k: True for k in _anims.ANIMS}
TERM_MODES = {"boucle": "En boucle, dans un panneau en haut", "lancement": "Seulement à l'ouverture",
              "fixe": "Image fixe, sans animation", "aucune": "Rien"}
TERM_INFOS = {"os": "Système", "host": "Utilisateur et machine", "kernel": "Noyau", "uptime": "Allumé depuis",
              "packages": "Paquets installés", "cpu": "Processeur", "ram": "Mémoire", "disk": "Disque",
              "shell": "Shell", "date": "Date et heure"}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load():
    try:
        return _merge(DEFAULTS, json.loads(STATE.read_text()))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    tmp.replace(STATE)


# ---------------------------------------------------------------- couleurs
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(x))) for x in c)


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return hexc([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def lum(h):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def aa(h, alpha):
    """#rrggbb + alpha 0..1 -> rrggbbaa (format Hyprland rgba())."""
    return "%s%02x" % (h.lstrip("#"), round(alpha * 255))


def css_rgba(h, alpha):
    r, g, b = rgb(h)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def palette(cfg):
    a, a2, bg, t = cfg["accent"], cfg["accent2"], cfg["bg"], float(cfg["tint"])
    surface = mix(mix(bg, "#ffffff", 0.035), a, 0.05 * t)
    elevated = mix(mix(bg, "#ffffff", 0.07), a, 0.08 * t)
    text = mix("#f1f1f5", a, 0.05 * t)
    return {
        "accent": a, "accent2": a2, "bg": bg,
        "surface": surface, "elevated": elevated,
        "text": text, "text2": mix(text, bg, 0.38), "text3": mix(text, bg, 0.62),
        "on_accent": "#0a0a0c" if lum(a) > 0.35 else "#ffffff",
        "danger": "#f0606f", "ok": "#4ade80", "warn": "#fbbf24",
    }


# ---------------------------------------------------------------- générateurs
def gen_hypr(cfg, p):
    w = cfg["win"]
    active = (f'{{ colors = {{ "rgba({aa(p["accent"], 0.93)})", "rgba({aa(p["accent2"], 0.93)})" }}, angle = {w["angle"]} }}'
              if w["gradient"] else f'"rgba({aa(p["accent"], 0.93)})"')
    inactive = f'"rgba({aa(mix(p["bg"], "#ffffff", 0.16), 0.75)})"'
    anim = w["anim"]
    lines = [
        "-- Généré par Studio : ne pas modifier à la main (SUPER+SHIFT+C).",
        "hl.config({",
        "    general = {",
        f'        gaps_in = {w["gap_in"]}, gaps_out = {w["gap_out"]}, border_size = {w["border"]},',
        f"        col = {{ active_border = {active}, inactive_border = {inactive} }},",
        "    },",
        "    decoration = {",
        f'        rounding = {w["rounding"]}, rounding_power = 2.4,',
        f'        active_opacity = {w["opacity_active"]:.2f}, inactive_opacity = {w["opacity_inactive"]:.2f},',
        f'        dim_inactive = {str(w["dim_inactive"] > 0).lower()}, dim_strength = {w["dim_inactive"]:.2f},',
        f'        blur = {{ enabled = {str(w["blur"]).lower()}, size = {w["blur_size"]}, passes = {w["blur_passes"]},',
        "                 noise = 0.02, contrast = 1.0, brightness = 0.85, vibrancy = 0.25, popups = true },",
        f'        shadow = {{ enabled = {str(w["shadow"]).lower()}, range = 22, render_power = 3,',
        f'                   color = "rgba({aa("#000000", 0.55)})", color_inactive = "rgba({aa("#000000", 0.3)})" }},',
        f'        glow = {{ enabled = {str(w["glow"]).lower()}, range = 14, render_power = 3,',
        f'                 color = "rgba({aa(p["accent"], 0.45)})", color_inactive = "rgba(00000000)" }},',
        "    },",
        f'    animations = {{ enabled = {str(anim != "aucune").lower()} }},',
        "})",
    ]
    i = cfg["input"]
    lines += [
        "hl.config({ input = {",
        f'    kb_layout = {lua_str(i["kb_layout"])}, kb_variant = {lua_str(i["kb_variant"])}, kb_options = {lua_str(i["kb_options"])},',
        f'    numlock_by_default = {str(i["numlock"]).lower()}, repeat_delay = {i["repeat_delay"]}, repeat_rate = {i["repeat_rate"]},',
        f'    sensitivity = {i["sensitivity"]:.2f}, natural_scroll = {str(i["natural_scroll"]).lower()},'
        + (f' accel_profile = {lua_str(i["accel"])},' if i["accel"] else ""),  # vide = défaut de libinput
        f'    scroll_factor = {i["scroll_factor"]:.2f}, follow_mouse = {i["follow_mouse"]}, left_handed = {str(i["left_handed"]).lower()},',
        "} })",
    ]
    if anim != "aucune":
        speed = {"doux": 1.0, "rapide": 0.55, "rebond": 1.0}[anim]
        lines += [
            'hl.curve("st_out",   { type = "bezier", points = { {0.16, 1}, {0.3, 1} } })',
            'hl.curve("st_lin",   { type = "bezier", points = { {0, 0}, {1, 1} } })',
            'hl.curve("st_ressort", { type = "spring", mass = 1, stiffness = %s, damping = %s })'
            % (("320", "15") if anim == "rebond" else ("260", "26")),
        ]
        for leaf, sp, curve, style in (
            ("windowsIn", 4.0, "spring", "popin 85%"), ("windowsOut", 1.6, "st_lin", "popin 85%"),
            ("windowsMove", 4.0, "spring", None), ("border", 6.0, "st_out", None),
            ("fade", 3.0, "st_out", None), ("layersIn", 3.5, "st_out", "fade"),
            ("layersOut", 1.6, "st_lin", "fade"), ("workspaces", 3.2, "st_out", "slidefade 12%"),
        ):
            spd = round(sp * speed, 2)
            c = 'spring = "st_ressort"' if curve == "spring" else f'bezier = "{curve}"'
            st = f', style = "{style}"' if style else ""
            lines.append(f'hl.animation({{ leaf = "{leaf}", enabled = true, speed = {spd}, {c}{st} }})')
    return "\n".join(lines) + "\n"


def lua_str(v):
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def bind_label(b):
    return tr(b.get("label") or ACTIONS[b["action"]][0])


def gen_binds(cfg):
    out = ["-- Généré par Studio (onglet Raccourcis) : ne pas modifier à la main."]
    for b in cfg["binds"]:
        if b["action"] not in ACTIONS or not b.get("keys"):
            continue
        lua = ACTIONS[b["action"]][1] or "hl.dsp.exec_cmd(%s)" % lua_str(b.get("arg", ""))
        out.append(f'hl.bind({lua_str(b["keys"])}, {lua})  -- {bind_label(b)}')
    return "\n".join(out) + "\n"


# Icônes Nerd Font écrites en codes : les caractères privés se perdent facilement à la copie.
IC = {k: chr(v) for k, v in {
    "studio": 0xF03D8, "cpu": 0xF035B, "ram": 0xF061A, "gpu": 0xF08AE, "disk": 0xF02CA, "bots": 0xF06A9,
    "vol1": 0xF057F, "vol2": 0xF0580, "vol3": 0xF057E, "mute": 0xF075F, "casque": 0xF02CB,
    "mic": 0xF036C, "micoff": 0xF036D, "lan": 0xF06F3, "wifi": 0xF0928, "nonet": 0xF092D,
    "clip": 0xF014C, "cam": 0xF0100, "bell": 0xF009A, "belloff": 0xF009B, "power": 0xF0425,
    "play": 0xF040A, "pause": 0xF03E4, "stop": 0xF04DB, "sys": 0xF0493, "dot": 0xF0765, "ring": 0xF0766,
    "music": 0xF075A, "temp": 0xF050F, "chev": 0xF0141,
}.items()}

BAR_STYLES = {
    "iles": "Îlots flottants", "blocs": "Pastilles séparées", "capsule": "Capsule unique",
    "neon": "Néon", "pleine": "Pleine largeur", "minimal": "Minimal (texte seul)",
}
WS_STYLES = {"points": "Points", "chiffres": "Chiffres", "romains": "Chiffres romains", "kanji": "Kanji"}
_ROMAINS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
_KANJI = list("一二三四五六七八九十")


TRANSFORMS = {0: "Normal", 1: "90°", 2: "180°", 3: "270°", 4: "Miroir", 5: "Miroir + 90°", 6: "Miroir + 180°", 7: "Miroir + 270°"}


def monitor_lua(name, m):
    if not m.get("enabled", True):
        return f'hl.monitor({{ output = {lua_str(name)}, disabled = true }})'
    return (f'hl.monitor({{ output = {lua_str(name)}, mode = {lua_str(m["mode"])}, '
            f'position = "{m["x"]}x{m["y"]}", scale = {m["scale"]}, transform = {m["transform"]}, '
            f'vrr = {m.get("vrr", 0)}, bitdepth = {10 if m.get("bitdepth10") else 8} }})')


def import_monitors():
    """État actuel des écrans (hyprctl) au format Studio."""
    out = {}
    for m in json.loads(subprocess.run(["hyprctl", "monitors", "all", "-j"], capture_output=True, text=True).stdout or "[]"):
        modes = [x.removesuffix("Hz") for x in m.get("availableModes", [])]
        want = f"{m['width']}x{m['height']}@{m['refreshRate']:.2f}"
        mode = min(modes, key=lambda x: abs(float(x.split("@")[1]) - m["refreshRate"])
                   if x.startswith(f"{m['width']}x{m['height']}@") else 1e9) if modes else want
        out[m["name"]] = {
            "desc": f"{m.get('make', '')} {m.get('model', '')}".strip(), "mode": mode, "modes": modes,
            "x": m["x"], "y": m["y"], "scale": m["scale"], "transform": m["transform"],
            "vrr": int(m.get("vrr", False)), "bitdepth10": False, "enabled": not m.get("disabled", False),
        }
    return out


def screen_order(cfg):
    """Écrans allumés, de gauche à droite : 5 espaces de travail chacun (1-5 le premier, 6-10 le suivant…)."""
    return [n for _x, _y, n in sorted((m["x"], m["y"], n) for n, m in cfg["monitors"].items() if m.get("enabled", True))]


def gen_monitors(cfg):
    out = ["-- Généré par Studio (onglet Écrans) : ne pas modifier à la main."]
    for name, m in cfg["monitors"].items():
        desc = m.get("desc")
        if desc:
            out.append(f"-- {desc}")
        out.append(monitor_lua(name, m))
    out.append("-- Ordre des écrans pour les espaces de travail (lu par hyprland.lua)")
    out.append("ECRANS = { " + ", ".join(lua_str(n) for n in screen_order(cfg)) + " }")
    out.append("-- Écran branché plus tard (TV, projecteur…) : réglage automatique")
    out.append('hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })')
    return "\n".join(out) + "\n"


def gen_sunset(cfg):
    s = cfg["sunset"]
    return (f"# Généré par Studio (veilleuse)\n"
            f"profile {{\n    time = {s['end']}\n    identity = true\n}}\n"
            f"profile {{\n    time = {s['start']}\n    temperature = {s['temp']}\n}}\n")


def gen_waybar_config(cfg):
    b, m = cfg["bar"], cfg["bar"]["modules"]
    s = str(BIN) + "/"
    style = b["style"]
    ws = b.get("ws_style", "points")
    sysmods = [x for x, on in (("custom/ram", m["ram"]), ("cpu", m["cpu"]), ("custom/gpu", m["gpu"]),
                               ("disk", m.get("disk", True))) if on]
    left = ["custom/studio", "hyprland/workspaces", "hyprland/submap"]
    center = (["mpris"] if m["mpris"] else []) + ["hyprland/window"]
    right = (["privacy"]
             + (["group/actions"] if m.get("actions", True) else [])
             + (["tray"] if m["tray"] else [])
             + (["custom/bots"] if m["bots"] else [])
             + (["group/systeme"] if sysmods else [])
             + (["pulseaudio", "pulseaudio#micro"] if m["audio"] else [])
             + (["network"] if m["network"] else [])
             + ["clock", "custom/power"])
    if style == "capsule":  # tout dans une seule pilule centrée
        left, center, right = [], left + ["hyprland/window"] + right, []
    floating = style != "pleine"
    top = b["position"] == "top"
    if ws == "points":
        ws_conf = {"format": "{icon}", "format-icons": {"default": IC["ring"], "active": IC["dot"],
                                                       "urgent": IC["dot"], "empty": IC["ring"]}}
    elif ws == "chiffres":
        ws_conf = {"format": "{name}"}
    else:
        names = _ROMAINS if ws == "romains" else _KANJI
        ws_conf = {"format": "{icon}", "format-icons": {str(i + 1): n for i, n in enumerate(names)}}
    conf = {
        "layer": "top", "position": b["position"], "height": b["height"],
        "margin-top": 8 if floating and top else 0, "margin-bottom": 8 if floating and not top else 0,
        "margin-left": 12 if floating else 0, "margin-right": 12 if floating else 0,
        "spacing": 6 if style == "blocs" else 0, "reload_style_on_change": True,
        "modules-left": left, "modules-center": center, "modules-right": right,

        "custom/studio": {"format": IC["studio"], "tooltip-format": "Studio",
                          "on-click": s + "studio", "on-click-right": s + "studio-menu launcher"},
        "hyprland/workspaces": {**ws_conf, "on-click": "activate", "sort-by-number": True,
                                "persistent-workspaces": {n: list(range(i * 5 + 1, i * 5 + 6))
                                                          for i, n in enumerate(screen_order(cfg))} or {"*": 5}},
        "hyprland/window": {"format": "{title}", "max-length": 34 if style == "capsule" else 60,
                            "separate-outputs": True, "rewrite": {"": tr("Bureau")}},
        "mpris": {"format": "{status_icon}  {title}", "max-length": 40,
                  "status-icons": {"playing": IC["pause"], "paused": IC["play"], "stopped": IC["stop"]},
                  "tooltip-format": "{player} · {artist} — {title}"},
        "privacy": {"icon-size": 14},

        "group/actions": {"orientation": "inherit",
                          "modules": ["custom/clip", "custom/shot", "custom/dnd"]},
        "custom/clip": {"format": IC["clip"], "tooltip-format": tr("Presse-papiers (Super+V)"),
                        "on-click": s + "studio-clip", "on-click-right": s + "studio-clip clip-clear"},
        "custom/shot": {"format": IC["cam"], "tooltip-format": tr("Capture — clic : zone · droit : écran · milieu : fenêtre"),
                        "on-click": s + "studio-shot zone", "on-click-right": s + "studio-shot ecran",
                        "on-click-middle": s + "studio-shot fenetre"},
        "custom/dnd": {"exec": s + "studio-ram dnd", "return-type": "json", "interval": "once",
                       "signal": 9, "on-click": "makoctl mode -t do-not-disturb; pkill -RTMIN+9 waybar"},

        "tray": {"icon-size": 16, "spacing": 10, "show-passive-items": True},
        "custom/bots": {"exec": s + "studio-bots waybar", "return-type": "json", "interval": 5,
                        "on-click": s + "studio-bots menu", "on-click-right": s + "studio --page bots"},

        "group/systeme": {"orientation": "inherit", "modules": sysmods,
                          "drawer": {"transition-duration": 350, "children-class": "tiroir",
                                     "transition-left-to-right": False}},
        "custom/ram": {"exec": s + "studio-ram waybar", "return-type": "json", "interval": 3,
                       "on-click": s + "studio-ram menu", "on-click-right": s + "studio --page ram"},
        "cpu": {"format": IC["cpu"] + " {usage}%", "interval": 3, "states": {"critical": 90}},
        "custom/gpu": {"exec": s + "studio-ram gpu", "return-type": "json", "interval": 3},
        "disk": {"format": IC["disk"] + " {percentage_used}%", "path": "/", "interval": 60,
                 "tooltip-format": tr("{used} utilisés sur {total} ({free} libres)")},

        "pulseaudio": {"format": "{icon} {volume}%", "format-muted": IC["mute"], "scroll-step": 5,
                       "format-icons": {"default": [IC["vol1"], IC["vol2"], IC["vol3"]], "headphone": IC["casque"]},
                       "tooltip-format": "{desc}",
                       "on-click": "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle",
                       "on-click-right": s + "studio --page son"},
        "pulseaudio#micro": {"format": "{format_source}", "format-source": IC["mic"],
                             "format-source-muted": IC["micoff"],
                             "on-click": "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle",
                             "on-click-right": s + "studio --page son"},
        "network": {"format-ethernet": IC["lan"], "format-wifi": IC["wifi"] + " {signalStrength}%",
                    "format-disconnected": IC["nonet"],
                    "tooltip-format": "{ifname} · {ipaddr}\n↓ {bandwidthDownBytes}  ↑ {bandwidthUpBytes}",
                    "interval": 3},
        "clock": {"format": "{:%H:%M}", "format-alt": "{:%a %d %b  %H:%M}", "locale": locale_name(),
                  "tooltip-format": "<tt><small>{calendar}</small></tt>",
                  "calendar": {"mode": "month", "weeks-pos": "", "format": {
                      "today": "<span color='" + cfg["accent"] + "'><b>{}</b></span>"}}},
        "custom/power": {"format": IC["power"], "tooltip-format": tr("Session"), "on-click": s + "studio-menu power"},
    }
    return json.dumps(conf, indent=2, ensure_ascii=False)


def gen_waybar_css(cfg, p):
    b, r = cfg["bar"], cfg["win"]["rounding"]
    style = b["style"]
    rad = max(6, min(r, b["height"] // 2))
    fs = cfg["font_size"]
    A, A2, T, T2, T3 = p["accent"], p["accent2"], p["text"], p["text2"], p["text3"]
    font = cfg["mono"] if style == "neon" else cfg["font"]
    island = css_rgba(p["surface"], 0.84)
    edge = css_rgba("#ffffff", 0.07)
    mods = ("#custom-studio, #workspaces, #window, #mpris, #privacy, #actions, #tray, #custom-bots, #systeme, "
            "#pulseaudio, #network, #clock, #custom-power")

    css = f"""/* Généré par Studio — style « {BAR_STYLES.get(style, style)} » */
* {{ font-family: "{font}", "{cfg['mono']}"; font-size: {fs}px; min-height: 0; border: none; border-radius: 0; }}
window#waybar {{ background: transparent; color: {T}; }}
tooltip {{ background: {css_rgba(p['elevated'], 0.97)}; border: 1px solid {css_rgba(A, 0.3)}; border-radius: {rad}px; }}
tooltip label {{ color: {T}; padding: 2px; }}

#custom-studio {{ color: {A}; font-size: {fs + 5}px; padding: 0 12px 0 10px; }}
#custom-studio:hover {{ color: {A2}; }}
#workspaces {{ padding: 0 4px; }}
#workspaces button {{ color: {T3}; padding: 0 6px; margin: 5px 1px; background: transparent; border-radius: {rad}px;
                      transition: all 200ms ease; }}
#workspaces button.empty {{ color: {css_rgba(T3, 0.6)}; }}
#workspaces button.visible {{ color: {T2}; }}
#workspaces button.active {{ color: {A}; background: {css_rgba(A, 0.14)}; }}
#workspaces button.urgent {{ color: {p['danger']}; }}
#workspaces button:hover {{ background: {css_rgba(A, 0.10)}; color: {T}; box-shadow: none; text-shadow: none; }}
#window, #mpris {{ color: {T2}; padding: 0 12px; }}
#mpris {{ color: {A}; }}
#mpris.paused {{ color: {T3}; }}
#custom-clip, #custom-shot, #custom-dnd, #custom-bots, #custom-ram, #cpu, #custom-gpu, #disk,
#pulseaudio, #network, #clock, #custom-power, #privacy {{ padding: 0 9px; color: {T2}; }}
#tray {{ padding: 0 10px; }}
#tray > .needs-attention {{ background: {css_rgba(p['danger'], 0.25)}; border-radius: 6px; }}
#custom-clip:hover, #custom-shot:hover, #custom-dnd:hover, #custom-bots:hover, #custom-ram:hover,
#pulseaudio:hover, #network:hover, #clock:hover {{ color: {T}; }}
#custom-dnd.off {{ color: {p['warn']}; }}
#custom-ram {{ color: {T}; }}
.tiroir {{ color: {T3}; }}
#clock {{ color: {T}; font-weight: 700; }}
#custom-power {{ color: {T3}; padding-right: 12px; }}
#custom-power:hover {{ color: {p['danger']}; }}
#custom-bots.on {{ color: {A}; }}
#custom-bots.down {{ color: {p['danger']}; }}
#custom-bots.empty {{ padding: 0; }}
#cpu.critical, #custom-ram.critical, #custom-gpu.critical {{ color: {p['danger']}; }}
#custom-ram.warning {{ color: {p['warn']}; }}
#pulseaudio.muted, #pulseaudio.source-muted {{ color: {T3}; }}
#privacy-item {{ color: {p['danger']}; }}
"""
    groups = ".modules-left, .modules-center, .modules-right"
    if style == "iles":
        css += f"{groups} {{ background: {island}; border-radius: {rad}px; border: 1px solid {edge}; padding: 0 4px; }}\n"
    elif style == "blocs":
        css += f"{mods} {{ background: {island}; border-radius: {rad}px; border: 1px solid {edge}; margin: 0 2px; }}\n"
        css += f"#workspaces button {{ margin: 4px 1px; }}\n"
    elif style == "capsule":
        css += (f".modules-center {{ background: {island}; border-radius: {b['height']}px; border: 1px solid {edge};"
                f" padding: 0 8px; box-shadow: 0 4px 18px rgba(0,0,0,0.35); }}\n")
    elif style == "neon":
        css += (f"{groups} {{ background: {css_rgba(p['bg'], 0.86)}; border-radius: {rad}px;"
                f" border: 1px solid {css_rgba(A, 0.55)}; box-shadow: 0 0 10px {css_rgba(A, 0.35)}, inset 0 0 8px {css_rgba(A, 0.10)}; padding: 0 4px; }}\n"
                f"#clock, #custom-ram, #workspaces button.active {{ color: {A}; text-shadow: 0 0 6px {css_rgba(A, 0.8)}; }}\n"
                f"#workspaces button.active {{ background: transparent; }}\n"
                f"#window {{ color: {css_rgba(A2, 0.9)}; }}\n")
    elif style == "pleine":
        css += (f"window#waybar {{ background: {css_rgba(p['surface'], 0.9)};"
                f" border-{'bottom' if b['position'] == 'top' else 'top'}: 2px solid {css_rgba(A, 0.55)}; }}\n")
    elif style == "minimal":
        css += (f"* {{ text-shadow: 0 1px 4px rgba(0,0,0,0.85); }}\n"
                f"#workspaces button.active {{ background: transparent; }}\n")
    return css


def gen_wofi(cfg, p):
    r = cfg["win"]["rounding"]
    css = f"""/* Généré par Studio */
* {{ font-family: "{cfg['font']}", "{cfg['mono']}"; font-size: {cfg['font_size'] + 1}px; }}
window {{ background: {css_rgba(p['elevated'], 0.95)}; border: 1px solid {css_rgba(p['accent'], 0.30)}; border-radius: {r + 4}px; }}
#outer-box {{ padding: 12px; }}
#input {{ background: {css_rgba(p['bg'], 0.7)}; color: {p['text']}; border: 1px solid {css_rgba('#ffffff', 0.08)};
          border-radius: {r}px; padding: 9px 12px; margin-bottom: 10px; }}
#input:focus {{ border-color: {css_rgba(p['accent'], 0.6)}; }}
#entry {{ padding: 8px 10px; border-radius: {max(6, r - 4)}px; }}
#entry:selected {{ background: {css_rgba(p['accent'], 0.18)}; box-shadow: inset 0 0 0 1px {css_rgba(p['accent'], 0.45)}; }}
#text {{ color: {p['text']}; }}
#entry:selected #text {{ color: {p['text']}; }}
"""
    conf = (f"show=drun\nwidth=560\nheight=420\nprompt={tr('Rechercher')}\nallow_images=true\nimage_size=22\n"
            "insensitive=true\nno_actions=true\nhide_scroll=true\n")
    menu = ("show=dmenu\nwidth=420\nheight=360\nprompt=\ninsensitive=true\nhide_scroll=true\n"
            "cache_file=/dev/null\n")
    return css, conf, menu


def gen_mako(cfg, p):
    return f"""# Généré par Studio
font={cfg['font']} {cfg['font_size']}
background-color={p['elevated']}f2
text-color={p['text']}
border-color={p['accent']}88
border-size=1
border-radius={cfg['win']['rounding']}
padding=14
margin=14
width=380
default-timeout=6000
icons=1
max-icon-size=40
progress-color=over {p['accent']}55

[urgency=critical]
border-color={p['danger']}
default-timeout=0

[mode=do-not-disturb]
invisible=1
"""


def gen_kitty(cfg, p):
    a, a2, bg, t = p["accent"], p["accent2"], p["bg"], p["text"]
    base = ["#2a2a33", "#f0606f", "#4ade80", "#fbbf24", "#60a5fa", "#c084fc", "#22d3ee", "#c9c9d1"]
    bright = [mix(c, "#ffffff", 0.2) for c in base]
    bright[0] = "#4b4b57"
    cols = "\n".join(f"color{i} {c}" for i, c in enumerate(base + bright))
    return f"""# Généré par Studio
font_family {cfg['mono']}
font_size {cfg['font_size'] - 1}
background {bg}
foreground {t}
background_opacity {cfg['term_opacity']:.2f}
selection_background {mix(bg, a, 0.35)}
selection_foreground {t}
cursor {a}
cursor_shape beam
url_color {a2}
active_border_color {a}
active_tab_background {a}
active_tab_foreground {p['on_accent']}
inactive_tab_background {p['surface']}
inactive_tab_foreground {p['text2']}
window_padding_width 14
confirm_os_window_close 0
startup_session {"forsaken.session" if cfg["term"]["mode"] == "boucle" else "none"}
{cols}
"""


def gen_kitty_session(cfg):
    """Panneau animé en haut, shell en dessous (utilisé quand le terminal est « en boucle »)."""
    panel = max(10, min(60, int(cfg["term"]["panel"])))
    return (f"# Généré par Studio (onglet Terminal) : panneau animé en haut, shell en dessous.\n"
            f"layout splits\n"
            f"launch --title {lua_str(tr('Animation'))} {BIN / 'forsaken-banner'}\n"
            f"launch --location=hsplit --bias={100 - panel}\n"
            f"focus\n")


def gen_hyprlock(cfg, p):
    wall = current_wall(cfg) or "screenshot"
    return f"""# Généré par Studio
general {{
    hide_cursor = true
    grace = 2
}}
background {{
    monitor =
    path = {wall}
    blur_passes = 4
    blur_size = 8
    brightness = 0.45
    vibrancy = 0.2
}}
label {{
    monitor =
    text = cmd[update:1000] date +"%H:%M"
    color = rgba({aa(p['text'], 0.95)})
    font_size = 110
    font_family = {cfg['font']} Light
    position = 0, 160
    halign = center
    valign = center
}}
label {{
    monitor =
    text = cmd[update:60000] LC_TIME={locale_name()} date +"%A %d %B"
    color = rgba({aa(p['text2'], 0.95)})
    font_size = 18
    font_family = {cfg['font']}
    position = 0, 60
    halign = center
    valign = center
}}
input-field {{
    monitor =
    size = 320, 52
    outline_thickness = 2
    rounding = {cfg['win']['rounding'] + 6}
    outer_color = rgba({aa(p['accent'], 0.8)}) rgba({aa(p['accent2'], 0.8)}) 45deg
    inner_color = rgba({aa(p['surface'], 0.75)})
    font_color = rgba({aa(p['text'], 1)})
    check_color = rgba({aa(p['accent2'], 0.9)})
    fail_color = rgba({aa(p['danger'], 0.9)})
    placeholder_text = <i>{tr("Mot de passe")}</i>
    fail_text = {tr("Raté")} ($ATTEMPTS)
    dots_spacing = 0.3
    fade_on_empty = false
    position = 0, -60
    halign = center
    valign = center
}}
"""


def gen_hypridle(cfg):
    i = cfg["idle"]
    blocks = ["general {\n    lock_cmd = pidof hyprlock || hyprlock\n    before_sleep_cmd = loginctl lock-session\n"
              "    after_sleep_cmd = hyprctl dispatch 'hl.dsp.dpms({ action = \"on\" })'\n}"]
    if i["lock"]:
        blocks.append(f"listener {{\n    timeout = {i['lock'] * 60}\n    on-timeout = loginctl lock-session\n}}")
    if i["screen_off"]:
        blocks.append(f"listener {{\n    timeout = {i['screen_off'] * 60}\n"
                      "    on-timeout = hyprctl dispatch 'hl.dsp.dpms({ action = \"off\" })'\n"
                      "    on-resume = hyprctl dispatch 'hl.dsp.dpms({ action = \"on\" })'\n}")
    if i["suspend"]:
        blocks.append(f"listener {{\n    timeout = {i['suspend'] * 60}\n    on-timeout = systemctl suspend\n}}")
    return "# Généré par Studio\n" + "\n".join(blocks) + "\n"


def gen_hyprpaper(cfg):
    wall = current_wall(cfg)
    if not wall:
        return "# Généré par Studio\nsplash = false\n"
    return (f"# Généré par Studio\nsplash = false\n"
            f"wallpaper {{\n    monitor =\n    path = {wall}\n    fit_mode = cover\n}}\n")


# ---------------------------------------------------------------- fonds d'écran
WALL_STYLES = {"aurore": "Aurore", "vagues": "Vagues douces", "degrade": "Dégradé", "uni": "Couleur unie"}


def generate_wallpaper(cfg, seed=None, size=(3440, 1440), style=None, out=None):
    """Fond aux couleurs du thème. Styles : aurore, vagues, dégradé, uni."""
    import numpy as np
    from PIL import Image
    p = palette(cfg)
    style = style or cfg.get("wall_style", "aurore")
    rng = np.random.default_rng(seed)
    w, h = size
    sw, sh = w // 8, h // 8
    y, x = np.mgrid[0:sh, 0:sw]
    x, y = x / sw, y / sh * (sh / sw) * 2.4          # coordonnées ~isotropes
    bg = np.array(rgb(p["bg"]), float) / 255
    A, A2 = (np.array(rgb(c), float) / 255 for c in (p["accent"], p["accent2"]))
    img = np.zeros((sh, sw, 3)) + bg
    if style in ("aurore", "vagues"):
        cols = [p["accent"], p["accent2"], mix(p["accent"], p["accent2"], 0.5), mix(p["accent"], "#ffffff", 0.25)]
        n, width, amp = (6, (0.04, 0.12), (0.35, 0.7)) if style == "aurore" else (4, (0.18, 0.32), (0.25, 0.45))
        for i in range(n):
            c = np.array(rgb(cols[i % len(cols)]), float) / 255
            cx, cy = rng.uniform(0.0, 1.0), rng.uniform(0.25, 1.0) * y.max()
            ang = rng.uniform(-0.6, 0.6)
            dx, dy = x - cx, y - cy
            u = dx * np.cos(ang) + dy * np.sin(ang)       # le long du ruban
            v = -dx * np.sin(ang) + dy * np.cos(ang)      # à travers
            v = v + 0.06 * np.sin(u * rng.uniform(4, 9) + rng.uniform(0, 6))  # ondulation
            g = np.exp(-(u / rng.uniform(0.25, 0.55)) ** 2 - (v / rng.uniform(*width)) ** 2)
            img += g[..., None] * c * rng.uniform(*amp)
    elif style == "degrade":
        t = np.clip((x * 0.7 + y / y.max() * 0.3), 0, 1)[..., None]
        glow = (A * (1 - t) + A2 * t) * 0.55
        k = np.clip(1.15 - (y / y.max()) * 0.3 - np.abs(x - 0.5) * 0.4, 0, 1)[..., None] ** 1.5
        img = bg * (1 - k) + glow * k + bg * 0.5 * k
    if style != "uni":
        vy, vx = np.mgrid[0:sh, 0:sw]
        vig = 1 - 0.55 * (((vx / sw - 0.5) * 1.3) ** 2 + ((vy / sh - 0.45) * 1.6) ** 2)
        img = img * vig[..., None]
    img = np.clip(img, 0, 1)
    big = Image.fromarray((img * 255).astype(np.uint8)).resize(size, Image.BICUBIC)
    arr = np.asarray(big, dtype=np.int16)
    if style != "uni":
        arr = arr + rng.normal(0, 3.2, (h, w, 1)).astype(np.int16)
    WALLDIR.mkdir(parents=True, exist_ok=True)
    if out is None:
        tag = hashlib.sha1(f"{p['accent']}{p['accent2']}{p['bg']}{seed}{style}".encode()).hexdigest()[:8]
        out = WALLDIR / f"studio-{tag}.png"
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(out, compress_level=3)
    return str(out)


AUTO_DIR = HOME / ".cache" / "studio" / "fond-auto"


def auto_wall(cfg):
    """Chemin du fond « assorti » : un fichier par combinaison couleurs + style + variante."""
    p = palette(cfg)
    tag = hashlib.sha1(f"{p['accent']}{p['accent2']}{p['bg']}{cfg['wall_style']}{cfg['wall_seed']}".encode()).hexdigest()[:10]
    return AUTO_DIR / f"fond-{tag}.png"


def current_wall(cfg):
    if cfg.get("wall_mode") == "auto":
        return str(auto_wall(cfg))
    return cfg["wallpaper"]


def ensure_auto_wall(cfg):
    """Génère le fond assorti s'il n'existe pas encore, et efface les anciens."""
    path = auto_wall(cfg)
    if not path.exists():
        AUTO_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.png")
        generate_wallpaper(cfg, seed=cfg["wall_seed"], out=tmp)
        tmp.replace(path)
        for old in AUTO_DIR.glob("fond-*.png"):
            if old != path:
                old.unlink(missing_ok=True)
    return str(path)


def accent_from_image(path):
    """Couleur la plus saturée parmi les dominantes d'une image."""
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((96, 96))
    q = im.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:30]
    counts = sorted(q.getcolors(), reverse=True)
    best, score = None, -1
    for n, idx in counts:
        c = pal[idx * 3: idx * 3 + 3]
        hh, ll, ss = colorsys.rgb_to_hls(*(x / 255 for x in c))
        s = ss * (1 - abs(ll - 0.55) * 1.6) * (n ** 0.35)
        if s > score:
            best, score = (hh, ll, ss), s
    hh, ll, ss = best
    a = colorsys.hls_to_rgb(hh, 0.66, max(0.6, ss))
    a2 = colorsys.hls_to_rgb((hh + 0.12) % 1, 0.7, max(0.55, ss))
    bgc = colorsys.hls_to_rgb(hh, 0.045, min(0.5, ss))
    return hexc([x * 255 for x in a]), hexc([x * 255 for x in a2]), hexc([x * 255 for x in bgc])



# ---------------------------------------------------------------- terminal (zsh)
_BANNER = [  # « FORSAKEN » en style ANSI Shadow
    "███████╗ ██████╗ ██████╗ ███████╗ █████╗ ██╗  ██╗███████╗███╗   ██╗",
    "██╔════╝██╔═══██╗██╔══██╗██╔════╝██╔══██╗██║ ██╔╝██╔════╝████╗  ██║",
    "█████╗  ██║   ██║██████╔╝███████╗███████║█████╔╝ █████╗  ██╔██╗ ██║",
    "██╔══╝  ██║   ██║██╔══██╗╚════██║██╔══██║██╔═██╗ ██╔══╝  ██║╚██╗██║",
    "██║     ╚██████╔╝██║  ██║███████║██║  ██║██║  ██╗███████╗██║ ╚████║",
    "╚═╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝",
]


def _fg(h):
    r, g, b = rgb(h)
    return f"\x1b[38;2;{r};{g};{b}m"


def gen_banner(p):
    """Bannière en dégradé accent → accent 2 ; les traits d'ombre sont plus sombres."""
    width = max(len(l) for l in _BANNER)
    out = []
    for row, line in enumerate(_BANNER):
        buf = ""
        for i, ch in enumerate(line):
            if ch == " ":
                buf += " "
                continue
            c = mix(p["accent"], p["accent2"], (i / width) * 0.85 + row * 0.03)
            if ch != "█":
                c = mix(c, p["bg"], 0.55)
            buf += _fg(c) + ch
        out.append(buf + "\x1b[0m")
    return "\n".join(out) + "\n"


def gen_term(cfg, p):
    """Couleurs et textes du prompt zsh (sourcé par ~/.zshrc)."""
    return (f"# Généré par Studio\n"
            f"ST_IN='{tr('dans')}'\nST_NORESULT='{tr('aucun résultat')}'\nST_BANNER='{cfg['term']['mode']}'\n"
            f"ST_ACCENT='{p['accent']}'\nST_ACCENT2='{p['accent2']}'\nST_TEXT='{p['text']}'\n"
            f"ST_TEXT2='{p['text2']}'\nST_TEXT3='{p['text3']}'\nST_DANGER='{p['danger']}'\n"
            f"ST_OK='{p['ok']}'\nST_WARN='{p['warn']}'\n"
            f"ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg={p['text3']}'\n")


# ---------------------------------------------------------------- application
def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    path.write_text(text)
    return True


def _run(*cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        pass


def _running(name):
    return subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL).returncode == 0


def hypr_eval(lua):
    """Applique du Lua à chaud. Sans les commentaires : une ligne « -- » serait prise pour une option."""
    code = "\n".join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    r = subprocess.run(["hyprctl", "eval", code], capture_output=True, text=True)
    return "error" not in r.stdout.lower()


def restart_waybar():
    subprocess.run(["pkill", "-x", "waybar"])
    _run("env", "GDK_BACKEND=wayland", "waybar")


def apply(cfg):
    """Écrit tous les fichiers et recharge ce qui a changé. Retourne la liste des cibles touchées."""
    p = palette(cfg)
    changed = []

    lua = gen_hypr(cfg, p)
    if _write(CONF / "hypr" / "theme.lua", lua):
        changed.append("hyprland")
        hypr_eval(lua)

    if cfg["monitors"] and _write(CONF / "hypr" / "monitors.lua", gen_monitors(cfg)):
        changed.append("écrans")  # appliqué en direct par l'onglet Écrans (avec confirmation)

    if _write(CONF / "hypr" / "hyprsunset.conf", gen_sunset(cfg)) or cfg["sunset"]["enabled"] != _running("hyprsunset"):
        changed.append("veilleuse")
        subprocess.run(["pkill", "-x", "hyprsunset"])
        if cfg["sunset"]["enabled"]:
            _run("hyprsunset")

    if _write(CONF / "hypr" / "binds.lua", gen_binds(cfg)):
        changed.append("raccourcis")
        subprocess.run(["hyprctl", "reload", "config-only"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    wb = [_write(CONF / "waybar" / "config.jsonc", gen_waybar_config(cfg)),
          _write(CONF / "waybar" / "style.css", gen_waybar_css(cfg, p))]
    if wb[0]:
        changed.append("waybar")
        restart_waybar()
    elif wb[1]:
        changed.append("waybar")  # reload_style_on_change s'en charge

    css, conf, menu = gen_wofi(cfg, p)
    if any([_write(CONF / "wofi" / "style.css", css), _write(CONF / "wofi" / "config", conf),
            _write(CONF / "wofi" / "menu.conf", menu)]):
        changed.append("wofi")

    if _write(CONF / "mako" / "config", gen_mako(cfg, p)):
        changed.append("mako")
        _run("makoctl", "reload")

    if any([_write(CONF / "studio" / "term.zsh", gen_term(cfg, p)),
            _write(CONF / "studio" / "banner.txt", gen_banner(p))]):
        changed.append("terminal")

    _write(CONF / "kitty" / "forsaken.session", gen_kitty_session(cfg))  # relu à chaque nouveau kitty
    if _write(CONF / "kitty" / "studio.conf", gen_kitty(cfg, p)):
        changed.append("kitty")
        _run("pkill", "-SIGUSR1", "-x", "kitty")

    if _write(CONF / "hypr" / "hyprlock.conf", gen_hyprlock(cfg, p)):
        changed.append("hyprlock")

    if _write(CONF / "hypr" / "hypridle.conf", gen_hypridle(cfg)):
        changed.append("hypridle")
        subprocess.run(["pkill", "-x", "hypridle"])
        _run("hypridle")

    if cfg.get("wall_mode") == "auto":
        ensure_auto_wall(cfg)
    if _write(CONF / "hypr" / "hyprpaper.conf", gen_hyprpaper(cfg)) or not _running("hyprpaper"):
        changed.append("fond")
        # hyprpaper relit sa conf au démarrage : le relancer est le moyen sûr de changer de fond
        subprocess.run(["pkill", "-x", "hyprpaper"])
        if current_wall(cfg):
            _run("hyprpaper")
    return changed
