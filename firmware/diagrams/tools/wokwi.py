"""Tiny layout helper: place Wokwi parts by breadboard hole, route wires with
explicit h/v moves, emit diagram.json and an HTML preview."""
import json, math, os

PITCH = 9.6
MM = 96 / 25.4

# measured (xmejkal/spark data/wokwi-geometry.json, wokwi-elements, wokwi-boards)
ROWS = dict(a=51, b=60.6, c=70.2, d=79.8, e=89.4, f=118.2, g=127.8, h=137.4, i=147, j=156.6)
RAILS = dict(tp=12.3, tn=22.3, bp=186.3, bn=196.3)
BB_SIZE = (332, 211)

PARTS = {
    "wokwi-led": dict(size=(40, 50), pins={"A": (25, 42), "C": (15, 42)}),
    "wokwi-resistor": dict(size=(59.13, 11.34), center=(29.5, 5.5), pins={"1": (0, 5.65), "2": (58.8, 5.65)}),
    "wokwi-pushbutton": dict(size=(67.28, 45.35), center=(33.5, 24.5),
                             pins={"1.l": (0, 13), "2.l": (0, 32), "1.r": (67, 13), "2.r": (67, 32)}),
    "wokwi-buzzer": dict(size=(17 * MM, 20 * MM), pins={"1": (27, 84), "2": (37, 84)}),
    "wokwi-slide-switch": dict(size=(8.5 * MM, 9.23 * MM), pins={"1": (6.5, 34), "2": (16, 34), "3": (25.5, 34)}),
    "wokwi-lcd1602": dict(size=(80 * MM, 36 * MM), pins={"GND": (4, 32), "VCC": (4, 41.5), "SDA": (4, 51), "SCL": (4, 60.5)}),
}

DEVKITC = json.load(open(os.path.join(os.path.dirname(__file__), "devkitc-pins.json")))
PARTS["board-esp32-devkit-c-v4"] = dict(
    size=(105.4, 214), pins={k: (v["x"] * MM, v["y"] * MM) for k, v in DEVKITC["pins"].items()})

# Custom chips: geometry NOT published. Assumed DIP layout: pins[0:n/2] down the
# left side, pins[n/2:] up the right side, 9.6 px pitch.
CHIP_W, CHIP_TOP = 72, 14.4


def chip_def(pins):
    n = len(pins)
    half = n // 2
    geo = {}
    for i, p in enumerate(pins):
        if not p:
            continue
        if i < half:
            geo[p] = (0, CHIP_TOP + PITCH * i)
        else:
            geo[p] = (CHIP_W, CHIP_TOP + PITCH * (n - 1 - i))
    return dict(size=(CHIP_W, CHIP_TOP * 2 + PITCH * (half - 1)), pins=geo, chip=pins)


def col_x(n):
    return 26 + PITCH * (n - 1)


def rail_x(k):
    return 34 + PITCH * (k - 1) + PITCH * ((k - 1) // 5)


def rotate_pt(x, y, deg, c):
    cx, cy = c
    for _ in range((deg // 90) % 4):
        x, y = cx + cy - y, cy - cx + x
    return x, y


class Diagram:
    def __init__(self):
        self.parts, self.conns, self.bb = [], [], {}

    def part(self, type_, id_, left=0, top=0, rotate=0, attrs=None, geo=None):
        g = geo or PARTS[type_]
        p = dict(type=type_, id=id_, top=round(top, 2), left=round(left, 2), attrs=attrs or {})
        if rotate:
            p["rotate"] = rotate
        self.parts.append(p)
        self._geo = getattr(self, "_geo", {})
        self._geo[id_] = (g, left, top, rotate)
        return p

    def breadboard(self, id_, left, top):
        self.bb = dict(id=id_, left=left, top=top)
        self.part("wokwi-breadboard-half", id_, left, top,
                  geo=dict(size=BB_SIZE, pins={}))

    def hole(self, name):
        """'12t.c' / '3b.j' / 'tp.4' -> absolute (x, y)."""
        L, T = self.bb["left"], self.bb["top"]
        a, b = name.split(".")
        if a in RAILS:
            return L + rail_x(int(b)), T + RAILS[a]
        return L + col_x(int(a[:-1])), T + ROWS[b]

    def pin_rel(self, id_, pin):
        g, left, top, rot = self._geo[id_]
        x, y = g["pins"][pin]
        c = g.get("center", (g["size"][0] / 2, g["size"][1] / 2))
        return rotate_pt(x, y, rot, c)

    def place(self, type_, id_, pin, at, rotate=0, attrs=None, geo=None, dx=0, dy=0):
        """Place so that `pin` sits on hole/point `at`."""
        g = geo or PARTS[type_]
        c = g.get("center", (g["size"][0] / 2, g["size"][1] / 2))
        px, py = rotate_pt(*g["pins"][pin], rotate, c)
        ax, ay = self.hole(at) if isinstance(at, str) else at
        return self.part(type_, id_, ax - px + dx, ay - py + dy, rotate, attrs, geo)

    def seat(self, id_, pin, hole):
        """Pin sits in a breadboard hole: Wokwi's $bb connection."""
        self.conns.append([f"{id_}:{pin}", f"{self.bb['id']}:{hole}", "", ["$bb"]])

    def pt(self, ref):
        id_, pin = ref.split(":", 1)
        if id_ == self.bb.get("id"):
            return self.hole(pin)
        g, left, top, rot = self._geo[id_]
        x, y = self.pin_rel(id_, pin)
        return left + x, top + y

    def wire(self, a, b, color, *path):
        """path: absolute waypoints as ('x', value) / ('y', value) moves from a.
        The last leg to b must be a single straight segment."""
        x, y = self.pt(a)
        instr = []
        for axis, v in path:
            if axis == "x":
                instr.append(f"h{round(v - x, 2):g}"); x = v
            else:
                instr.append(f"v{round(v - y, 2):g}"); y = v
        bx, by = self.pt(b)
        if abs(bx - x) > 2 and abs(by - y) > 2:
            print(f"warning: {a} -> {b} last leg is diagonal ({bx - x:.1f}, {by - y:.1f})")
        self.conns.append([a, b, color, instr])

    def json(self, author):
        return json.dumps(dict(version=1, author=author, editor="wokwi", parts=self.parts,
                               connections=self.conns, dependencies={}), indent=2)

    # ---- preview -------------------------------------------------------
    def preview(self, path, pad=40):
        boxes = []
        for p in self.parts:
            g, left, top, rot = self._geo[p["id"]]
            w, h = g["size"]
            boxes.append((left, top, left + w, top + h))
        minx = min(b[0] for b in boxes) - pad
        miny = min(b[1] for b in boxes) - pad
        maxx = max(b[2] for b in boxes) + pad
        maxy = max(b[3] for b in boxes) + pad
        out = []
        for p in self.parts:
            g, left, top, rot = self._geo[p["id"]]
            w, h = g["size"]
            c = g.get("center", (w / 2, h / 2))
            style = f"left:{left - minx}px;top:{top - miny}px;transform-origin:{c[0]}px {c[1]}px;transform:rotate({rot}deg)"
            t = p["type"]
            if t == "wokwi-breadboard-half":
                out.append(f'<div class="p" style="{style}">{bb_svg()}</div>')
            elif t == "board-esp32-devkit-c-v4":
                out.append(f'<img class="p" src="https://raw.githubusercontent.com/wokwi/wokwi-boards/main/boards/esp32-devkit-c-v4/board.svg" style="{style};width:{w}px;height:{h}px">')
            elif t.startswith("chip-"):
                out.append(f'<div class="p" style="{style}">{chip_svg(p["id"], g)}</div>')
            else:
                at = " ".join(f'{k}="{v}"' for k, v in p["attrs"].items())
                tag = t
                out.append(f'<{tag} class="p" style="{style}" {at}></{tag}>')
        wires = []
        for a, b, color, instr in self.conns:
            if instr == ["$bb"] or a.startswith("$") or b.startswith("$") or "$serial" in a + b:
                continue
            x, y = self.pt(a)
            pts = [(x, y)]
            for s in instr:
                v = float(s[1:])
                if s[0] == "h": x += v
                else: y += v
                pts.append((x, y))
            bx, by = self.pt(b)
            if abs(bx - x) > 0.5 and abs(by - y) > 0.5:
                pts.append((bx, y))
            pts.append((bx, by))
            d = " ".join(f"{px - minx:.1f},{py - miny:.1f}" for px, py in pts)
            wires.append(f'<polyline points="{d}" stroke="{color or "green"}" stroke-width="2" fill="none" stroke-linejoin="round" opacity="0.9"/>')
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<script type="module" src="https://cdn.jsdelivr.net/npm/@wokwi/elements@1.9.2/+esm"></script>
<style>body{{margin:0;background:#fff}} .p{{position:absolute}} #w{{position:absolute;left:0;top:0;pointer-events:none}}</style>
</head><body><div style="position:relative;width:{maxx - minx}px;height:{maxy - miny}px">
{''.join(out)}
<svg id="w" width="{maxx - minx}" height="{maxy - miny}">{''.join(wires)}</svg>
</div></body></html>"""
        open(path, "w").write(html)
        return int(maxx - minx), int(maxy - miny)


def bb_svg():
    s = [f'<svg width="{BB_SIZE[0]}" height="{BB_SIZE[1]}"><rect width="{BB_SIZE[0]}" height="{BB_SIZE[1]}" rx="6" fill="#eee" stroke="#ccc"/>',
         f'<rect x="0" y="99" width="{BB_SIZE[0]}" height="10" fill="#ddd"/>']
    for n in range(1, 31):
        for r, y in ROWS.items():
            s.append(f'<rect x="{col_x(n) - 2.5}" y="{y - 2.5}" width="5" height="5" fill="#555"/>')
    for rail, y in RAILS.items():
        col = "#e55" if rail.endswith("p") else "#59f"
        for k in range(1, 26):
            s.append(f'<rect x="{rail_x(k) - 2.5}" y="{y - 2.5}" width="5" height="5" fill="#555"/>')
        ly = y - 5 if rail in ("tp", "bp") else y + 5
        ly = y + (-5 if rail[1] == "p" and rail[0] == "t" else 5) if False else ly
        s.append(f'<line x1="20" x2="312" y1="{ly}" y2="{ly}" stroke="{col}" stroke-width="1"/>')
    s.append("</svg>")
    return "".join(s)


def chip_svg(id_, g):
    w, h = g["size"]
    s = [f'<svg width="{w + 10}" height="{h}" style="overflow:visible"><rect x="4" width="{w - 8}" height="{h}" rx="3" fill="#222"/>',
         f'<text x="{w / 2}" y="{h - 4}" fill="#aaa" font-size="8" text-anchor="middle" font-family="sans-serif">{id_}</text>']
    for name, (x, y) in g["pins"].items():
        s.append(f'<rect x="{x - 4}" y="{y - 2}" width="8" height="4" fill="#bbb"/>')
        tx = x + 8 if x == 0 else x - 8
        anchor = "start" if x == 0 else "end"
        s.append(f'<text x="{tx}" y="{y + 3}" fill="#fff" font-size="7" font-family="monospace" text-anchor="{anchor}">{name}</text>')
    s.append("</svg>")
    return "".join(s)
