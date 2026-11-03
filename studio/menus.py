"""Petits menus wofi partagés (session, lanceur, confirmations)."""
import os
import subprocess
import sys
from pathlib import Path

from i18n import tr

MENU_CONF = Path.home() / ".config" / "wofi" / "menu.conf"


def dmenu(items, prompt="", height=None):
    """Affiche une liste wofi ; renvoie la ligne choisie ou None.

    wofi peut se fermer sur perte de focus en renvoyant la ligne surlignée :
    seul un code retour 0 compte comme un vrai choix.
    """
    env = dict(os.environ, GDK_BACKEND="wayland")
    cmd = ["wofi", "--conf", str(MENU_CONF), "--prompt", prompt]
    if height:
        cmd += ["--height", str(height)]
    done = subprocess.run(cmd, input="\n".join(items), text=True, capture_output=True, env=env)
    if done.returncode != 0:
        return None
    out = done.stdout.strip()
    return out if out in items else None


def confirm(question):
    yes = tr("Oui")
    return dmenu([yes, tr("Non")], question, height=150) == yes


def power():
    # (icône, libellé, commande, demander confirmation)
    actions = [
        ("󰌾", "Verrouiller", ["loginctl", "lock-session"], False),
        ("󰤄", "Veille", ["systemctl", "suspend"], False),
        ("󰍃", "Fermer la session", ["hyprctl", "dispatch", "hl.dsp.exit()"], True),
        ("󰜉", "Redémarrer", ["systemctl", "reboot"], True),
        ("󰐥", "Éteindre", ["systemctl", "poweroff"], True),
    ]
    labels = {f"{icon}  {tr(name)}": (tr(name), cmd, ask) for icon, name, cmd, ask in actions}
    choice = dmenu(list(labels), tr("Session"), height=290)
    if not choice:
        return
    name, cmd, ask = labels[choice]
    if ask and not confirm(tr("{action} ?", action=name)):
        return
    subprocess.Popen(cmd, start_new_session=True)


def launcher():
    subprocess.Popen(["wofi", "--show", "drun"], env=dict(os.environ, GDK_BACKEND="wayland"),
                     start_new_session=True)


if __name__ == "__main__":
    {"power": power, "launcher": launcher}.get(sys.argv[1] if len(sys.argv) > 1 else "", power)()
