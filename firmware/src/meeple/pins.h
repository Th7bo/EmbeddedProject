#pragma once

// Must match diagrams/meeple/diagram.json
// GPIO0 and GPIO2 must be high at boot; the ESP8266 internal pull-ups take care of that.
// No external I2C pull-ups: Wire enables INPUT_PULLUP on SDA/SCL.
constexpr uint8_t PIN_SDA = 0;  // GPIO0
constexpr uint8_t PIN_SCL = 2;  // GPIO2
constexpr uint8_t PIN_LED = 3;  // GPIO3 (RX) via 1k, active high -> Serial is TX only
