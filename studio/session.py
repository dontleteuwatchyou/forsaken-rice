"""Ouverture de session : programmes au démarrage (XDG + commandes perso) et applis par défaut.

Hyprland ne lance pas les entrées ~/.config/autostart et /etc/xdg/autostart :
c'est ce module qui le fait, en respectant leurs règles (OnlyShowIn, Hidden…).
"""
import configparser
import os
import shutil
import subprocess
import sys
from pathlib import Path

DESKTOP = "Hyprland"
USER_DIR = Path.home() / ".config" / "autostart"
SYS_DIRS = [Path("/etc/xdg/autostart")]


# ------------------------------------------------------------ démarrage XDG
def _read(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
        return dict(cp["Desktop Entry"])
    except (configparser.Error, KeyError, UnicodeDecodeError):
        return None


def _applies(e):
    """L'entrée concerne-t-elle ce bureau ? (indépendamment de Hidden)"""
    only = [x for x in e.get("OnlyShowIn", "").split(";") if x]
    if only and DESKTOP not in only:
        return False
    if DESKTOP in e.get("NotShowIn", "").split(";"):
        return False
    if e.get("X-GNOME-HiddenUnderSystemd", "").lower() == "true":
        return False
    cond = e.get("AutostartCondition", "")
    if cond.startswith("GSettings "):
        _, schema, key = cond.split(None, 2)
        r = subprocess.run(["gsettings", "get", schema, key], capture_output=True, text=True)
        if r.stdout.strip() != "true":
            return False
    elif cond:
        return False  # condition inconnue : prudence
    tryexec = e.get("TryExec")
    if tryexec and not shutil.which(tryexec):
        return False
    return bool(e.get("Exec"))


def xdg_entries():
    """Entrées de démarrage qui concernent Hyprland. L'utilisateur peut masquer celles du système."""
    files = {}
    for d in SYS_DIRS + [USER_DIR]:  # ~/.config/autostart l'emporte (même nom de fichier)
        if d.is_dir():
            for f in sorted(d.glob("*.desktop")):
                files[f.name] = f
    out = []
    for name, path in files.items():
        e = _read(path)
        if not e or not _applies(e):
            continue
        out.append({"id": name, "path": str(path), "name": e.get("Name", name), "exec": e["Exec"],
                    "enabled": e.get("Hidden", "false").lower() != "true",
                    "system": not str(path).startswith(str(USER_DIR))})
    return out


def set_xdg_enabled(entry_id, enabled):
    """Écrit (ou met à jour) la copie utilisateur avec Hidden=…, sans toucher au fichier système."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    user = USER_DIR / entry_id
    if not user.exists():
        src = next((d / entry_id for d in SYS_DIRS if (d / entry_id).exists()), None)
        if src:
            shutil.copy(src, user)
    lines = user.read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines if not l.startswith("Hidden=")]
    i = next((n for n, l in enumerate(lines) if l.strip() == "[Desktop Entry]"), 0)
    lines.insert(i + 1, f"Hidden={'false' if enabled else 'true'}")
    user.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _exec_line(e):
    """Retire les codes de champ (%U, %f…) d'une ligne Exec."""
    import shlex
    return [a for a in shlex.split(e) if not (len(a) == 2 and a.startswith("%"))]


def _spawn(argv):
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, cwd=str(Path.home()))
    except (FileNotFoundError, PermissionError):
        pass


def start():
    """Appelé une fois à l'ouverture de session (hyprland.lua)."""
    sys.path.insert(0, str(Path(__file__).parent))
    import bots
    import core
    for e in xdg_entries():
        if e["enabled"]:
            _spawn(_exec_line(e["exec"]))
    for a in core.load()["autostart"]:
        if a.get("enabled", True) and a.get("cmd"):
            _spawn(["/bin/sh", "-c", a["cmd"]])
    bots.autostart()


# ------------------------------------------------------------ applis par défaut
CATEGORIES = {
    "navigateur": ("Navigateur web", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    "fichiers":   ("Fichiers", ["inode/directory"]),
    "mail":       ("Mail", ["x-scheme-handler/mailto"]),
    "video":      ("Vidéos", ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo"]),
    "musique":    ("Musique", ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4"]),
    "images":     ("Images", ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]),
    "pdf":        ("Documents PDF", ["application/pdf"]),
    "texte":      ("Texte et code", ["text/plain", "text/markdown", "application/json", "text/x-python"]),
    "archives":   ("Archives", ["application/zip", "application/x-7z-compressed", "application/vnd.rar",
                                "application/x-tar", "application/zstd"]),
}
TERMINALS = ["kitty", "alacritty", "foot", "wezterm", "ghostty", "konsole", "gnome-terminal", "xfce4-terminal"]
# Raccourcis du Studio qui suivent l'appli par défaut de leur catégorie
BIND_FOR = {"navigateur": "Navigateur", "fichiers": "Fichiers", "terminal": "Terminal"}


def apps_for(cat):
    """(applis candidates, appli par défaut actuelle) pour une catégorie."""
    from gi.repository import Gio
    mimes = CATEGORIES[cat][1]
    # le 1er type définit la catégorie (https pour un navigateur, pas text/html que vim sait ouvrir)
    apps = [a for a in Gio.AppInfo.get_all_for_type(mimes[0]) if a.should_show()]
    cur = Gio.AppInfo.get_default_for_type(mimes[0], False)
    if cur and cur.get_id() not in {a.get_id() for a in apps}:
        apps.insert(0, cur)
    return apps, (cur.get_id() if cur else None)


def set_default(cat, app_id):
    from gi.repository import Gio
    app = Gio.DesktopAppInfo.new(app_id)
    for m in CATEGORIES[cat][1]:
        try:
            app.set_as_default_for_type(m)
        except Exception:
            pass
    if cat == "navigateur":
        subprocess.run(["xdg-settings", "set", "default-web-browser", app_id], stderr=subprocess.DEVNULL)


def terminals():
    return [t for t in TERMINALS if shutil.which(t)]


if __name__ == "__main__":
    {"start": start}[sys.argv[1] if len(sys.argv) > 1 else "start"]()
