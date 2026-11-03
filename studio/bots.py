"""Gestionnaire de bots : chaque bot est un service systemd --user transitoire.

systemd s'occupe du redémarrage auto (Restart=on-failure), des journaux
(journalctl) et de la mesure mémoire ; on ne garde ici que la liste.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from i18n import tr  # noqa: E402

LIST = Path.home() / ".config" / "studio" / "bots.json"


def load():
    try:
        return json.loads(LIST.read_text())
    except (OSError, ValueError):
        return []


def save(bots):
    LIST.parent.mkdir(parents=True, exist_ok=True)
    LIST.write_text(json.dumps(bots, indent=2, ensure_ascii=False))


def unit(name):
    return "studio-bot-" + re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-").lower() + ".service"


def detect(folder):
    """Devine la commande de lancement d'un projet. None si rien de reconnu."""
    d = Path(folder)
    pkg = d / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
        except ValueError:
            data = {}
        bun = (d / "bun.lockb").exists() or (d / "bun.lock").exists()
        runner = "bun" if bun and shutil.which("bun") else "node"
        if data.get("scripts", {}).get("start"):
            return "bun run start" if runner == "bun" else "npm start"
        main = data.get("main") or next((f for f in ("index.js", "bot.js", "main.js", "src/index.js")
                                         if (d / f).exists()), None)
        return f"{runner} {main}" if main else None
    py = next((f for f in ("main.py", "bot.py", "app.py", "run.py") if (d / f).exists()), None)
    if py:
        venv = next((v for v in (".venv", "venv") if (d / v / "bin" / "python").exists()), None)
        if venv:
            return f"{venv}/bin/python {py}"
        if (d / "pyproject.toml").exists() and shutil.which("uv"):
            return f"uv run {py}"
        return f"python {py}"
    return None


def _sysctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def status(bot):
    out = _sysctl("show", unit(bot["name"]), "-p", "ActiveState", "-p", "MemoryCurrent", "-p", "NRestarts").stdout
    kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    mem = kv.get("MemoryCurrent", "")
    return {
        "state": kv.get("ActiveState", "inactive"),
        "mem": int(mem) if mem.isdigit() else 0,
        "restarts": int(kv.get("NRestarts", "0") or 0),
    }


def start(bot):
    u = unit(bot["name"])
    _sysctl("stop", u)
    _sysctl("reset-failed", u)
    path = ":".join([str(Path.home() / p) for p in (".bun/bin", ".local/bin")] + [os.environ.get("PATH", "/usr/bin")])
    return subprocess.run([
        "systemd-run", "--user", "--unit", u, "--collect",
        "--property=Restart=on-failure", "--property=RestartSec=5",
        "--property=StartLimitIntervalSec=0",
        f"--working-directory={bot['dir']}", f"--setenv=PATH={path}",
        "--description", f"Bot {bot['name']}",
        "/bin/sh", "-c", bot["cmd"],
    ], capture_output=True, text=True)


def stop(bot):
    _sysctl("stop", unit(bot["name"]))


def restart(bot):
    return start(bot)


def logs(bot):
    subprocess.Popen(["kitty", "--title", f"{tr('Logs')} — {bot['name']}", "journalctl", "--user", "-u",
                      unit(bot["name"]), "-f", "-n", "300", "-o", "cat"], start_new_session=True)


def autostart():
    for b in load():
        if b.get("autostart") and status(b)["state"] != "active":
            start(b)


def human(n):
    return f"{n / 1024**3:.1f} {tr('Go')}" if n >= 1024**3 else f"{n / 1024**2:.0f} {tr('Mo')}"


def waybar():
    bots = load()
    if not bots:
        print(json.dumps({"text": "", "tooltip": "", "class": "empty"}))
        return
    rows, up, mem, failed = [], 0, 0, 0
    for b in bots:
        s = status(b)
        on = s["state"] == "active"
        up += on
        mem += s["mem"]
        failed += s["state"] == "failed"
        dot = "●" if on else ("✕" if s["state"] == "failed" else "○")
        rows.append(f"{dot}  {b['name']}" + (f"  ·  {human(s['mem'])}" if on else ""))
    cls = "down" if failed else ("on" if up else "off")
    print(json.dumps({"text": f"󰚩 {up}/{len(bots)}", "class": cls,
                      "tooltip": tr("Bots") + " — " + human(mem) + "\n" + "\n".join(rows)}, ensure_ascii=False))


def menu():
    from menus import dmenu
    bots = load()
    if not bots:
        subprocess.Popen([str(Path.home() / ".local/bin/studio"), "--page", "bots"], start_new_session=True)
        return
    labels = {}
    for b in bots:
        s = status(b)
        dot = "●" if s["state"] == "active" else ("✕" if s["state"] == "failed" else "○")
        labels[f"{dot}  {b['name']}"] = b
    manage = "󰒓  " + tr("Gérer dans Studio")
    pick = dmenu(list(labels) + [manage], tr("Bots"))
    if not pick:
        return
    if pick == manage:
        subprocess.Popen([str(Path.home() / ".local/bin/studio"), "--page", "bots"], start_new_session=True)
        return
    b = labels[pick]
    on = status(b)["state"] == "active"
    acts = ([("󰜉", "Redémarrer", restart), ("󰓛", "Arrêter", stop)] if on else [("󰐊", "Démarrer", start)]) \
        + [("󰦪", "Logs", logs)]
    acts = {f"{icon}  {tr(name)}": fn for icon, name, fn in acts}
    act = dmenu(list(acts), b["name"], height=220)
    if act:
        acts[act](b)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "waybar"
    if cmd in ("start", "stop", "restart", "logs") and len(sys.argv) > 2:
        b = next((x for x in load() if x["name"] == sys.argv[2]), None)
        if not b:
            sys.exit(tr("bot inconnu : {nom}", nom=sys.argv[2]))
        r = globals()[cmd](b)
        if getattr(r, "returncode", 0):
            sys.exit(r.stderr)
    elif cmd == "list":
        for b in load():
            s = status(b)
            print(f"{s['state']:9} {human(s['mem']):>8}  {b['name']:20} {b['dir']}  ({b['cmd']})")
    else:
        {"waybar": waybar, "menu": menu, "autostart": autostart}[cmd]()
