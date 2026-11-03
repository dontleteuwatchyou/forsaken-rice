-- Config Hyprland minimale
-- Wiki : https://wiki.hypr.land/configuring/
-- Ancienne config : ~/.config/hypr/backup-2026-11-02/

pcall(require, "monitors")   -- généré par Studio (onglet Écrans) ; absent au premier lancement

---- PROGRAMMES ----
local terminal    = "kitty"
local fileManager = "nautilus"
local menu        = "wofi --show drun"
local browser     = "firefox"

---- AUTOSTART ----
local studio = os.getenv("HOME") .. "/.local/bin/"

hl.on("hyprland.start", function()
    hl.exec_cmd(studio .. "studio-apply")          -- régénère le thème
    hl.exec_cmd("env GDK_BACKEND=wayland waybar")
    hl.exec_cmd("hyprpaper")
    hl.exec_cmd("hypridle")
    hl.exec_cmd("mako")
    hl.exec_cmd("wl-paste --type text --watch cliphist store")   -- historique du presse-papiers
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
    hl.exec_cmd(studio .. "studio-session")        -- programmes au démarrage (XDG + perso) et bots
end)

---- ENVIRONNEMENT ----
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")

---- APPARENCE ----
hl.config({
    general = {
        gaps_in     = 4,
        gaps_out    = 8,
        border_size = 2,
        col = {
            active_border   = "rgba(33ccffee)",
            inactive_border = "rgba(595959aa)",
        },
        layout = "dwindle",
    },
    decoration = {
        rounding = 8,
        shadow = { enabled = false },
        blur   = { enabled = true, size = 3, passes = 1 },
    },
    animations = { enabled = true },
    dwindle = { preserve_split = true },
    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
    },
})

---- ESPACES DE TRAVAIL ----
-- 5 espaces par écran, de gauche à droite : 1-5 sur le premier, 6-10 sur le suivant…
-- La liste ECRANS vient de monitors.lua (Studio, onglet Écrans) ; vide = pas de répartition
local ecrans = ECRANS or {}
local PAR_ECRAN = 5
for e, nom in ipairs(ecrans) do
    for k = 1, PAR_ECRAN do
        local i = (e - 1) * PAR_ECRAN + k
        hl.workspace_rule({ workspace = tostring(i), monitor = nom, default = (k == 1) })
    end
end

-- Espace n° k de l'écran sous la souris (1-5 sur le premier écran, 6-10 sur le suivant…)
local function espace_ici(k)
    local m = hl.get_monitor_at_cursor()
    for e, nom in ipairs(ecrans) do
        if m and m.name == nom then return (e - 1) * PAR_ECRAN + k end
    end
    return k
end

---- CLAVIER / SOURIS ----
hl.config({
    input = {
        kb_layout    = "fr",
        follow_mouse = 1,
        sensitivity  = 0,
    },
})

---- RACCOURCIS ----
local mod = "SUPER"

-- Raccourcis d'actions : gérés dans Studio > Raccourcis (fichier binds.lua généré)
pcall(require, "binds")

-- Focus avec les flèches
hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Espaces de travail : SUPER + &é"'(-è_çà (rangée du haut AZERTY)
-- Déplacer la fenêtre : SUPER + SHIFT + même touche
local azerty = { "ampersand", "eacute", "quotedbl", "apostrophe", "parenleft",
                 "minus", "egrave", "underscore", "ccedilla", "agrave" }
-- SUPER + 1…5 : espaces de l'écran sous la souris ; SUPER + 6…0 : espace 6…10 précis
for i = 1, 10 do
    if i <= PAR_ECRAN then
        hl.bind(mod .. " + " .. azerty[i], function() hl.dispatch(hl.dsp.focus({ workspace = espace_ici(i) })) end)
        hl.bind(mod .. " + SHIFT + " .. azerty[i], function() hl.dispatch(hl.dsp.window.move({ workspace = espace_ici(i) })) end)
    else
        hl.bind(mod .. " + " .. azerty[i],         hl.dsp.focus({ workspace = i }))
        hl.bind(mod .. " + SHIFT + " .. azerty[i], hl.dsp.window.move({ workspace = i }))
    end
end

-- Molette : changer d'espace
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

-- Déplacer / redimensionner à la souris
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Son
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true })

---- RÈGLES ----
hl.window_rule({
    name  = "suppress-maximize",
    match = { class = ".*" },
    suppress_event = "maximize",
})

hl.window_rule({
    name  = "studio-flottant",
    match = { class = "fr.forsaken.Studio" },
    float = true,
    size  = "1120 800",
    center = true,
})

-- Flou sous la barre, les menus et les notifs
for _, ns in ipairs({ "waybar", "wofi", "notifications" }) do
    hl.layer_rule({
        name  = "flou-" .. ns,
        match = { namespace = "^" .. ns .. "$" },
        blur  = true,
        ignore_alpha = 0.2,
    })
end

---- THÈME (généré par Studio, SUPER+SHIFT+C) ----
pcall(require, "theme")
