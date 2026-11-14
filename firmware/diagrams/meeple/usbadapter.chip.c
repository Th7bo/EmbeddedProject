// Wiring-only part: Wokwi has no USB to ESP-01 adapter, so this chip just shows the pins.
// 3V3 = socket VCC (onboard regulator), ESP_TX = socket pin where the ESP-01 TX plugs in (CH340 RXD).
#include "wokwi-api.h"

void chip_init(void) {}
