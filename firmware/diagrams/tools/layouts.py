# Breadboard layouts for the Wokwi diagrams. Usage: python3 layouts.py <out dir>
import sys
from wokwi import Diagram, chip_def, col_x, ROWS, PITCH
from sheet import render

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

    # 128x64 graphic LCD (ADM12864H + SparkFun serial backpack, 5 V) right of the ESP32,
    # fed one-way from UART2 TX (GPIO17) through a 3.3 V <-> 5 V logic level converter.
    lv = chip_def(["LV1", "LV2", "LV", "GND", "LV3", "LV4", "HV4", "HV3", "GND2", "HV", "HV2", "HV1"])
    d.part("chip-levelshift", "lv", 520, d.pt("esp:17")[1] - lv["pins"]["LV1"][1], geo=lv)
    lcd = chip_def(["RX", "TX", "VIN", "GND", "", "", "", ""])
    d.part("chip-glcd", "lcd", 680, d.pt("lv:HV1")[1] - lcd["pins"]["RX"][1], geo=lcd)

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

    # LCD: TX -> LV1 -> HV1 -> backpack RX; LV side 3V3, HV side + backpack 5V
    d.wire("esp:17", "lv:LV1", "orange")
    d.wire("lv:HV1", "lcd:RX", "orange")
    d.wire("esp:GND.3", "lv:GND", "black", ("x", 490), ("y", d.pt("lv:GND")[1]))
    d.wire("lv:GND2", "lcd:GND", "black")
    d.wire("lv:HV", "lcd:VIN", "red")
    d.wire("esp:3V3", "lv:LV", "red", ("y", -45), ("x", 505), ("y", d.pt("lv:LV")[1]))
    d.wire("esp:5V", "lv:HV", "red", ("y", 215), ("x", 615), ("y", d.pt("lv:HV")[1]))
    return d


ESP01_ROWS = [["GND", "GPIO2", "GPIO0", "RX"], ["TX", "CH_PD", "RST", "VCC"]]


def meeple():
    d = Diagram()
    # Mini breadboard: 17 columns, no power rails. Bus columns instead:
    #   col 16 = 3V3 (bottom half fed by the USB adapter, jumpered to the top half)
    #   col 17 = GND (same)
    d.breadboard("bb", 0, 0, kind="mini")
    d.wire("bb:16b.f", "bb:16t.e", "red")
    d.wire("bb:17b.f", "bb:17t.e", "black")

    # ESP-01 in its breadboard adapter, straddling the gap in columns 6-9 (antenna side up):
    #   row e: GND  GPIO2 GPIO0 RX        (header pins 1-4)
    #   row f: TX   CH_PD RST   VCC       (header pins 8-5)
    x0, ye, yf = col_x(6), ROWS["e"], ROWS["f"]
    geo = dict(size=(3 * PITCH + 16, yf - ye + 20),
               pins={n: (8 + PITCH * k, 10 + (yf - ye) * r) for r, row in enumerate(ESP01_ROWS) for k, n in enumerate(row)})
    d.part("chip-esp01", "esp", x0 - 8, ye - 10, geo=geo)
    for r, row in enumerate(ESP01_ROWS):
        for k, n in enumerate(row):
            d.seat("esp", n, f"{6 + k}{'t' if r == 0 else 'b'}.{'e' if r == 0 else 'f'}")

    # Power: GND along row d to the GND column, CH_PD / RST / VCC along rows g-i to the 3V3 column
    d.wire("bb:6t.d", "bb:17t.d", "black")
    d.wire("bb:7b.g", "bb:16b.g", "red")
    d.wire("bb:8b.h", "bb:16b.h", "red")
    d.wire("bb:9b.i", "bb:16b.i", "red")

    # LED on RX (GPIO3): 1k in row b from col 9 to col 15, LED anode col 15, cathode col 14 -> GND
    d.place("wokwi-resistor", "r_led", "1", "9t.b", dx=-0.6, attrs={"value": "1000"})
    d.seat("r_led", "1", "9t.b"); d.seat("r_led", "2", "15t.b")
    d.place("wokwi-led", "led", "A", "15t.a", attrs={"color": "blue"})
    d.seat("led", "A", "15t.a"); d.seat("led", "C", "14t.a")
    d.wire("bb:14t.c", "bb:17t.c", "black")

    # PN532 right of the breadboard. I2C header labels on our boards: TXD = SCL, RXD = SDA.
    pn = chip_def(["SCL", "SDA", "VCC", "GND", "", "", "", ""])
    d.part("chip-pn532", "nfc", col_x(17) + 70, -22 - pn["pins"]["SCL"][1], geo=pn)
    d.wire("bb:7t.a", "nfc:SCL", "blue", ("y", -22))
    d.wire("bb:8t.a", "nfc:SDA", "green", ("y", d.pt("nfc:SDA")[1]))
    d.wire("nfc:VCC", "bb:16t.a", "red", ("x", d.hole("16t.a")[0]))
    d.wire("nfc:GND", "bb:17t.a", "black", ("x", d.hole("17t.a")[0]))

    # Power: OPEN-SMART USB to ESP-01 adapter, used only as 3V3 supply + serial monitor.
    # ESP-01 is NOT in its socket: the adapter's CH340 would drive RX (= LED pin).
    usb = chip_def(["", "ESP_TX", "GND", "3V3"])
    d.part("chip-usbadapter", "usb", 60, 200, geo=usb)
    d.wire("usb:3V3", "bb:16b.j", "red", ("x", d.hole("16b.j")[0]))
    d.wire("usb:GND", "bb:17b.j", "black", ("x", d.hole("17b.j")[0]))
    # ESP-01 TX -> adapter socket TX hole (CH340 RXD), only for the serial monitor
    d.wire("bb:6b.j", "usb:ESP_TX", "gray", ("y", 190), ("x", 40), ("y", d.pt("usb:ESP_TX")[1]))
    return d


SHEETS = {
    "base": dict(
        title="Control base: ESP32 DevKitC + 128x64 serial LCD + button + buzzer + LED",
        labels={"btn": ("ROLL button", 33, 106), "led": ("LED", 20, -4), "r_led": ("1k", 30, -4),
                "bz": ("buzzer", 32, -6), "lv": ("level converter", 36, -6),
                "lcd": ("LCD 128x64 (SparkFun serial)", 36, -6), "esp": ("ESP32 DevKitC V4", 53, 240)},
        chips={"lv": dict(fill="#2a5db0", title="3.3V | 5V"), "lcd": dict(fill="#8fb33a", fg="#111", title="ADM12864H")},
        notes=["LCD is one-way: GPIO17 (UART2 TX) -> converter LV1 -> HV1 -> backpack RX. Both converter GND pins are the same net.",
               "Button: INPUT_PULLUP, no resistor. Buzzer + on GPIO32. LED long leg -> 1k -> GPIO25. Power: ESP32 USB."]),
    "meeple": dict(
        title="Meeple: ESP-01 + PN532 V3 (I2C) + LED on a mini breadboard",
        labels={"esp": ("ESP-01", 22, 27), "led": ("LED", 20, -4), "r_led": ("1k", 30, -4),
                "nfc": ("PN532 V3 (SW1 ON, SW2 OFF)", 36, -6), "usb": ("USB to ESP-01 adapter", 36, -6)},
        chips={"esp": dict(fill="#1d1d24", pin_names=False), "nfc": dict(fill="#a22", labels={"SCL": "TXD (SCL)", "SDA": "RXD (SDA)"}),
               "usb": dict(fill="#c33", labels={"ESP_TX": "TX", "3V3": "3V3"})},
        callout=dict(x=-175, y=40, title="ESP-01 adapter, columns 6-9", cols=[6, 7, 8, 9],
                     rows=[("row e", ESP01_ROWS[0]), ("row f", ESP01_ROWS[1])]),
        notes=["Mini breadboard, no rails: column 16 = 3V3, column 17 = GND (each half jumpered across the gap).",
               "USB adapter: jumper wires from its socket holes 3V3, GND and TX. ESP-01 not in the adapter (its RX drives the LED).",
               "LED long leg in col 15 (with the 1k), short leg col 14. No pull-up resistors needed.",
               "Flash: ESP-01 into the USB adapter, switch to PROG (unplug first), upload, then back to UART + breadboard."]),
}

for name, fn in [("base", base), ("meeple", meeple)]:
    d = fn()
    open(f"{OUT}/{name}.diagram.json", "w").write(d.json(AUTHOR) + "\n")
    print(name, d.preview(f"{OUT}/{name}.html"))
    if name in SHEETS:
        render(d, f"{OUT}/{name}.svg", **SHEETS[name])
