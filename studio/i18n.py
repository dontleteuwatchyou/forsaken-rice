"""Langue du rice : tous les textes affichés passent par tr("texte en français").

Le français sert de clé et de repli ; les traductions sont dans traductions.py.
La langue vient de ~/.config/studio/studio.json (clé « lang »), lue une fois au chargement :
les petits scripts (menus, barre, bannière) la suivent donc à chaque lancement.
"""
import json
from pathlib import Path

LANGS = {"fr": "Français", "en": "English", "ru": "Русский", "es": "Español"}
LOCALES = {"fr": "fr_FR.UTF-8", "en": "en_US.UTF-8", "ru": "ru_RU.UTF-8", "es": "es_ES.UTF-8"}
_COL = {"en": 0, "ru": 1, "es": 2}


def _saved_lang():
    try:
        lang = json.loads((Path.home() / ".config" / "studio" / "studio.json").read_text()).get("lang", "fr")
    except (OSError, ValueError):
        lang = "fr"
    return lang if lang in LANGS else "fr"


LANG = _saved_lang()


def set_lang(code):
    global LANG
    LANG = code if code in LANGS else "fr"


def locale_name():
    return LOCALES[LANG]


def tr(text, **kw):
    """Traduit un texte français ; les {champs} sont remplis ensuite, comme str.format."""
    if LANG != "fr":
        from traductions import TR
        row = TR.get(text)
        if row:
            text = row[_COL[LANG]]
    return text.format(**kw) if kw else text
