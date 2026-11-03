"""Animations du terminal (Studio, onglet Terminal), dessinées en caractères dans la console.

Chaque animation est une classe Anim(cols, rows, size) avec :
  .width            colonnes réellement utilisées (au plus cols)
  .step(dt)         avance de dt secondes
  .cells(colors)    {(colonne, ligne): (caractère, couleur[, couleur de fond])}
  .close()          facultatif : libère ce qu'elle a lancé
colors = {"accent", "accent2"} (couleurs de Studio). Le décor garde des couleurs fixes ;
les « personnages » et les détails prennent les couleurs du thème.
"""
import math
import os
import random
import shutil
import subprocess

from i18n import tr

# ================================================================ outils communs
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ra, rb = rgb(a), rgb(b)
    return "#%02x%02x%02x" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


def ramp(stops, t):
    """Couleur le long d'un dégradé [(position, couleur), …]."""
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return mix(c0, c1, (t - t0) / max(1e-6, t1 - t0))
    return stops[-1][1]


GREY, GREY2, GREY3 = "#a8a4ad", "#6f6b75", "#3d3a42"   # décor : couleurs fixes, ne suivent pas Studio
WEB_SPOKE, WEB_RING = GREY, GREY2
WHITE, BLACK = "#ecebf0", "#000000"
BRAILLE = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
           (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


class Dots:
    """Dessin en points braille : 2x4 points par cellule. La dernière couleur posée dans une cellule l'emporte."""

    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.w, self.h = cols * 2, rows * 4
        self.cells = {}

    def plot(self, x, y, color):
        x, y = int(math.floor(x)), int(math.floor(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            c = self.cells.get((x // 2, y // 4))
            if c is None:
                self.cells[(x // 2, y // 4)] = [BRAILLE[(x % 2, y % 4)], color]
            else:
                c[0] |= BRAILLE[(x % 2, y % 4)]
                c[1] = color

    def line(self, x0, y0, x1, y1, color):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 1.5) + 1
        for k in range(n + 1):
            self.plot(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, color)

    def poly(self, pts, color, holes=()):
        """Polygone plein (balayage ligne par ligne). holes : points à laisser vides."""
        ys = [p[1] for p in pts]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            yc = y + 0.5
            xs = []
            for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
                if (ya <= yc < yb) or (yb <= yc < ya):
                    xs.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                for x in range(int(round(a)), int(round(b))):
                    if (x, y) not in holes:
                        self.plot(x, y, color)

    def ellipse(self, cx, cy, a, b, angle, color, holes=()):
        ca, sa = math.cos(angle), math.sin(angle)
        r = int(max(a, b)) + 2
        for y in range(int(cy) - r, int(cy) + r + 1):
            for x in range(int(cx) - r, int(cx) + r + 1):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                u, v = dx * ca + dy * sa, -dx * sa + dy * ca
                if (u / a) ** 2 + (v / b) ** 2 <= 1 and (x, y) not in holes:
                    self.plot(x, y, color)

    def out(self):
        return {k: (chr(0x2800 + m), col) for k, (m, col) in self.cells.items() if m}


def half_blocks(pixels, cols, rows):
    """{(x, y): couleur} sur une grille cols x rows*2 -> cellules en demi-blocs (▀ avec couleur de fond)."""
    out = {}
    for y in range(rows):
        for x in range(cols):
            top, bot = pixels.get((x, 2 * y)), pixels.get((x, 2 * y + 1))
            if top and bot:
                out[(x, y)] = ("█", top) if top == bot else ("▀", top, bot)
            elif top:
                out[(x, y)] = ("▀", top)
            elif bot:
                out[(x, y)] = ("▄", bot)
    return out


def options(anim, opts):
    """Réglages d'une animation : ses valeurs par défaut (OPTIONS), remplacées par celles choisies dans Studio.
    OPTIONS = [(clé, libellé, "choice" | "bool" | "num", défaut, {valeur: libellé} ou (min, max, pas, décimales))]"""
    out = {key: default for key, _label, _kind, default, _extra in getattr(anim, "OPTIONS", [])}
    out.update({k: v for k, v in (opts or {}).items() if k in out})
    return out


# ================================================================ pluie de code
class Pluie:
    """Des colonnes de signes qui tombent ; la tête brille, la traîne s'éteint."""
    SIGNS = {"kana": [chr(c) for c in range(0xFF66, 0xFF9E)] + list("012345789Z:.=*+<>¦"),
             "binaire": list("01"), "hexa": list("0123456789ABCDEF"), "lettres": list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
    OPTIONS = [("signes", "Signes", "choice", "kana",
                {"kana": "Japonais", "binaire": "Binaire (0 et 1)", "hexa": "Hexadécimal", "lettres": "Lettres"}),
               ("densite", "Densité", "num", 0.75, (0.2, 1.0, 0.05, 2))]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.width, self.rows = cols, rows
        self.GLYPHS = self.SIGNS.get(o["signes"], self.SIGNS["kana"])
        self.glyph = {}
        self.drops = [self._new(x, True) for x in range(cols) if random.random() < float(o["densite"])]

    def _new(self, x, anywhere=False):
        top = random.uniform(-self.rows, self.rows) if anywhere else random.uniform(-self.rows * 1.2, -1)
        return {"x": x, "y": top, "v": random.uniform(5, 15), "len": random.randint(4, max(5, int(self.rows * 1.2)))}

    def _ch(self, x, y):
        g = self.glyph.get((x, y))
        if g is None:
            g = self.glyph[(x, y)] = random.choice(self.GLYPHS)
        return g

    def step(self, dt):
        for i, d in enumerate(self.drops):
            d["y"] += d["v"] * dt
            if d["y"] - d["len"] > self.rows:
                self.drops[i] = self._new(d["x"])
        for _ in range(max(1, int(self.width * self.rows * dt * 0.4))):   # quelques signes changent
            self.glyph[(random.randrange(self.width), random.randrange(self.rows))] = random.choice(self.GLYPHS)

    def cells(self, colors):
        a, a2 = colors["accent"], colors["accent2"]
        head = mix(a, WHITE, 0.75)
        out = {}
        for d in self.drops:
            hy = int(d["y"])
            for k in range(d["len"]):
                y = hy - k
                if 0 <= y < self.rows:
                    t = k / d["len"]
                    col = head if k == 0 else ramp([(0, a), (0.5, a2), (1, mix(a2, BLACK, 0.85))], t)
                    out[(d["x"], y)] = (self._ch(d["x"], y), col)
        return out


# ================================================================ feu
class Feu:
    """Des flammes qui montent du bas (propagation de chaleur), en demi-blocs, aux couleurs du thème."""

    OPTIONS = [("hauteur", "Hauteur des flammes", "num", 1.0, (0.5, 1.5, 0.1, 1))]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.width, self.rows = cols, rows
        self.h = rows * 2
        self.heat = [[0.0] * cols for _ in range(self.h)]
        self.decay = 2.0 / (self.h * 0.95 * float(o["hauteur"]))
        self.acc, self.t = 0.0, 0.0
        self.seed = [random.uniform(0, 6.28) for _ in range(3)]

    def _spread(self):
        w, h, heat = self.width, self.h, self.heat
        t = self.t
        base = heat[h - 1]
        for x in range(w):                       # le foyer respire : des langues de flamme plus ou moins hautes
            n = (math.sin(x * 0.23 + t * 1.7 + self.seed[0]) + math.sin(x * 0.071 - t * 1.1 + self.seed[1])
                 + math.sin(x * 0.53 + t * 2.9 + self.seed[2]) * 0.5) / 5 + 0.5
            base[x] = max(0.0, min(1.0, 0.25 + 1.0 * n ** 1.6 + random.uniform(-0.08, 0.08)))
        dec = self.decay
        for y in range(1, h):
            row, up = heat[y], heat[y - 1]
            for x in range(w):
                r = random.random()
                dst = x + (1 if r > 0.8 else -1 if r < 0.1 else 0)   # petit vent irrégulier
                if 0 <= dst < w:
                    v = (row[x] * 2 + row[max(0, x - 1)] + row[min(w - 1, x + 1)]) / 4   # lissé : des flammes, pas du bruit
                    up[dst] = max(0.0, v - r * dec)

    def step(self, dt):
        self.acc += dt
        self.t += dt
        while self.acc >= 1 / 30:
            self.acc -= 1 / 30
            self._spread()

    def cells(self, colors):
        a, a2 = colors["accent"], colors["accent2"]
        stops = [(0, "#120a0e"), (0.25, mix(a2, BLACK, 0.55)), (0.5, a2), (0.72, a), (0.9, mix(a, WHITE, 0.55)), (1, WHITE)]
        pal = [ramp(stops, i / 31) for i in range(32)]
        px = {}
        for y, row in enumerate(self.heat):
            for x, v in enumerate(row):
                if v > 0.06:
                    px[(x, y)] = pal[min(31, int(v * 31))]
        return half_blocks(px, self.width, self.rows)


# ================================================================ ciel nocturne
class Ciel:
    """Étoiles qui scintillent, une lune, et de temps en temps une étoile filante."""

    OPTIONS = [("filantes", "Étoiles filantes", "choice", "normales",
                {"jamais": "Jamais", "rares": "Rares", "normales": "Normales", "souvent": "Souvent"}),
               ("lune", "Lune", "bool", True, None)]
    GAPS = {"rares": (10, 25), "normales": (3, 9), "souvent": (0.8, 3)}

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.gap = self.GAPS.get(o["filantes"])
        self.show_moon = bool(o["lune"])
        self.width, self.rows, self.size = cols, rows, size
        self.t = 0.0
        self.stars = []
        for _ in range(max(6, cols * rows // 9)):
            self.stars.append({"x": random.randrange(cols), "y": random.randrange(rows),
                               "p": random.uniform(0, 6.28), "f": random.uniform(0.6, 2.5),
                               "big": random.random() < 0.12, "acc": random.random() < 0.1})
        self.shoot = None
        self.next_shoot = random.uniform(1.5, 5)
        r = min(rows * 1.7, cols * 0.5) * size
        self.moon = (cols * 2 * 0.78, rows * 2, r)

    def step(self, dt):
        self.t += dt
        if self.shoot:
            s = self.shoot
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            s["life"] -= dt
            if s["life"] <= 0:
                self.shoot = None
        elif self.gap:
            self.next_shoot -= dt
            if self.next_shoot <= 0:
                self.next_shoot = random.uniform(*self.gap)
                left = random.random() < 0.5
                self.shoot = {"x": random.uniform(self.width * 0.2, self.width * 0.9) if left else random.uniform(0, self.width * 0.6),
                              "y": random.uniform(0, self.rows * 0.3), "vx": (-1 if left else 1) * random.uniform(30, 50),
                              "vy": random.uniform(8, 14), "life": random.uniform(0.5, 0.9), "trail": []}

    def cells(self, colors):
        out = {}
        mx, my, mr = self.moon
        for s in self.stars:
            b = 0.5 + 0.5 * math.sin(s["p"] + self.t * s["f"])
            if s["acc"]:
                col = mix(GREY3, colors["accent"], b)
            else:
                col = mix(GREY3, WHITE, 0.25 + 0.75 * b)
            ch = ("✦" if b > 0.8 else "+" if b > 0.45 else "·") if s["big"] else ("•" if b > 0.85 else "·")
            if not self.show_moon or math.hypot(s["x"] * 2 + 1 - mx, s["y"] * 4 + 2 - my) > mr + 3:
                out[(s["x"], s["y"])] = (ch, col)                              # pas d'étoile devant la lune
        d = Dots(self.width, self.rows)
        lune = "#e8e2cf"
        for y in range(int(my - mr) - 1, int(my + mr) + 2) if self.show_moon else ():
            for x in range(int(mx - mr) - 1, int(mx + mr) + 2):
                if math.hypot(x + 0.5 - mx, y + 0.5 - my) <= mr and math.hypot(x + 0.5 - mx + mr * 0.45, y + 0.5 - my + mr * 0.2) > mr * 0.9:
                    d.plot(x, y, lune)                    # croissant : un disque moins un disque décalé
        out.update(d.out())
        s = self.shoot
        if s:
            for k in range(8):                        # traînée qui s'éteint
                x = int(s["x"] - s["vx"] * k * 0.025)
                y = int(s["y"] - s["vy"] * k * 0.025)
                if 0 <= x < self.width and 0 <= y < self.rows:
                    out[(x, y)] = ("✦" if k == 0 else "·" if k > 3 else "•",
                                   WHITE if k == 0 else mix(colors["accent"], BLACK, k / 9))
        return out


# ================================================================ neige
class Neige:
    """Des flocons qui tombent en dérivant et s'entassent en bas ; le tas fond doucement quand il est trop haut."""
    FLAKES = ["·", "·", "∗", "*", "❄", "❅", "❆"]

    OPTIONS = [("intensite", "Quantité de neige", "num", 1.0, (0.3, 2.5, 0.1, 1)),
               ("tas", "La neige s'entasse en bas", "bool", True, None)]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.width, self.rows = cols, rows
        self.t = 0.0
        self.pile_on = bool(o["tas"])
        self.pile = [0.0] * cols                      # hauteur du tas, en huitièmes de cellule
        self.flakes = [self._new(True) for _ in range(max(4, int(cols * rows / 14 * float(o["intensite"]))))]

    def _new(self, anywhere=False):
        depth = random.random()                      # 0 = loin (petit, lent), 1 = près
        return {"x": random.uniform(0, self.width), "y": random.uniform(0, self.rows) if anywhere else random.uniform(-3, 0),
                "v": 1.2 + depth * 3.5, "p": random.uniform(0, 6.28), "d": depth,
                "ch": self.FLAKES[min(len(self.FLAKES) - 1, int(depth * len(self.FLAKES)))],
                "acc": random.random() < 0.08}

    def step(self, dt):
        self.t += dt
        for i, f in enumerate(self.flakes):
            f["y"] += f["v"] * dt
            f["x"] += math.sin(self.t * 1.3 + f["p"]) * dt * 1.2 + dt * 0.6
            x = int(f["x"]) % self.width
            ground = self.rows - self.pile[x] / 8
            if f["y"] >= ground:
                if self.pile_on:
                    self.pile[x] += 1.5 + f["d"]
                self.flakes[i] = self._new()
        p = self.pile
        for x in range(self.width):                   # la neige glisse vers les colonnes plus basses
            for nx in (x - 1, x + 1):
                if 0 <= nx < self.width and p[x] - p[nx] > 6:
                    p[x] -= 1
                    p[nx] += 1
        if sum(p) / self.width > self.rows * 8 * 0.3:   # trop haut : ça fond
            for x in range(self.width):
                p[x] = max(0.0, p[x] - dt * 3)

    def cells(self, colors):
        out = {}
        for f in self.flakes:
            x, y = int(f["x"]) % self.width, int(f["y"])
            if 0 <= y < self.rows:
                col = colors["accent"] if f["acc"] else mix(GREY2, WHITE, f["d"])
                out[(x, y)] = (f["ch"], col)
        blocks = " ▁▂▃▄▅▆▇█"
        for x, h in enumerate(self.pile):
            h = int(h)
            full, part = divmod(h, 8)
            for k in range(full):
                if self.rows - 1 - k >= 0:
                    out[(x, self.rows - 1 - k)] = ("█", mix(WHITE, GREY, k / max(1, self.rows) * 0.6))
            if part and self.rows - 1 - full >= 0:
                out[(x, self.rows - 1 - full)] = (blocks[part], WHITE)
        return out


# ================================================================ toile d'araignée
# Dessinée en braille : chaque cellule fait 2x4 points (carrés), ce qui donne des fils fins.
SPOKES = [-8, 36, 90, 133, 178, 222, 268, 316]      # angles irréguliers : plus naturel
RINGS = [0.16, 0.3, 0.45, 0.6, 0.76, 0.92]
SAG = 0.13                                          # les fils entre deux rayons s'affaissent vers le centre
STRETCH = 1.12                                      # toile un peu plus large que haute


class Web:
    def __init__(self, rows):
        self.rows = rows
        self.radius = rows * 2 - 1                  # en points
        self.cols = math.ceil(self.radius * STRETCH * 1.2) + 1
        self.cx, self.cy = self.cols, rows * 2      # centre, en points
        self.cells = {}                             # (col, ligne) -> [masque braille, est un rayon]
        self._lengths = {}
        for i in range(len(SPOKES)):
            for s in range(int(self.radius * 4)):
                self._plot(*self.spoke_point(i, s / (self.radius * 3)), True)
        for r in RINGS:
            n = int(self.radius * 6 * r) + 2
            for i in range(len(SPOKES)):
                for s in range(n + 1):
                    self._plot(*self.ring_point(i, r, s / n), False)

    def _plot(self, x, y, spoke):
        x, y = int(x), int(y)
        if 0 <= x < self.cols * 2 and 0 <= y < self.rows * 4:
            c = self.cells.setdefault((x // 2, y // 4), [0, False])
            c[0] |= BRAILLE[(x % 2, y % 4)]
            c[1] |= spoke

    def spoke_point(self, i, r):
        a = math.radians(SPOKES[i])
        return self.cx + math.cos(a) * r * self.radius * STRETCH, self.cy + math.sin(a) * r * self.radius

    def ring_point(self, i, r, t):
        x0, y0 = self.spoke_point(i, r)
        x1, y1 = self.spoke_point((i + 1) % len(SPOKES), r)
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        k = 1 - SAG * math.sin(math.pi * t)
        return self.cx + (x - self.cx) * k, self.cy + (y - self.cy) * k

    # Le chemin de l'araignée : les nœuds sont les croisements (rayon i, couronne j), plus le centre.
    def neighbours(self, node):
        if node == "C":
            return [(i, 0) for i in range(len(SPOKES))]
        i, j = node
        n = [((i + 1) % len(SPOKES), j), ((i - 1) % len(SPOKES), j), "C" if j == 0 else (i, j - 1)]
        if j + 1 < len(RINGS):
            n.append((i, j + 1))
        return n

    def edge_point(self, a, b, t):
        """Point à la fraction t du fil qui va du nœud a au nœud b."""
        if a == "C" or b == "C" or a[0] == b[0]:          # le long d'un rayon
            i = b[0] if a == "C" else a[0]
            ra = 0 if a == "C" else RINGS[a[1]]
            rb = 0 if b == "C" else RINGS[b[1]]
            return self.spoke_point(i, ra + (rb - ra) * t)
        r = RINGS[a[1]]                                     # le long d'une couronne
        if b[0] == (a[0] + 1) % len(SPOKES):
            return self.ring_point(a[0], r, t)
        return self.ring_point(b[0], r, 1 - t)

    def edge_length(self, a, b):
        if (a, b) in self._lengths:
            return self._lengths[(a, b)]
        pts = [self.edge_point(a, b, s / 8) for s in range(9)]
        self._lengths[(a, b)] = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        return self._lengths[(a, b)]


# ---------------------------------------------------------------- araignée
class Spider:
    SPEED = 10          # points par seconde, en vitesse de croisière
    TURN = 2.8          # radians par seconde quand elle pivote sur place
    EASE = 0.35         # secondes pour démarrer / freiner

    def __init__(self, speed=1.0):
        self.SPEED, self.TURN = self.SPEED * speed, self.TURN * max(1.0, speed)
        self.node, self.prev, self.target = random.choice([(1, 3), (6, 2), (3, 4), "C"]), None, None
        self.t, self.pause, self.stop_after = 0.0, 0.0, False
        self.heading, self.phase, self.speed = math.pi, 0.0, 0.0
        self.pos = None

    def _tangent(self, web, t):
        a = web.edge_point(self.node, self.target, max(0.0, t - 0.02))
        b = web.edge_point(self.node, self.target, min(1.0, t + 0.02))
        return math.atan2(b[1] - a[1], b[0] - a[0])

    def _rotate_to(self, want, dt):
        """Tourne vers want à vitesse limitée ; renvoie l'écart restant."""
        turn = (want - self.heading + math.pi) % (2 * math.pi) - math.pi
        step = max(-self.TURN * dt, min(self.TURN * dt, turn))
        self.heading += step
        self.phase += abs(step) * 2.5                     # les pattes bougent aussi quand elle pivote
        return abs(turn - step)

    def step(self, web, dt):
        if self.pos is None:
            self.pos = (web.cx, web.cy) if self.node == "C" else web.spoke_point(self.node[0], RINGS[self.node[1]])
        if self.pause > 0:                                # immobile
            self.pause -= dt
            return
        if self.target is None:                           # choisit le fil suivant (sans faire demi-tour si possible)
            choices = [n for n in web.neighbours(self.node) if n != self.prev] or web.neighbours(self.node)
            self.target, self.t = random.choice(choices), 0.0
            self.stop_after = random.random() < 0.3
            self.speed = 0.0
        if self.t == 0.0 and self._rotate_to(self._tangent(web, 0.0), dt) > 0.12:
            return                                        # d'abord se tourner dans le bon sens, sur place
        turned = self.t == 0.0                            # déjà tournée sur cette image
        length = max(1.0, web.edge_length(self.node, self.target))
        left = (1 - self.t) * length                      # points restant jusqu'au nœud
        cruise = self.SPEED * (min(1.0, left / (self.SPEED * self.EASE)) if self.stop_after else 1.0)
        self.speed += (max(2.0, cruise) - self.speed) * min(1.0, dt / self.EASE * 2.5)
        self.t = min(1.0, self.t + self.speed * dt / length)
        self.phase += dt * self.speed * 0.8
        self.pos = web.edge_point(self.node, self.target, self.t)
        if not turned:
            self._rotate_to(self._tangent(web, self.t), dt)
        if self.t >= 1.0:
            self.prev, self.node, self.target = self.node, self.target, None
            if self.stop_after:
                self.pause = random.uniform(0.8, 3.0)

    def dots(self, scale):
        """Points braille de l'araignée : {(x, y): 'corps' | 'yeux'}."""
        out = {}
        px, py = round(self.pos[0] * 2) / 2, round(self.pos[1] * 2) / 2   # arrondis : la silhouette
        h = round(self.heading / math.radians(6)) * math.radians(6)        # ne scintille pas en avançant
        fx, fy = math.cos(h), math.sin(h)        # vers l'avant
        sx, sy = -fy, fx                          # vers le côté

        def at(f, s):
            return px + fx * f * scale + sx * s * scale, py + fy * f * scale + sy * s * scale

        def blob(f0, a, b):                       # ellipse pleine, a le long du corps, b en travers
            r = int(max(a, b) * scale) + 2
            cx, cy = at(f0, 0)
            for y in range(int(cy) - r, int(cy) + r + 1):
                for x in range(int(cx) - r, int(cx) + r + 1):
                    dx, dy = x + 0.5 - cx, y + 0.5 - cy
                    u, v = (dx * fx + dy * fy) / scale, (dx * sx + dy * sy) / scale
                    if (u / a) ** 2 + (v / b) ** 2 <= 1:
                        out[(x, y)] = "corps"

        def line(p, q):
            n = int(math.dist(p, q) * 2) + 1
            for k in range(n + 1):
                out.setdefault((int(p[0] + (q[0] - p[0]) * k / n), int(p[1] + (q[1] - p[1]) * k / n)), "corps")

        # pattes : 4 de chaque côté, en deux segments ; elles avancent par groupes alternés
        for side in (1, -1):
            for k, (deg, femur, tibia, bend) in enumerate(((38, 5.5, 6.5, -30), (78, 5, 5.5, -15),
                                                           (108, 5, 5.5, 15), (145, 5.5, 7, 30))):
                swing = 13 * math.sin(self.phase + (k % 2) * math.pi + (side < 0) * math.pi)
                a = math.radians(deg + swing)
                root = at(0.8 + math.cos(a) * 1.2, side * math.sin(a) * 1.4)
                knee_a = a - math.radians(bend) * 0.5
                knee = (root[0] + (fx * math.cos(knee_a) + sx * side * math.sin(knee_a)) * femur * scale,
                        root[1] + (fy * math.cos(knee_a) + sy * side * math.sin(knee_a)) * femur * scale)
                foot_a = a + math.radians(bend)
                foot = (knee[0] + (fx * math.cos(foot_a) + sx * side * math.sin(foot_a)) * tibia * scale,
                        knee[1] + (fy * math.cos(foot_a) + sy * side * math.sin(foot_a)) * tibia * scale)
                line(root, knee)
                line(knee, foot)
        blob(-5.3, 3.9, 3.1)      # abdomen
        blob(0.7, 2.1, 1.9)       # céphalothorax (avec une taille fine entre les deux)
        for s in (-0.9, 0.9):      # yeux
            x, y = at(2.6, s)
            out[(int(x), int(y))] = "yeux"
        return out


class Toile:
    """La toile d'araignée et son araignée. Toute nouvelle animation suit la même forme."""

    def __init__(self, cols, rows, size=1.0, opts=None):
        self.web = Web(rows)
        self.spider = Spider()
        self.size = size
        self.width = self.web.cols
        self.spider.step(self.web, 0)

    def step(self, dt):
        self.spider.step(self.web, dt)

    def cells(self, colors):
        """{(colonne, ligne): (caractère, couleur)}"""
        web, rows = self.web, self.web.rows
        scale = max(0.85, min(1.2, web.radius / 28)) * self.size
        sp = self.spider.dots(scale)
        cells = {k: [m, WEB_SPOKE if s else WEB_RING] for k, (m, s) in web.cells.items()}
        hit = {}
        for (x, y), kind in sp.items():
            if 0 <= x < web.cols * 2 and 0 <= y < rows * 4:
                c = (x // 2, y // 4)
                hit[c] = "yeux" if kind == "yeux" or hit.get(c) == "yeux" else "corps"
        for c in hit:                                   # l'araignée cache la toile derrière elle
            cells[c] = [0, colors["accent2"] if hit[c] == "yeux" else colors["accent"]]
        for (x, y), kind in sp.items():
            c = (x // 2, y // 4)
            if c in hit:
                cells[c][0] |= BRAILLE[(x % 2, y % 4)]
        return {k: (chr(0x2800 + m), col) for k, (m, col) in cells.items() if m}

# ================================================================ chauves-souris
LUNE = "#e8e2cf"


def draw_bat(d, x, y, flap, s, color, facing=1):
    """Chauve-souris en points : corps, oreilles, deux ailes festonnées qui battent (flap de -1 à 1)."""
    d.ellipse(x, y, 1.6 * s, 2.4 * s, math.pi / 2, color)
    d.poly([(x - 1.4 * s, y - 2 * s), (x - 1.1 * s, y - 4 * s), (x - 0.2 * s, y - 2.2 * s)], color)   # oreilles
    d.poly([(x + 1.4 * s, y - 2 * s), (x + 1.1 * s, y - 4 * s), (x + 0.2 * s, y - 2.2 * s)], color)
    for side in (1, -1):
        def P(u, v, lift):                            # lift : quelle part du battement ce point suit
            return x + side * u * s, y + (v - flap * 5 * lift) * s
        d.poly([P(1, -0.8, 0), P(5, -3.5, 0.7), P(9, -4.2, 1), P(14, -2.5, 1.1),   # bord d'attaque jusqu'au bout
                P(12, 0.2, 0.8), P(10.5, -0.6, 0.75), P(9, 2.2, 0.6),               # membrane festonnée
                P(7.5, 1, 0.5), P(5.5, 3, 0.35), P(4, 1.6, 0.25), P(1.5, 2.2, 0)], color)


class Chauves:
    """Une grosse lune, des chauves-souris qui volent devant, et parfois toute une nuée."""

    OPTIONS = [("nombre", "Nombre de chauves-souris", "num", 3, (1, 8, 1, 0)),
               ("nuees", "Une nuée passe de temps en temps", "bool", True, None)]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.width, self.rows, self.size = cols, rows, size
        self.t = 0.0
        r = min(rows * 1.85, cols * 0.55)
        self.moon = (cols * 2 * 0.62, rows * 2.05, r)
        self.bats = [self._bat() for _ in range(int(o["nombre"]))]
        self.swarm_on = bool(o["nuees"])
        self.swarm_in = random.uniform(8, 20)

    def _bat(self, swarm=False):
        d = random.choice((1, -1))
        s = (random.uniform(0.4, 0.6) if swarm else random.uniform(0.8, 1.2)) * self.size * max(0.6, self.rows / 14)
        return {"x": -20 if d > 0 else self.width * 2 + 20, "y": random.uniform(0.15, 0.85) * self.rows * 4,
                "vx": d * random.uniform(14, 24) * (1.6 if swarm else 1), "amp": random.uniform(2, 6),
                "f": random.uniform(5, 8) * (1.4 if swarm else 1), "p": random.uniform(0, 6.28), "s": s,
                "wob": random.uniform(0.5, 1.5), "swarm": swarm}

    def step(self, dt):
        self.t += dt
        for i, b in enumerate(self.bats):
            b["x"] += b["vx"] * dt
            b["p"] += b["f"] * dt
            if not -30 <= b["x"] <= self.width * 2 + 30:
                if b["swarm"]:
                    b["dead"] = True
                else:
                    self.bats[i] = self._bat()
        self.bats = [b for b in self.bats if not b.get("dead")]
        self.swarm_in -= dt
        if self.swarm_in <= 0 and self.swarm_on:
            self.swarm_in = random.uniform(20, 40)
            d = random.choice((1, -1))
            for k in range(14):
                b = self._bat(True)
                b["vx"] = d * abs(b["vx"])
                b["x"] = (-20 - k * 6) if d > 0 else (self.width * 2 + 20 + k * 6)
                self.bats.append(b)

    def cells(self, colors):
        mx, my, mr = self.moon
        bats = {}                                     # points couverts par les chauves-souris -> couleur
        for b in sorted(self.bats, key=lambda b: b["s"]):
            layer = Dots(self.width, self.rows)
            layer.plot = lambda x, y, c, L=layer: L.__dict__.setdefault("pts", set()).add((int(math.floor(x)), int(math.floor(y))))
            y = b["y"] + math.sin(self.t * b["wob"] + b["p"] * 0.1) * b["amp"]
            draw_bat(layer, b["x"], y, math.sin(b["p"]), b["s"], None)
            col = colors["accent"] if not b["swarm"] else colors["accent2"]
            for p in getattr(layer, "pts", ()):
                bats[p] = col
        # Pleine lune : les cellules entièrement dans le disque sont pleines, le bord est en points.
        # Une chauve-souris devant la lune y est dessinée dans sa couleur, sans trouer la lune.
        inside = lambda x, y: math.hypot(x + 0.5 - mx, y + 0.5 - my) <= mr   # noqa: E731
        d = Dots(self.width, self.rows)
        full = set()
        for cy in range(max(0, int((my - mr) / 4)), min(self.rows, int((my + mr) / 4) + 1)):
            for cx in range(max(0, int((mx - mr) / 2)), min(self.width, int((mx + mr) / 2) + 1)):
                dots = [(cx * 2 + i, cy * 4 + k) for i in (0, 1) for k in range(4)]
                n = sum(inside(*p) for p in dots)
                if n == 8:
                    full.add((cx, cy))
                elif n:
                    for p in dots:
                        if inside(*p):
                            d.plot(*p, LUNE)
        for (x, y), col in bats.items():
            if (x // 2, y // 4) not in full:
                d.plot(x, y, col)
        out = d.out()
        on_moon = {}
        for (x, y), col in bats.items():
            c = (x // 2, y // 4)
            if c in full:
                on_moon.setdefault(c, [0, col])[0] |= BRAILLE[(x % 2, y % 4)]
        for c in full:
            if c in on_moon:
                m, col = on_moon[c]
                out[c] = (chr(0x2800 + m), col, LUNE)
            else:
                out[c] = ("█", LUNE)
        return out


# ================================================================ corbeau
class Corbeau:
    """Un corbeau sur une branche : il cligne des yeux, regarde à gauche et à droite, croasse,
    et de temps en temps s'envole puis revient se poser."""

    OPTIONS = [("envol", "S'envole de temps en temps", "bool", True, None),
               ("croa", "Croasse", "bool", True, None)]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.can_fly, self.can_caw = bool(o["envol"]), bool(o["croa"])
        self.width, self.rows = cols, rows
        self.s = max(0.55, min(1.6, rows / 14)) * size
        self.branch_y = rows * 4 * 0.72
        self.perch_x = min(cols * 2 * 0.45, cols * 2 - 30 * self.s)
        self.x, self.y = self.perch_x, self.branch_y
        self.face = 1
        self.state, self.timer = "perche", random.uniform(10, 20)
        self.blink = 0.0
        self.caw = 0.0
        self.look_in = random.uniform(1.5, 4)
        self.flap = 0.0
        self.vx = self.vy = 0.0
        self.bob = 0.0
        self.twigs = [(random.uniform(0.1, 0.9), random.choice((-1, 1)), random.uniform(4, 9)) for _ in range(5)]

    def step(self, dt):
        self.blink = max(0.0, self.blink - dt)
        self.caw = max(0.0, self.caw - dt)
        if self.state == "perche":
            self.bob += dt
            self.look_in -= dt
            if self.look_in <= 0:
                self.look_in = random.uniform(1.5, 5)
                r = random.random()
                if r < 0.45:
                    self.face = -self.face
                elif r < 0.75:
                    self.blink = 0.18
                elif self.can_caw:
                    self.caw = 1.4
            self.timer -= dt
            if self.timer <= 0 and self.can_fly:
                self.state, self.vx, self.vy = "envol", self.face * 22 * self.s, -14 * self.s
        elif self.state == "envol":
            self.flap += dt * 9
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.vy = max(-18 * self.s, self.vy - dt * 6)
            if self.x < -30 or self.x > self.width * 2 + 30 or self.y < -25:
                self.state, self.timer = "parti", random.uniform(2, 5)
        elif self.state == "parti":
            self.timer -= dt
            if self.timer <= 0:                       # revient de l'autre côté
                self.face = random.choice((1, -1))
                self.x = -30 if self.face > 0 else self.width * 2 + 30
                self.y = self.branch_y - 30 * self.s
                self.state = "retour"
        else:                                         # retour : plane vers la branche puis se pose
            self.flap += dt * 6
            dx, dy = self.perch_x - self.x, self.branch_y - self.y
            dist = math.hypot(dx, dy)
            sp = 20 * self.s
            if dist < 1.5:
                self.x, self.y = self.perch_x, self.branch_y
                self.state, self.timer = "perche", random.uniform(8, 18)
            else:
                self.x += dx / dist * min(dist, sp * dt)
                self.y += dy / dist * min(dist, sp * dt)

    def _crow_perched(self, d, color):
        s, f = self.s, self.face
        x, y = self.x, self.y - (0.4 if math.sin(self.bob * 2.2) > 0.6 else 0) * s
        P = lambda u, v: (x + f * u * s, y + v * s)   # noqa: E731
        eye = P(8.6, -16.2)
        holes = set() if self.blink else {(int(eye[0]), int(eye[1]))}
        d.poly([P(-3, -6), P(-15, 2), P(-13, 4), P(-1, -2)], color)                 # queue
        d.ellipse(*P(1, -8), 8.5 * s, 5.2 * s, -f * 0.45 if f > 0 else math.pi + 0.45, color)   # corps
        d.ellipse(*P(7.5, -15), 3.8 * s, 3.4 * s, 0, color, holes)                   # tête
        d.poly([P(10.5, -16.5), P(16, -14.5), P(10.5, -13.2)], color)                # bec
        for u in (0, 3):                                                           # pattes
            d.line(*P(u, -3), *P(u + 0.5, 0), color)
        if self.caw:
            d.line(*P(16, -14.5), *P(14, -12.5), color)                              # bec ouvert

    def _crow_flying(self, d, color):
        s, f = self.s, (1 if self.vx >= 0 else -1) if self.state == "envol" else (1 if self.perch_x >= self.x else -1)
        x, y = self.x, self.y - 10 * s
        P = lambda u, v: (x + f * u * s, y + v * s)   # noqa: E731
        w = math.sin(self.flap)                       # 1 = ailes en haut, -1 = en bas
        d.ellipse(*P(0, 0), 8 * s, 3.2 * s, 0, color)
        d.ellipse(*P(8, -1.5), 3 * s, 2.8 * s, 0, color)
        d.poly([P(10.5, -2.5), P(15, -1), P(10.5, 0)], color)                    # bec
        d.poly([P(-6, 0), P(-15, -3), P(-16, 0), P(-15, 3)], color)              # queue en éventail
        for k, depth in ((0, 0.65), (1, 1.0)):        # aile lointaine (plus petite) puis aile proche
            lift = (w * 13 + (2 if k == 0 else 0)) * depth
            d.poly([P(4, -1), P(-4, -1), P(-9, -1 - lift * 0.8), P(-6, -1 - lift * 1.05),
                    P(-1, -1 - lift * 1.1), P(3, -1 - lift * 0.7)], color)       # plumes au bout de l'aile

    def cells(self, colors):
        d = Dots(self.width, self.rows)
        bark = "#7b6c5f"
        by = self.branch_y
        end = min(self.width * 2 - 2, self.perch_x + 34 * self.s)
        pts = [(x, by + 1 + math.sin(x * 0.05) * 1.2 + (end - x) * 0.04) for x in range(-1, int(end))]
        for x, y in pts:                              # la branche (épaisse côté tronc)
            th = 1.2 + (end - x) / max(1, end) * 2.2
            for k in range(int(th * 2) + 1):
                d.plot(x, y + k * 0.5, bark)
        for t, side, ln in self.twigs:                # rameaux
            x0 = end * t
            y0 = by + 1 + math.sin(x0 * 0.05) * 1.2 + (end - x0) * 0.04
            d.line(x0, y0, x0 + ln * 0.7, y0 + side * ln * 0.6, bark)
        if self.state == "perche":
            self._crow_perched(d, colors["accent"])
        elif self.state in ("envol", "retour"):
            self._crow_flying(d, colors["accent"])
        out = d.out()
        if self.caw and self.state == "perche":
            txt = tr("Croâ !")
            cx = int((self.x + self.face * 16 * self.s) / 2) + (1 if self.face > 0 else -len(txt) - 1)
            cy = max(0, int((self.y - 22 * self.s) / 4))
            for i, ch in enumerate(txt):
                if 0 <= cx + i < self.width:
                    out[(cx + i, cy)] = (ch, colors["accent2"])
        return out


# ================================================================ aquarium
class Aquarium:
    """Des poissons qui nagent, des bulles qui montent, des algues qui ondulent sur le sable."""
    RIGHT = ["><>", "><(((º>", "><((('>", "><))°>", ">=))>"]
    LEFT = ["<><", "<º)))><", "<')))><", "<°((><", "<((=<"]

    OPTIONS = [("poissons", "Nombre de poissons", "num", 6, (1, 25, 1, 0))]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.width, self.rows = cols, rows
        self.t = 0.0
        self.fish = [self._fish() for _ in range(int(o["poissons"]))]
        self.bubbles = []
        self.weeds = [(x, random.randint(max(2, rows // 4), max(3, rows * 2 // 3)), random.uniform(0, 6.28))
                      for x in sorted(random.sample(range(1, max(2, cols - 1)), min(max(1, cols // 9), max(1, cols - 2))))]
        self.rocks = [(random.randrange(cols), random.randint(2, 5)) for _ in range(max(1, cols // 25))]

    def _fish(self):
        k = random.randrange(len(self.RIGHT))
        d = random.choice((1, -1))
        return {"k": k, "d": d, "x": random.uniform(0, self.width - 8), "y": random.uniform(0.5, self.rows - 2.5),
                "v": random.uniform(2, 7) * (0.6 if k == 0 else 1), "turn": random.uniform(4, 15),
                "c": random.choice(("accent", "accent2", "pale"))}

    def step(self, dt):
        self.t += dt
        for f in self.fish:
            f["x"] += f["d"] * f["v"] * dt
            f["y"] += math.sin(self.t * 0.7 + f["k"] + f["x"] * 0.05) * dt * 0.4
            f["y"] = min(self.rows - 2.5, max(0.2, f["y"]))
            f["turn"] -= dt
            n = len(self.RIGHT[f["k"]])
            if f["x"] < 0 or f["x"] > self.width - n or f["turn"] <= 0:
                f["d"] = 1 if f["x"] < 0 else -1 if f["x"] > self.width - n else -f["d"]
                f["turn"] = random.uniform(5, 15)
                f["x"] = min(self.width - n, max(0, f["x"]))
            if random.random() < dt * 0.15:                 # une bulle sort de la bouche
                self.bubbles.append({"x": f["x"] + (n if f["d"] > 0 else -1), "y": f["y"], "p": random.uniform(0, 6)})
        if random.random() < dt * self.width / 25:
            self.bubbles.append({"x": random.uniform(0, self.width), "y": self.rows - 1.5, "p": random.uniform(0, 6)})
        for b in self.bubbles:
            b["y"] -= dt * 3
            b["x"] += math.sin(self.t * 3 + b["p"]) * dt * 0.8
        self.bubbles = [b for b in self.bubbles if b["y"] > -1]

    def cells(self, colors):
        out = {}
        sand, weed, rock, bubble = "#8a7d68", "#4f7a62", "#5e5964", "#9fb6cc"
        for x in range(self.width):
            out[(x, self.rows - 1)] = ("▁" if (x * 7) % 5 else "▂", sand)
        for x, h in self.rocks:
            for i in range(h):
                if 0 <= x + i < self.width:
                    out[(x + i, self.rows - 1)] = ("▆" if 0 < i < h - 1 else "▄", rock)
        for x, h, p in self.weeds:
            for k in range(h):
                sway = math.sin(self.t * 1.4 + p + k * 0.6)
                xx = x + (1 if sway > 0.55 and k > 1 else 0)
                y = self.rows - 2 - k
                if 0 <= y and 0 <= xx < self.width:
                    out[(xx, y)] = ("(" if (k + int(self.t * 1.5 + p)) % 2 else ")", weed)
        for b in self.bubbles:
            x, y = int(b["x"]), int(b["y"])
            if 0 <= x < self.width and 0 <= y < self.rows - 1:
                out[(x, y)] = ("O" if y < self.rows * 0.3 else "o" if y < self.rows * 0.65 else "°", bubble)
        for f in self.fish:
            body = (self.RIGHT if f["d"] > 0 else self.LEFT)[f["k"]]
            col = colors["accent"] if f["c"] == "accent" else colors["accent2"] if f["c"] == "accent2" else mix(colors["accent"], WHITE, 0.45)
            y = int(round(f["y"]))
            for i, ch in enumerate(body):
                x = int(f["x"]) + i
                if 0 <= x < self.width and 0 <= y < self.rows - 1:
                    out[(x, y)] = (ch, col)
        return out


# ================================================================ orage
class Orage:
    """Pluie battante en biais, éclaboussures, et des éclairs qui illuminent tout le panneau."""

    OPTIONS = [("pluie", "Quantité de pluie", "num", 1.0, (0.2, 2.5, 0.1, 1)),
               ("eclairs", "Éclairs", "choice", "normaux",
                {"jamais": "Jamais", "rares": "Rares", "normaux": "Normaux", "souvent": "Souvent"})]
    GAPS = {"rares": (10, 25), "normaux": (3, 9), "souvent": (1, 3)}

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.gap = self.GAPS.get(o["eclairs"])
        self.width, self.rows = cols, rows
        self.W, self.H = cols * 2, rows * 4
        self.drops = [self._drop(True) for _ in range(max(5, int(cols * rows / 5 * float(o["pluie"]))))]
        self.splash = []
        self.bolt, self.bolt_t, self.flash = None, 0.0, 0.0
        self.next_bolt = random.uniform(2, 6)
        self.t = 0.0

    def _drop(self, anywhere=False):
        return {"x": random.uniform(-self.H * 0.3, self.W), "y": random.uniform(0, self.H) if anywhere else random.uniform(-10, 0),
                "v": random.uniform(45, 75)}

    def _make_bolt(self):
        x, y = random.uniform(self.W * 0.15, self.W * 0.85), 0.0
        main, branches = [(x, y)], []
        while y < self.H:
            y += random.uniform(2, 5)
            x += random.uniform(-4, 4)
            main.append((x, y))
            if random.random() < 0.18:
                bx, byy, br = x, y, [(x, y)]
                for _ in range(random.randint(2, 5)):
                    byy += random.uniform(2, 4)
                    bx += random.choice((-1, 1)) * random.uniform(2, 5)
                    br.append((bx, byy))
                branches.append(br)
        return [main] + branches

    def step(self, dt):
        self.t += dt
        for i, d in enumerate(self.drops):
            d["y"] += d["v"] * dt
            d["x"] += d["v"] * 0.3 * dt
            if d["y"] >= self.H - 1:
                if random.random() < 0.35:
                    self.splash.append({"x": d["x"], "y": self.H - 2, "vx": random.uniform(-6, 6), "vy": -random.uniform(6, 12), "life": 0.25})
                self.drops[i] = self._drop()
        for s in self.splash:
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            s["vy"] += 60 * dt
            s["life"] -= dt
        self.splash = [s for s in self.splash if s["life"] > 0]
        self.flash = max(0.0, self.flash - dt)
        if self.bolt:
            self.bolt_t -= dt
            if self.bolt_t <= 0:
                self.bolt = None
        elif self.gap:
            self.next_bolt -= dt
            if self.next_bolt <= 0:
                self.bolt, self.bolt_t, self.flash = self._make_bolt(), 0.35, 0.12
                self.next_bolt = random.uniform(*self.gap)

    def cells(self, colors):
        d = Dots(self.width, self.rows)
        rain = "#7f8a9c"
        for r in self.drops:
            for k in range(6):
                d.plot(r["x"] - k * 0.3, r["y"] - k, rain if k < 4 else GREY3)
        for s in self.splash:
            d.plot(s["x"], s["y"], "#a9b4c4")
        if self.bolt and (self.bolt_t > 0.22 or int(self.bolt_t * 30) % 2):
            col = mix(colors["accent"], WHITE, 0.55)
            for path in self.bolt:
                for (x0, y0), (x1, y1) in zip(path, path[1:]):
                    d.line(x0, y0, x1, y1, col)
        out = d.out()
        for x in range(self.width):                   # nuages sombres qui défilent en haut
            n = math.sin(x * 0.21 + self.t * 0.8) + math.sin(x * 0.07 - self.t * 0.3)
            out[(x, 0)] = ("▓" if n > 0.8 else "▒" if n > -0.4 else "░", GREY3)
            if n > 0.2 and self.rows > 6:
                out.setdefault((x, 1), ("░", GREY3))
        if self.flash:
            bg = mix(colors["accent"], BLACK, 0.7)
            for y in range(self.rows):
                for x in range(self.width):
                    c = out.get((x, y))
                    out[(x, y)] = (c[0], c[1], bg) if c else (" ", None, bg)
        return out

# ================================================================ visualiseur audio
class Audio:
    """Barres qui suivent le son qui sort de l'ordi (via cava). Sans cava : une vague tranquille et un message."""
    CONF = os.path.expanduser("~/.cache/studio/cava.conf")

    OPTIONS = [("style", "Style", "choice", "barres", {"barres": "Barres", "fines": "Barres fines", "miroir": "Miroir"})]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.style = o["style"]
        self.width, self.rows = cols, rows
        self.n = max(4, cols // (2 if self.style == "fines" else 3))
        self.levels = [0.0] * self.n
        self.shown = [0.0] * self.n
        self.peaks = [0.0] * self.n
        self.t = 0.0
        self.proc, self.buf = None, b""
        if shutil.which("cava"):
            os.makedirs(os.path.dirname(self.CONF), exist_ok=True)
            with open(self.CONF, "w") as f:
                f.write(f"[general]\nbars = {self.n}\nframerate = 30\n[output]\nmethod = raw\nraw_target = /dev/stdout\n"
                        "data_format = ascii\nascii_max_range = 1000\nbar_delimiter = 59\nframe_delimiter = 10\n"
                        "channels = mono\n")
            try:
                self.proc = subprocess.Popen(["cava", "-p", self.CONF], stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                os.set_blocking(self.proc.stdout.fileno(), False)
            except OSError:
                self.proc = None

    def close(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None

    def step(self, dt):
        self.t += dt
        if self.proc:
            try:
                chunk = self.proc.stdout.read()
            except (OSError, ValueError):
                chunk = None
            if chunk:
                self.buf += chunk
                lines = self.buf.split(b"\n")
                self.buf = lines[-1]
                full = [l for l in lines[:-1] if l.strip()]
                if full:
                    vals = [int(v) for v in full[-1].decode().strip(";").split(";") if v.isdigit()]
                    if len(vals) == self.n:
                        self.levels = [v / 1000 for v in vals]
        else:                                          # pas de cava : petite vague
            self.levels = [0.12 + 0.08 * math.sin(self.t * 2 + i * 0.5) + 0.05 * math.sin(self.t * 3.3 - i * 0.9)
                           for i in range(self.n)]
        for i, v in enumerate(self.levels):
            self.shown[i] += (v - self.shown[i]) * min(1.0, dt * 18)
            self.peaks[i] = max(self.shown[i], self.peaks[i] - dt * 0.35)

    def cells(self, colors):
        out = {}
        blocks = " ▁▂▃▄▅▆▇█"
        a, a2 = colors["accent"], colors["accent2"]
        rows = self.rows - (1 if not self.proc else 0)
        if self.style == "miroir":                     # les barres partent du milieu, vers le haut et vers le bas
            mid = self.rows / 2
            for i, v in enumerate(self.shown):
                h = v * mid
                for x in (i * 3, i * 3 + 1):
                    if x >= self.width:
                        continue
                    for k in range(int(mid) + 1):
                        if k < h:
                            col = mix(a, a2, k / max(1, mid))
                            for y in (int(mid) - 1 - k, int(mid) + k):
                                if 0 <= y < self.rows:
                                    out[(x, y)] = ("█" if h - k >= 1 else "▪", col)
            if not self.proc:
                msg = tr("Installe cava pour voir ta musique : sudo pacman -S cava")
                for j, ch in enumerate(msg[: self.width]):
                    out[(j, 0)] = (ch, GREY)
            return out
        step = 2 if self.style == "fines" else 3
        for i, v in enumerate(self.shown):
            h = int(v * rows * 8)
            ph = int(self.peaks[i] * rows)
            for x in (i * step,) if step == 2 else (i * 3, i * 3 + 1):
                if x >= self.width:
                    continue
                for k in range(rows):
                    y = self.rows - 1 - k
                    col = mix(a, a2, k / max(1, rows - 1))
                    fill = h - k * 8
                    if fill >= 8:
                        out[(x, y)] = ("█", col)
                    elif fill > 0:
                        out[(x, y)] = (blocks[fill], col)
                    elif k == ph and ph > 0:
                        out[(x, y)] = ("▔", mix(a2, WHITE, 0.4))
        if not self.proc:
            msg = tr("Installe cava pour voir ta musique : sudo pacman -S cava")
            for j, ch in enumerate(msg[: self.width]):
                out[(j, 0)] = (ch, GREY)
        return out


# ================================================================ jeu de la vie
class Vie:
    """Le jeu de la vie : des cellules naissent et meurent selon leurs voisines. Relancé quand tout se fige."""

    OPTIONS = [("densite", "Densité au départ", "num", 0.28, (0.1, 0.5, 0.02, 2))]

    def __init__(self, cols, rows, size=1.0, opts=None):
        self.density = float(options(self, opts)["densite"])
        self.width, self.rows = cols, rows
        self.w, self.h = cols, rows * 2
        self.acc = 0.0
        self.seed()

    def seed(self):
        self.age = {(x, y): 1 for x in range(self.w) for y in range(self.h) if random.random() < self.density}
        self.ghost = {}
        self.history = []

    def _gen(self):
        counts = {}
        w, h = self.w, self.h
        for (x, y) in self.age:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx or dy:
                        k = ((x + dx) % w, (y + dy) % h)
                        counts[k] = counts.get(k, 0) + 1
        new = {}
        for k, n in counts.items():
            if n == 3 or (n == 2 and k in self.age):
                new[k] = self.age.get(k, 0) + 1
        self.ghost = {k: 2 for k in self.age if k not in new}
        self.age = new
        sig = hash(frozenset(new))
        self.history = (self.history + [sig])[-12:]
        if not new or self.history.count(sig) > 2 or len(new) < self.w * self.h * 0.02:
            self.seed()

    def step(self, dt):
        self.acc += dt
        while self.acc >= 1 / 9:
            self.acc -= 1 / 9
            self._gen()

    def cells(self, colors):
        a, a2 = colors["accent"], colors["accent2"]
        px = {k: mix(GREY3, a, 0.6) for k in self.ghost}
        for k, age in self.age.items():
            px[k] = a2 if age == 1 else mix(a2, a, min(1.0, age / 6))
        return half_blocks(px, self.width, self.rows)


# ================================================================ forme 3D
# Logo d'Arch Linux (contour simplifié, y vers le haut), extrudé en épaisseur
ARCH = [(0.0, 1.0), (0.22, 0.52), (0.5, -0.1), (0.92, -1.0), (0.56, -1.0), (0.44, -0.66), (0.28, -0.42),
        (0.0, -0.33), (-0.28, -0.42), (-0.44, -0.66), (-0.56, -1.0), (-0.92, -1.0), (-0.52, -0.12),
        (-0.28, -0.04), (-0.44, 0.12), (-0.22, 0.52)]


def _inside(poly, x, y):
    inside = False
    for (xa, ya), (xb, yb) in zip(poly, poly[1:] + poly[:1]):
        if (ya > y) != (yb > y) and x < xa + (y - ya) * (xb - xa) / (yb - ya):
            inside = not inside
    return inside


class Forme:
    """Une forme en 3D qui tourne, ombrée avec des caractères et éclairée aux couleurs du thème."""
    SHADES = ".,-~:;=!*#$@"
    OPTIONS = [("forme", "Forme", "choice", "arch",
                {"arch": "Logo d'Arch Linux", "tore": "Tore", "cube": "Cube", "tour": "Toutes, tour à tour"})]

    def __init__(self, cols, rows, size=1.0, opts=None):
        o = options(self, opts)
        self.rows, self.size = rows, size
        self.width = min(cols, int(rows * 2.4) + 4)
        self.K2 = 8.0
        self.A = self.B = 0.0
        self.t = 0.0
        self.shape = 0
        make = {"arch": [self._arch], "tore": [self._torus], "cube": [self._cube],
                "tour": [self._arch, self._torus, self._cube]}.get(o["forme"], [self._arch])
        self.shapes = []
        for f in make:
            pts, xr, yr, zr, spin = f()
            k = min((rows / 2 - 0.6) * (self.K2 - zr) / yr, (self.width / 2 - 1) / 2 * (self.K2 - zr) / xr)
            self.shapes.append((pts, k * size, spin))

    @staticmethod
    def _arch():
        pts, D = [], 0.2
        area = sum(xa * yb - xb * ya for (xa, ya), (xb, yb) in zip(ARCH, ARCH[1:] + ARCH[:1]))
        turn = 1 if area > 0 else -1                   # sens du contour : pour orienter les normales vers l'extérieur
        step = 0.035
        y = -1.0
        while y <= 1.0:                               # faces avant et arrière
            x = -0.95
            while x <= 0.95:
                if _inside(ARCH, x, y):
                    pts.append((x, y, -D, 0.0, 0.0, -1.0))
                    pts.append((x, y, D, 0.0, 0.0, 1.0))
                x += step
            y += step
        for (xa, ya), (xb, yb) in zip(ARCH, ARCH[1:] + ARCH[:1]):   # tranche
            ln = math.hypot(xb - xa, yb - ya)
            nx, ny = turn * (yb - ya) / ln, -turn * (xb - xa) / ln
            for k in range(int(ln / 0.025) + 1):
                t = k * 0.025 / ln
                for z in (-D, -D / 2, 0.0, D / 2, D):
                    pts.append((xa + (xb - xa) * t, ya + (yb - ya) * t, z, nx, ny, 0.0))
        return pts, 0.95, 1.08, 0.95, True

    @staticmethod
    def _torus():
        pts = []
        for i in range(0, 50):
            th = i * 2 * math.pi / 50
            ct, st = math.cos(th), math.sin(th)
            for j in range(0, 120):
                ph = j * 2 * math.pi / 120
                cp, sp = math.cos(ph), math.sin(ph)
                cx = 2 + ct
                pts.append((cx * cp, cx * sp, st, ct * cp, ct * sp, st))   # point, normale
        return pts, 3.0, 3.0, 3.0, False

    @staticmethod
    def _cube():
        pts, n = [], 22
        for axis in range(3):
            for sgn in (-1, 1):
                for i in range(n + 1):
                    for j in range(n + 1):
                        u, v = -1.4 + 2.8 * i / n, -1.4 + 2.8 * j / n
                        p = [0.0, 0.0, 0.0]
                        p[axis], p[(axis + 1) % 3], p[(axis + 2) % 3] = sgn * 1.4, u, v
                        nn = [0.0, 0.0, 0.0]
                        nn[axis] = sgn
                        pts.append((*p, *nn))
        return pts, 2.45, 2.45, 2.45, False

    def step(self, dt):
        self.t += dt
        self.A += dt * 0.9
        self.B += dt * 0.8
        if len(self.shapes) > 1 and self.t > 16:
            self.t, self.shape = 0.0, (self.shape + 1) % len(self.shapes)

    def cells(self, colors):
        pts, K1, spin = self.shapes[self.shape]
        K2 = self.K2
        cx, cy = self.width / 2, self.rows / 2
        zbuf, lum = {}, {}
        lx, ly, lz = -0.38, 0.55, -0.74                 # lumière : en haut à gauche, vers nous
        if spin:                                         # logo : tourne sur lui-même, en se balançant un peu
            cB, sB = math.cos(self.B), math.sin(self.B)
            tilt = 0.28 * math.sin(self.A * 0.6)
            cA, sA = math.cos(tilt), math.sin(tilt)
        else:
            cA, sA, cB, sB = math.cos(self.A), math.sin(self.A), math.cos(self.B * 0.7), math.sin(self.B * 0.7)
        for x, y, z, nx, ny, nz in pts:
            if spin:
                x1, z1 = x * cB + z * sB, -x * sB + z * cB
                y2, z2 = y * cA - z1 * sA, y * sA + z1 * cA
                nx1, nz1 = nx * cB + nz * sB, -nx * sB + nz * cB
                ny2, nz2 = ny * cA - nz1 * sA, ny * sA + nz1 * cA
                X, Y, Z, NX, NY, NZ = x1, y2, z2, nx1, ny2, nz2
            else:                                        # tore, cube : rotation sur deux axes
                y1, z1 = y * cA - z * sA, y * sA + z * cA
                x2, y2 = x * cB - y1 * sB, x * sB + y1 * cB
                ny1, nz1 = ny * cA - nz * sA, ny * sA + nz * cA
                nx2, ny2 = nx * cB - ny1 * sB, nx * sB + ny1 * cB
                X, Y, Z, NX, NY, NZ = x2, y2, z1, nx2, ny2, nz1
            ooz = 1 / (K2 + Z)
            xp, yp = int(cx + K1 * ooz * X * 2), int(cy - K1 * ooz * Y)
            if 0 <= xp < self.width and 0 <= yp < self.rows and ooz > zbuf.get((xp, yp), 0):
                zbuf[(xp, yp)] = ooz
                lum[(xp, yp)] = NX * lx + NY * ly + NZ * lz
        a, a2 = colors["accent"], colors["accent2"]
        out = {}
        for k, L in lum.items():
            L = max(0.06, L)
            ch = self.SHADES[min(len(self.SHADES) - 1, int(L * (len(self.SHADES) - 1) + 0.5))]
            out[k] = (ch, ramp([(0, mix(a2, BLACK, 0.55)), (0.5, a2), (0.8, a), (1, mix(a, WHITE, 0.6))], L))
        return out


# ================================================================ serpent
class Serpent:
    """Un serpent qui joue tout seul : il va chercher la nourriture sans se mordre, et grandit."""

    OPTIONS = [("longueur", "Longueur au départ", "num", 10, (3, 40, 1, 0))]

    def __init__(self, cols, rows, size=1.0, opts=None):
        self.start_len = int(options(self, opts)["longueur"])
        self.width, self.rows = cols, rows
        self.w, self.h = cols, rows * 2
        self.acc, self.t = 0.0, 0.0
        self.reset()

    def reset(self):
        y = self.h // 2
        n = max(2, min(self.start_len, self.w - 3))
        self.body = [(x, y) for x in range(n + 2, 2, -1)]       # tête en premier
        self.dead = 0.0
        self.place_food()

    def place_food(self):
        free = {(x, y) for x in range(self.w) for y in range(self.h)} - set(self.body)
        self.food = random.choice(sorted(free)) if free else None

    def _neighbours(self, p):
        x, y = p
        return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    def _inside(self, p):
        return 0 <= p[0] < self.w and 0 <= p[1] < self.h

    def _path(self, start, goal, blocked):
        prev, todo = {start: None}, [start]
        for p in todo:
            if p == goal:
                break
            for n in self._neighbours(p):
                if n not in prev and self._inside(n) and n not in blocked:
                    prev[n] = p
                    todo.append(n)
        if goal not in prev:
            return None
        while prev[goal] != start:
            goal = prev[goal]
        return goal

    def _room(self, p, blocked, limit):
        seen, todo = {p}, [p]
        for q in todo:
            for n in self._neighbours(q):
                if n not in seen and self._inside(n) and n not in blocked:
                    seen.add(n)
                    todo.append(n)
                    if len(seen) >= limit:
                        return len(seen)
        return len(seen)

    def _move(self):
        head = self.body[0]
        blocked = set(self.body[:-1])
        nxt = self._path(head, self.food, blocked) if self.food else None
        if nxt:                                         # ne pas foncer dans un cul-de-sac
            if self._room(nxt, blocked | {head}, len(self.body) + 2) <= len(self.body):
                nxt = None
        if not nxt:                                     # sinon : là où il reste le plus de place
            opts = [n for n in self._neighbours(head) if self._inside(n) and n not in blocked]
            if not opts:
                self.dead = 1.2
                return
            nxt = max(opts, key=lambda n: self._room(n, blocked | {head}, len(self.body) * 2 + 10))
        self.body.insert(0, nxt)
        if nxt == self.food:
            self.place_food()
            if len(self.body) > self.w * self.h * 0.45:
                self.dead = 1.2
        else:
            self.body.pop()

    def step(self, dt):
        self.t += dt
        if self.dead:
            self.dead -= dt
            if self.dead <= 0:
                self.reset()
            return
        self.acc += dt
        while self.acc >= 1 / 14 and not self.dead:
            self.acc -= 1 / 14
            self._move()

    def cells(self, colors):
        a, a2 = colors["accent"], colors["accent2"]
        px = {}
        n = len(self.body)
        fade = 1.0 if not self.dead else max(0.0, self.dead / 1.2)
        for i, p in enumerate(self.body):
            col = mix(a, WHITE, 0.45) if i == 0 else mix(a, a2, i / max(1, n - 1))
            px[p] = mix(BLACK, col, fade) if self.dead else col
        if self.food and not self.dead:
            px[self.food] = a2 if int(self.t * 3) % 2 else WHITE
        return half_blocks(px, self.width, self.rows)


# ================================================================ liste (ordre du menu de Studio)
ANIMS = {
    "toile": (Toile, "Toile d'araignée"),
    "pluie": (Pluie, "Pluie de code"),
    "feu": (Feu, "Feu"),
    "ciel": (Ciel, "Ciel nocturne"),
    "chauves": (Chauves, "Chauves-souris et lune"),
    "corbeau": (Corbeau, "Corbeau sur sa branche"),
    "orage": (Orage, "Orage"),
    "aquarium": (Aquarium, "Aquarium"),
    "audio": (Audio, "Visualiseur audio"),
    "vie": (Vie, "Jeu de la vie"),
    "forme": (Forme, "Forme 3D"),
    "neige": (Neige, "Neige"),
    "serpent": (Serpent, "Serpent"),
}
LABELS = {k: label for k, (_cls, label) in ANIMS.items()}
