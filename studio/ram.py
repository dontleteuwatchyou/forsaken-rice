"""Mémoire : module waybar, carte graphique, et menu « fermer ce qui mange la RAM ».

Pas de « vidage de cache » : sous Linux le cache est rendu instantanément aux
applis qui en ont besoin, le vider ne fait que ralentir. Ce qui libère vraiment
de la RAM, c'est fermer les processus gourmands — c'est ce que fait le menu.
"""
import json
import os
import signal
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent))
from i18n import tr  # noqa: E402

ME = os.getuid()
# Les fermer casserait la session ou le bureau : jamais proposés.
PROTECTED = {"Hyprland", "Xwayland", "systemd", "dbus-broker", "dbus-broker-launch", "dbus-daemon",
             "pipewire", "pipewire-pulse", "wireplumber", "waybar", "hyprpaper", "hypridle", "mako",
             "xdg-desktop-portal", "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk",
             "xdg-document-portal", "xdg-permission-store", "gnome-keyring-daemon", "at-spi-bus-launcher",
             "at-spi2-registryd", "gvfsd", "uwsm", "sd-pam"}


def human(n):
    return f"{n / 1024**3:.1f} {tr('Go')}" if n >= 1024**3 else f"{n / 1024**2:.0f} {tr('Mo')}"


def apps(limit=12):
    """Processus de l'utilisateur regroupés par appli, triés par mémoire (USS si dispo, sinon RSS)."""
    groups = defaultdict(lambda: {"mem": 0, "pids": []})
    for p in psutil.process_iter(["name", "uids", "memory_info", "exe"]):
        try:
            if p.info["uids"].real != ME:
                continue
            name = Path(p.info["exe"] or "").name or p.info["name"]
            name = {"electron": p.info["name"], "python3": p.info["name"]}.get(name, name)
            if name in PROTECTED or p.info["name"] in PROTECTED or p.pid == os.getpid():
                continue
            g = groups[name]
            g["mem"] += p.info["memory_info"].rss
            g["pids"].append(p.pid)
        except (psutil.Error, AttributeError):
            continue
    return sorted(({"name": k, **v} for k, v in groups.items()), key=lambda x: -x["mem"])[:limit]


def waybar():
    vm = psutil.virtual_memory()
    used = vm.total - vm.available
    pct = used * 100 / vm.total
    top = "\n".join(f"{human(a['mem']):>8}  {a['name']}" for a in apps(6))
    sw = psutil.swap_memory()
    print(json.dumps({
        "text": f"󰘚 {used / 1024**3:.1f}G",
        "class": "critical" if pct > 92 else ("warning" if pct > 80 else ""),
        "percentage": round(pct),
        "tooltip": f"RAM {human(used)} / {human(vm.total)} ({pct:.0f} %)\n"
                   f"Swap {human(sw.used)} / {human(sw.total)}\n\n{top}\n\n" + tr("Clic : fermer une appli"),
    }, ensure_ascii=False))


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout
        u, t, mu, mt = (int(float(x)) for x in out.split(","))
    except Exception:
        print(json.dumps({"text": ""}))
        return
    print(json.dumps({"text": f"󰢮 {u}%", "class": "critical" if u > 90 or t > 83 else "",
                      "tooltip": f"GPU {u} % · {t} °C\nVRAM {mu} / {mt} {tr('Mo')}"}, ensure_ascii=False))


def dnd():
    """État du mode « Ne pas déranger » de mako, pour la barre."""
    modes = subprocess.run(["makoctl", "mode"], capture_output=True, text=True).stdout.split()
    on = "do-not-disturb" in modes
    print(json.dumps({"text": chr(0xF009B) if on else chr(0xF009A), "class": "off" if on else "",
                      "tooltip": tr("Notifications coupées — clic pour les réactiver") if on
                      else tr("Notifications actives — clic pour ne pas être dérangé")}, ensure_ascii=False))


def kill_app(a):
    for pid in a["pids"]:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def menu():
    from menus import dmenu, confirm
    lst = apps(14)
    labels = {f"{human(a['mem']):>8}   {a['name']}": a for a in lst}
    pick = dmenu(list(labels), tr("Fermer une appli"))
    if pick and confirm(tr("Fermer {nom} ({n} processus) ?", nom=labels[pick]["name"], n=len(labels[pick]["pids"]))):
        kill_app(labels[pick])


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    {"waybar": waybar, "gpu": gpu, "menu": menu, "dnd": dnd}[sys.argv[1] if len(sys.argv) > 1 else "waybar"]()
