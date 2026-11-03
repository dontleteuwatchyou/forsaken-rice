"""Captures d'écran (copiées dans le presse-papiers) et historique du presse-papiers."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from i18n import tr  # noqa: E402

CAPTURES = Path(subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True).stdout.strip()
                or Path.home() / "Images") / "Captures"


def notify(title, body="", icon=None):
    cmd = ["notify-send", "-a", "Studio", title, body]
    if icon:
        cmd += ["-i", icon]
    subprocess.run(cmd, stderr=subprocess.DEVNULL)


def _hypr(what):
    return json.loads(subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True).stdout or "{}")


def shot(mode="zone"):
    """zone = rectangle à la souris, fenetre = fenêtre active, ecran = écran sous la souris."""
    if mode == "zone":
        sel = subprocess.run(["slurp", "-d"], capture_output=True, text=True)
        if sel.returncode != 0:  # Échap
            return
        geo = sel.stdout.strip()
    elif mode == "fenetre":
        w = _hypr("activewindow")
        if not w:
            return
        geo = f"{w['at'][0]},{w['at'][1]} {w['size'][0]}x{w['size'][1]}"
    else:
        geo = None  # grim -o sur l'écran actif, plus bas
    CAPTURES.mkdir(parents=True, exist_ok=True)
    out = CAPTURES / time.strftime("capture-%Y%m%d-%H%M%S.png")
    cmd = ["grim"] + (["-g", geo] if geo else
                      ["-o", next(m["name"] for m in _hypr("monitors") if m.get("focused"))]) + [str(out)]
    if subprocess.run(cmd).returncode != 0:
        notify(tr("Capture ratée"))
        return
    with open(out, "rb") as f:
        subprocess.run(["wl-copy", "--type", "image/png"], stdin=f)
    notify(tr("Capture copiée"), tr("Colle-la avec Ctrl+V · {nom}", nom=out.name), str(out))


def clip():
    """Historique du presse-papiers (cliphist) dans wofi : choisir = recopier."""
    sys.path.insert(0, str(Path(__file__).parent))
    from menus import dmenu
    lines = subprocess.run(["cliphist", "list"], capture_output=True, text=True).stdout.splitlines()[:80]
    if not lines:
        notify(tr("Presse-papiers vide"))
        return
    pick = dmenu(lines, tr("Presse-papiers"))
    if pick:
        data = subprocess.run(["cliphist", "decode"], input=pick.encode(), capture_output=True).stdout
        subprocess.run(["wl-copy"], input=data)


def clip_clear():
    subprocess.run(["cliphist", "wipe"])
    notify(tr("Historique du presse-papiers vidé"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "zone"
    if cmd in ("zone", "fenetre", "ecran"):
        shot(cmd)
    else:
        {"clip": clip, "clip-clear": clip_clear}[cmd]()
