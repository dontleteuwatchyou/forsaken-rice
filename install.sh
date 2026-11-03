#!/usr/bin/env bash
# Installe le rice forsaken : Studio (l'appli de réglages), ses scripts, et les configs de base
# (Hyprland, kitty, zsh, starship). Tout ce qui existait déjà est sauvegardé avant d'être remplacé.
#
#   ./install.sh [--lang fr|en|ru|es] [--no-deps]
set -euo pipefail
cd "$(dirname "$0")"

LANGUE=fr
DEPS=1
while [[ $# -gt 0 ]]; do
  case $1 in
    --lang) LANGUE=${2:-fr}; shift 2 ;;
    --no-deps) DEPS=0; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "? $1"; exit 1 ;;
  esac
done
[[ $LANGUE == @(fr|en|ru|es) ]] || LANGUE=fr

# ---- messages dans les 4 langues ----
declare -A M
M[fr,deps]="Paquets manquants :";             M[en,deps]="Missing packages:"
M[ru,deps]="Не хватает пакетов:";             M[es,deps]="Paquetes que faltan:"
M[fr,nodeps]="pacman introuvable : installe les dépendances à la main (voir README)."
M[en,nodeps]="pacman not found: install the dependencies by hand (see README)."
M[ru,nodeps]="pacman не найден: установи зависимости вручную (см. README)."
M[es,nodeps]="pacman no encontrado: instala las dependencias a mano (ver README)."
M[fr,backup]="Ancienne config sauvegardée dans";  M[en,backup]="Previous config saved in"
M[ru,backup]="Старая конфигурация сохранена в";   M[es,backup]="Configuración anterior guardada en"
M[fr,copy]="Copie des fichiers…";              M[en,copy]="Copying files…"
M[ru,copy]="Копирование файлов…";              M[es,copy]="Copiando archivos…"
M[fr,apply]="Génération du thème…";            M[en,apply]="Generating the theme…"
M[ru,apply]="Создание темы…";                  M[es,apply]="Generando el tema…"
M[fr,shell]="Ton shell n'est pas zsh. Pour l'utiliser :"; M[en,shell]="Your shell isn't zsh. To use it:"
M[ru,shell]="Твоя оболочка не zsh. Чтобы перейти на неё:"; M[es,shell]="Tu shell no es zsh. Para usarlo:"
M[fr,done]="C'est installé. Reconnecte-toi à Hyprland, puis ouvre Studio avec Super+Maj+C."
M[en,done]="Installed. Log back into Hyprland, then open Studio with Super+Shift+C."
M[ru,done]="Установлено. Перезайди в Hyprland, затем открой Studio через Super+Shift+C."
M[es,done]="Instalado. Vuelve a entrar en Hyprland y abre Studio con Super+Mayús+C."
t() { echo "${M[$LANGUE,$1]}"; }

# ---- dépendances (Arch et dérivées) ----
PAQUETS=(hyprland hyprpaper hypridle hyprlock waybar wofi mako kitty zsh starship
         zsh-autosuggestions zsh-syntax-highlighting zsh-history-substring-search
         python python-gobject gtk4 libadwaita python-pillow python-numpy python-psutil
         wl-clipboard cliphist grim slurp libnotify libpulse wireplumber xdg-user-dirs
         ttf-jetbrains-mono-nerd noto-fonts-cjk)
OPTIONNELS=(cava hyprsunset zoxide pavucontrol)
if (( DEPS )); then
  if command -v pacman >/dev/null; then
    mapfile -t MANQUANTS < <(pacman -T "${PAQUETS[@]}" "${OPTIONNELS[@]}" || true)
    if (( ${#MANQUANTS[@]} )); then
      echo "$(t deps) ${MANQUANTS[*]}"
      sudo pacman -S --needed "${MANQUANTS[@]}"
    fi
  else
    t nodeps
  fi
fi

# ---- sauvegarde de ce qui va être remplacé ----
SAUVE=~/.local/share/rice-backups/avant-forsaken-rice-$(date +%Y%m%d-%H%M%S)
mkdir -p "$SAUVE"
for f in .local/share/studio .config/hypr/hyprland.lua .config/kitty/kitty.conf .config/starship.toml .zshrc; do
  if [[ -e ~/$f ]]; then
    mkdir -p "$SAUVE/$(dirname "$f")"
    cp -a ~/"$f" "$SAUVE/$f"
  fi
done
echo "$(t backup) $SAUVE"

# ---- copie ----
t copy
mkdir -p ~/.local/share/studio ~/.local/bin ~/.config/hypr ~/.config/kitty ~/.config/studio
cp studio/*.py ~/.local/share/studio/
install -m 755 bin/* ~/.local/bin/
cp config/hypr/hyprland.lua ~/.config/hypr/
cp config/kitty/kitty.conf ~/.config/kitty/
cp config/starship.toml ~/.config/starship.toml
cp config/zsh/zshrc ~/.zshrc

# langue choisie (les autres réglages gardent leurs valeurs, ou celles par défaut)
python3 - "$LANGUE" <<'EOF'
import json, sys
from pathlib import Path
p = Path.home() / ".config" / "studio" / "studio.json"
try:
    cfg = json.loads(p.read_text())
except (OSError, ValueError):
    cfg = {}
cfg["lang"] = sys.argv[1]
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
EOF

t apply
~/.local/bin/studio-apply || true

if [[ $(basename "${SHELL:-}") != zsh ]]; then
  echo "$(t shell)  chsh -s /usr/bin/zsh"
fi
t done
