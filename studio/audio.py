"""Son : sortie et micro par défaut, volume, muet (via pactl, compatible PipeWire).

On ne fait que changer le DÉFAUT : sous PipeWire, seuls les flux qui suivent le
défaut basculent. Jamais de move-sink-input global, ça casserait un routage
manuel (ex. Bitwig → sink virtuel).
"""
import json
import re
import subprocess


def _pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True)


def _label(dev):
    desc = dev.get("description") or ""
    if not desc or desc == "(null)":
        desc = dev.get("properties", {}).get("device.description", dev["name"])
    return re.sub(r"\s+", " ", desc).strip()


def devices(kind):
    """kind = 'sink' (sorties) ou 'source' (micros). Les « Monitor of » sont exclus."""
    data = json.loads(_pactl("-f", "json", "list", kind + "s").stdout or "[]")
    default = _pactl("get-default-" + kind).stdout.strip()
    out = []
    for d in data:
        if kind == "source" and d.get("properties", {}).get("device.class") == "monitor":
            continue
        vols = [v["value_percent"] for v in d.get("volume", {}).values()]
        pct = int(vols[0].rstrip("%")) if vols else 0
        out.append({"name": d["name"], "label": _label(d), "volume": pct,
                    "mute": d.get("mute", False), "default": d["name"] == default})
    return out


def set_default(kind, name):
    _pactl("set-default-" + kind, name)


def set_volume(kind, name, pct):
    _pactl(f"set-{kind}-volume", name, f"{int(pct)}%")


def set_mute(kind, name, mute):
    _pactl(f"set-{kind}-mute", name, "1" if mute else "0")


def test_sound():
    for f in ("/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga",
              "/usr/share/sounds/freedesktop/stereo/bell.oga"):
        try:
            subprocess.Popen(["pw-play", f], stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
