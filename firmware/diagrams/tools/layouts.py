# Breadboard layouts for the Wokwi diagrams. Usage: python3 layouts.py <out dir>
import sys
from wokwi import Diagram, chip_def

AUTHOR = "Snakes & Ladders: Hot or Cold"
OUT = sys.argv[1]


def base():
    d = Diagram()
    d.breadboard("bb", 0, 0)
    # ESP32 right of the breadboard; GPIO32 lines up with row a, 33 with b, 25 with c, GND.1 with f
    d.part("board-esp32-devkit-c-v4", "esp", 360, -35.4)

    # Button straddles the gap: contact 1 = col 5 (GPIO33), contact 2 = col 3 (GND)
    d.place("wokwi-pushbutton", "btn", "1.l", "5t.b", rotate=90, attrs={"color": "green", "label": "ROLL"})
    for pin, hole in [("1.l", "5t.b"), ("2.l", "3t.b"), ("1.r", "5b.g"), ("2.r", "3b.g")]:
        d.seat("btn", pin, hole)

    # LED + 1k: anode col 9, cathode col 8, resistor row c col 9 -> 15
    d.place("wokwi-led", "led", "A", "9t.a", attrs={"color": "red"})
    d.seat("led", "A", "9t.a"); d.seat("led", "C", "8t.a")
    d.place("wokwi-resistor", "r_led", "1", "9t.c", dx=-0.6, attrs={"value": "1000"})
    d.seat("r_led", "1", "9t.c"); d.seat("r_led", "2", "15t.c")

    # Buzzer: - col 20, + col 21
    d.place("wokwi-buzzer", "bz", "1", "20t.a", attrs={"volume": "0.2"})
    d.seat("bz", "1", "20t.a"); d.seat("bz", "2", "21t.a")

    # LCD right of the ESP32, GND/SDA/SCL straight across
    d.place("wokwi-lcd1602", "lcd", "GND", (520 + 4, 51), attrs={"pins": "i2c"})

    d.conns += [["esp:TX", "$serialMonitor:RX", "", []], ["esp:RX", "$serialMonitor:TX", "", []]]

    # GND: ESP32 -> bottom rail, parts -> bottom rail
    d.wire("esp:GND.1", "bb:bn.25", "black", ("x", 345), ("y", 196.3))
    d.wire("bb:3b.j", "bb:bn.2", "black")
    d.wire("bb:8t.e", "bb:bn.6", "black")
    d.wire("bb:20t.e", "bb:bn.16", "black")

    # Signals, straight along their rows
    d.wire("esp:32", "bz:2", "purple")
    d.wire("esp:33", "btn:1.l", "gold")
    d.wire("esp:25", "r_led:2", "orange")

    # LCD
    d.wire("esp:GND.3", "lcd:GND", "black")
    d.wire("esp:18", "lcd:SDA", "green")
    d.wire("esp:5", "lcd:SCL", "blue")
    d.wire("esp:5V", "lcd:VCC", "red", ("y", 235), ("x", 495), ("y", d.pt("lcd:VCC")[1]))
    return d


def meeple():
    d = Diagram()
    d.breadboard("bb", 0, 0)
    # Rails: top + = 3V3 (pull-ups, PN532), all - = GND. Bottom rails fed by the LDO.
    d.wire("bb:tp.2", "bb:bp.2", "red")
    d.wire("bb:tn.3", "bb:bn.3", "black")

    # Pull-ups, standing from the top + rail into row c: EN col 26, RST col 24, SDA col 10, SCL col 12
    for rid, col, k in [("r_sda", 10, 8), ("r_scl", 12, 10), ("r_rst", 24, 20), ("r_en", 26, 21)]:
        d.place("wokwi-resistor", rid, "1", f"tp.{k}", rotate=90, dx=0.8, dy=-0.45, attrs={"value": "1000"})
        d.seat(rid, "1", f"tp.{k}"); d.seat(rid, "2", f"{col}t.c")
        d.wire(f"bb:{col}t.e", f"bb:{col}b.f", "orange")  # bridge the gap

    # LED: anode col 9, cathode col 8; 1k stands across the gap in col 9 (b -> f)
    d.place("wokwi-led", "led", "A", "9t.a", attrs={"color": "blue"})
    d.seat("led", "A", "9t.a"); d.seat("led", "C", "8t.a")
    d.place("wokwi-resistor", "r_led", "1", "9t.b", rotate=90, dy=-0.6, attrs={"value": "1000"})
    d.seat("r_led", "1", "9t.b"); d.seat("r_led", "2", "9b.f")
    d.wire("bb:8t.d", "bb:tn.4", "black", ("x", d.hole("tn.4")[0]))

    # ESP-01 below the breadboard (2x4 header: GND GPIO2 GPIO0 RX / VCC RST CH_PD TX)
    esp = chip_def(["GND", "GPIO2", "GPIO0", "RX", "TX", "CH_PD", "RST", "VCC"])
    d.part("chip-esp01", "esp", 158, 240, geo=esp)
    for pin, to, color in [("GND", "bn.11", "black"), ("GPIO2", "12b.j", "blue"), ("GPIO0", "10b.j", "green"),
                           ("RX", "9b.j", "purple"), ("VCC", "bp.19", "red"), ("RST", "24b.j", "gold"),
                           ("CH_PD", "26b.j", "gold")]:
        d.wire(f"esp:{pin}", f"bb:{to}", color, ("x", d.hole(to)[0]))

    # PN532 right of the breadboard (I2C header: GND VCC SDA SCL); SDA lines up with row g
    pn = chip_def(["GND", "VCC", "SDA", "SCL", "", "", "", ""])
    d.part("chip-pn532", "nfc", 360, 127.8 - pn["pins"]["SDA"][1], geo=pn)
    d.wire("nfc:SDA", "bb:10b.g", "green")
    d.wire("nfc:SCL", "bb:12b.h", "blue")
    d.wire("nfc:VCC", "bb:tp.24", "red", ("x", d.hole("tp.24")[0]))
    d.wire("nfc:GND", "bb:tn.25", "black", ("x", d.hole("tn.25")[0]))

    # Power: LiPo -> switch -> LDO -> bottom rails
    ldo = chip_def(["VIN", "EN", "GND", "VOUT"])
    d.part("chip-ldo", "ldo", -58, 230, geo=ldo)
    d.wire("ldo:VOUT", "bb:bp.4", "red", ("x", d.hole("bp.4")[0]))
    d.wire("ldo:GND", "bb:bn.5", "black", ("x", d.hole("bn.5")[0]))
    d.wire("ldo:EN", "ldo:VIN", "red", ("x", -66), ("y", d.pt("ldo:VIN")[1]))

    en_y = d.pt("ldo:EN")[1]
    d.place("wokwi-slide-switch", "sw", "1", (-88, en_y), rotate=180)
    d.wire("sw:1", "ldo:EN", "red")

    bat = chip_def(["", "", "BAT-", "BAT+"])
    d.part("chip-lipo", "bat", -135 - bat["size"][0], en_y - 20 - bat["pins"]["BAT+"][1], geo=bat)
    d.wire("sw:2", "bat:BAT+", "red", ("y", d.pt("bat:BAT+")[1]))
    bx, by = d.pt("bat:BAT-")
    d.wire("bat:BAT-", "ldo:GND", "black", ("x", bx + 8), ("y", 300), ("x", 24), ("y", d.pt("ldo:GND")[1]))
    return d


for name, fn in [("base", base), ("meeple", meeple)]:
    d = fn()
    open(f"{OUT}/{name}.diagram.json", "w").write(d.json(AUTHOR) + "\n")
    print(name, d.preview(f"{OUT}/{name}.html"))
