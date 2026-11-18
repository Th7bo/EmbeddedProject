// Wiring-only part: Wokwi has no SparkFun serial graphic LCD, so this chip just shows the pins.
// Backpack: 5 V, 115200 baud, commands start with 0x7C (see src/base/glcd.*).
#include "wokwi-api.h"

void chip_init(void) {}
