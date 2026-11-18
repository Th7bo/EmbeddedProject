"""Standalone breadboard wiring sheet (SVG) for a wokwi.Diagram.

Draws the same geometry and wires as the Wokwi diagram.json, without needing Wokwi:
breadboard holes, the ESP32 DevKitC with its real pin order, LEDs, resistors, buttons,
buzzers and the custom chips. Every wire in the layout is drawn.
"""
from wokwi import BB_SIZE, DEVKITC, MM, ROWS, RAILS, col_x, rail_x

WIRE = {"black": "#222", "red": "#e02020", "orange": "#f08a00", "gold": "#d4a800", "purple": "#8a3cc8",
        "green": "#1a9a3a", "blue": "#2a62d0", "gray": "#8a8a8a", "white": "#ddd", "": "#1a9a3a"}


def _bb(kind="half", size=BB_SIZE):
    w, h = size
    cols, rails = (30, True) if kind == "half" else (17, False)
    y0, y1 = (0, h) if rails else (ROWS["a"] - 17, ROWS["j"] + 19)
    s = [f'<rect y="{y0}" width="{w}" height="{y1 - y0}" rx="6" fill="#f2f2ee" stroke="#c9c9c0"/>',
         f'<rect x="4" y="99" width="{w - 8}" height="10" fill="#e2e2da"/>']
    for n in range(1, cols + 1):
        for y in ROWS.values():
            s.append(f'<rect x="{col_x(n) - 2.3:.1f}" y="{y - 2.3:.1f}" width="4.6" height="4.6" rx="1" fill="#555"/>')
        if n % 5 == 0 or n == 1 or (not rails and n == cols):
            for y in (ROWS["a"] - 9, ROWS["j"] + 12):
                s.append(f'<text x="{col_x(n):.1f}" y="{y}" font-size="6" fill="#999" text-anchor="middle">{n}</text>')
    for r, y in ROWS.items():
        s.append(f'<text x="8" y="{y + 2}" font-size="6" fill="#999" text-anchor="middle">{r}</text>')
    for rail, y in (RAILS.items() if rails else ()):
        plus = rail.endswith("p")
        col = "#e33" if plus else "#36c"
        for k in range(1, 26):
            s.append(f'<rect x="{rail_x(k) - 2.3:.1f}" y="{y - 2.3:.1f}" width="4.6" height="4.6" rx="1" fill="#555"/>')
        ly = y - 6 if rail in ("tp", "bn") else y + 6
        s.append(f'<line x1="22" x2="{w - 22}" y1="{ly}" y2="{ly}" stroke="{col}" stroke-width="1.2"/>')
        s.append(f'<text x="14" y="{y + 3}" font-size="9" font-weight="bold" fill="{col}" text-anchor="middle">{"+" if plus else "−"}</text>')
    return "".join(s)


def _devkitc(g):
    w, h = g["size"]
    s = [f'<rect width="{w}" height="{h}" rx="5" fill="#1d1d24" stroke="#000"/>',
         f'<rect x="{w / 2 - 33}" y="4" width="66" height="22" fill="#2b2b36"/>',
         f'<path d="M{w / 2 - 28} 22 v-12 h7 v9 h7 v-9 h7 v9 h7 v-9 h7 v9 h7 v-9 h12" fill="none" stroke="#b8963a" stroke-width="2"/>',
         f'<rect x="{w / 2 - 26}" y="32" width="52" height="40" fill="#8a8a92" stroke="#555"/>',
         f'<text x="{w / 2}" y="56" font-size="8" fill="#222" text-anchor="middle" font-weight="bold">ESP32</text>',
         f'<rect x="{w / 2 - 12}" y="{h - 4}" width="24" height="10" fill="#bbb" stroke="#555"/>',
         f'<text x="{w / 2}" y="{h + 16}" font-size="7" fill="#666" text-anchor="middle">USB</text>']
    for name, (x, y) in g["pins"].items():
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#d9b44a"/>')
        left = x < w / 2
        lab = name.split(".")[0]
        s.append(f'<text x="{x + (6 if left else -6):.1f}" y="{y + 2.2:.1f}" font-size="5.6" font-family="monospace" '
                 f'fill="#eee" text-anchor="{"start" if left else "end"}">{lab}</text>')
    return "".join(s)


def _led(attrs):
    color = {"red": "#e33", "blue": "#39f", "green": "#3c3", "yellow": "#ec2"}.get(attrs.get("color", "red"), "#e33")
    return (f'<line x1="15" y1="30" x2="15" y2="42" stroke="#999" stroke-width="1.5"/>'
            f'<line x1="25" y1="26" x2="25" y2="42" stroke="#999" stroke-width="1.5"/>'
            f'<path d="M10 30 v-14 a10 10 0 0 1 20 0 v14 z" fill="{color}" stroke="#333" opacity="0.92"/>'
            f'<rect x="8" y="28" width="24" height="4" fill="{color}" stroke="#333"/>'
            f'<text x="20" y="10" font-size="5" text-anchor="middle" fill="#fff">+ long</text>')


def _resistor(attrs):
    return ('<line x1="0" y1="5.65" x2="58.8" y2="5.65" stroke="#999" stroke-width="1.5"/>'
            '<rect x="14" y="1" width="31" height="9.3" rx="4" fill="#d8c08a" stroke="#8a7346"/>'
            '<rect x="19" y="1" width="2.5" height="9.3" fill="#7b4a12"/><rect x="24" y="1" width="2.5" height="9.3" fill="#111"/>'
            '<rect x="29" y="1" width="2.5" height="9.3" fill="#e33"/><rect x="38" y="1" width="2.5" height="9.3" fill="#c9a33a"/>')


def _button(attrs):
    cap = {"green": "#2a2", "red": "#d22", "blue": "#25c"}.get(attrs.get("color"), "#444")
    return ('<rect x="8" y="2" width="51" height="41" rx="3" fill="#333" stroke="#111"/>'
            '<line x1="0" y1="13" x2="8" y2="13" stroke="#999" stroke-width="2"/><line x1="0" y1="32" x2="8" y2="32" stroke="#999" stroke-width="2"/>'
            '<line x1="59" y1="13" x2="67" y2="13" stroke="#999" stroke-width="2"/><line x1="59" y1="32" x2="67" y2="32" stroke="#999" stroke-width="2"/>'
            f'<circle cx="33.5" cy="22.5" r="14" fill="{cap}" stroke="#111"/>')


def _buzzer(g):
    w, h = g["size"]
    return (f'<line x1="27" y1="{h - 22}" x2="27" y2="84" stroke="#999" stroke-width="1.5"/>'
            f'<line x1="37" y1="{h - 22}" x2="37" y2="84" stroke="#999" stroke-width="1.5"/>'
            f'<circle cx="{w / 2}" cy="{w / 2}" r="{w / 2 - 1}" fill="#1a1a1a" stroke="#000"/>'
            f'<circle cx="{w / 2}" cy="{w / 2}" r="5" fill="#555"/>'
            f'<text x="40" y="{h - 26}" font-size="7" fill="#fff">+</text>')


def _chip(g, style):
    w, h = g["size"]
    fill = style.get("fill", "#222")
    fg = style.get("fg", "#fff")
    fs = style.get("font", 6.5)
    names = style.get("labels", {})
    s = [f'<rect width="{w}" height="{h}" rx="4" fill="{fill}" stroke="#111"/>']
    for name, (x, y) in g["pins"].items():
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.8" fill="#d9b44a" stroke="#111" stroke-width="0.6"/>')
        if x <= 1:
            tx, ty, anchor = x + 6, y + 2.4, "start"
        elif x >= w - 1:
            tx, ty, anchor = x - 6, y + 2.4, "end"
        elif y < h / 2:
            tx, ty, anchor = x, y + 4 + fs * 1.2, "middle"
        else:
            tx, ty, anchor = x, y - 4 - fs * 0.3, "middle"
        if style.get("pin_names", True):
            s.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{fs}" font-family="monospace" font-weight="bold" '
                     f'fill="{fg}" text-anchor="{anchor}">{names.get(name, name)}</text>')
    if style.get("title"):
        s.append(f'<text x="{w / 2}" y="{h / 2 + 3}" font-size="7.5" font-weight="bold" fill="{fg}" '
                 f'text-anchor="middle" opacity="0.85">{style["title"]}</text>')
    return "".join(s)


def render(d, path, title, labels=None, chips=None, notes=(), tags=None, callout=None, pad=50):
    """labels: {part id: (caption, dx, dy)}. chips: {part id: {fill, fg, title, font, labels, pin_names}}.
    tags: {"part:pin": (text, "up" | "down")} vertical name tags next to a pin (for dense headers).
    callout: {x, y, title, cols, rows: [(row label, [names])]} small pin-map table at (x, y)."""
    labels, chips = labels or {}, chips or {}
    boxes = []
    for p in d.parts:
        g, left, top, rot = d._geo[p["id"]]
        w, h = g["size"]
        if rot % 180:
            c = g.get("center", (w / 2, h / 2))
            cx, cy = left + c[0], top + c[1]
            boxes.append((cx - h / 2, cy - w / 2, cx + h / 2, cy + w / 2))
        else:
            boxes.append((left, top, left + w, top + h))
    for a, b, color, instr in d.conns:
        if instr == ["$bb"] or a.startswith("$") or b.startswith("$"):
            continue
        for ref in (a, b):
            x, y = d.pt(ref)
            boxes.append((x, y, x, y))
        x, y = d.pt(a)
        for s_ in instr:
            v = float(s_[1:])
            x, y = (x + v, y) if s_[0] == "h" else (x, y + v)
            boxes.append((x, y, x, y))
    if callout:
        boxes.append((callout["x"], callout["y"], callout["x"] + 150, callout["y"] + 30 + 18 * len(callout["rows"])))
    minx = min(b[0] for b in boxes) - pad
    miny = min(b[1] for b in boxes) - pad - 30
    maxx = max(b[2] for b in boxes) + pad
    maxy = max(b[3] for b in boxes) + pad + 16 * len(notes)
    W, H = maxx - minx, maxy - miny

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W * 1.6:.0f}" '
           f'height="{H * 1.6:.0f}" font-family="Helvetica, Arial, sans-serif">',
           f'<title>{title}</title>', f'<rect width="{W:.0f}" height="{H:.0f}" fill="#fff"/>',
           f'<text x="14" y="22" font-size="13" font-weight="bold" fill="#222">{title}</text>',
           f'<g transform="translate({-minx:.1f},{-miny:.1f})">']

    for p in d.parts:
        g, left, top, rot = d._geo[p["id"]]
        w, h = g["size"]
        c = g.get("center", (w / 2, h / 2))
        t = p["type"]
        body = (_bb(t.rsplit("-", 1)[1], g["size"]) if t.startswith("wokwi-breadboard") else _devkitc(g) if t == "board-esp32-devkit-c-v4"
                else _led(p["attrs"]) if t == "wokwi-led" else _resistor(p["attrs"]) if t == "wokwi-resistor"
                else _button(p["attrs"]) if t == "wokwi-pushbutton" else _buzzer(g) if t == "wokwi-buzzer"
                else _chip(g, chips.get(p["id"], {})))
        out.append(f'<g transform="translate({left:.1f},{top:.1f}) rotate({rot},{c[0]:.1f},{c[1]:.1f})">{body}</g>')

    for a, b, color, instr in d.conns:  # wires on top of the parts
        if instr == ["$bb"] or a.startswith("$") or b.startswith("$"):
            continue
        x, y = d.pt(a)
        pts = [(x, y)]
        for s_ in instr:
            v = float(s_[1:])
            x, y = (x + v, y) if s_[0] == "h" else (x, y + v)
            pts.append((x, y))
        bx, by = d.pt(b)
        if abs(bx - x) > 0.5 and abs(by - y) > 0.5:
            pts.append((bx, y))
        pts.append((bx, by))
        col = WIRE.get(color, color)
        ps = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out.append(f'<polyline points="{ps}" fill="none" stroke="#000" stroke-opacity="0.25" stroke-width="4.2" stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<polyline points="{ps}" fill="none" stroke="{col}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>')
        for px, py in (pts[0], pts[-1]):
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.4" fill="{col}" stroke="#000" stroke-width="0.6"/>')

    for ref, (text, way) in (tags or {}).items():
        x, y = d.pt(ref)
        ty = y - 5 if way == "up" else y + 5
        anchor = "start" if way == "up" else "end"
        w = 3.4 * len(text) + 4
        ry = ty - w if way == "up" else ty
        out.append(f'<rect x="{x - 4.2:.1f}" y="{ry:.1f}" width="8.4" height="{w:.1f}" rx="2" fill="#fff" stroke="#333" stroke-width="0.5"/>')
        out.append(f'<text transform="translate({x + 2.2:.1f},{ty - (2 if way == "up" else -2):.1f}) rotate(-90)" font-size="5.6" '
                   f'font-family="monospace" font-weight="bold" fill="#111" text-anchor="{anchor}">{text}</text>')
    if callout:
        cx, cy, cw = callout["x"], callout["y"], 150
        ch = 30 + 18 * len(callout["rows"])
        out.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="6" fill="#fff" stroke="#bbb"/>')
        out.append(f'<text x="{cx + 8}" y="{cy + 13}" font-size="8" font-weight="bold" fill="#333">{callout["title"]}</text>')
        colw = (cw - 40) / len(callout["cols"])
        for k, c in enumerate(callout["cols"]):
            out.append(f'<text x="{cx + 40 + colw * (k + .5):.1f}" y="{cy + 25}" font-size="7" fill="#888" text-anchor="middle">col {c}</text>')
        for r, (rl, names) in enumerate(callout["rows"]):
            y = cy + 40 + 18 * r
            out.append(f'<text x="{cx + 8}" y="{y}" font-size="7" fill="#888">{rl}</text>')
            for k, n in enumerate(names):
                out.append(f'<text x="{cx + 40 + colw * (k + .5):.1f}" y="{y}" font-size="7.5" font-family="monospace" '
                           f'font-weight="bold" fill="#111" text-anchor="middle">{n}</text>')
    for pid, (text, dx, dy) in labels.items():
        g, left, top, rot = d._geo[pid]
        out.append(f'<text x="{left + dx:.1f}" y="{top + dy:.1f}" font-size="8.5" font-weight="bold" fill="#333" '
                   f'text-anchor="middle">{text}</text>')
    out.append("</g>")
    for i, n in enumerate(notes):
        out.append(f'<text x="14" y="{H - 14 - 16 * (len(notes) - 1 - i):.0f}" font-size="9" fill="#555">{n}</text>')
    out.append("</svg>")
    open(path, "w").write("\n".join(out) + "\n")
