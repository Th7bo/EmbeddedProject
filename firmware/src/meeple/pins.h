#pragma once

// Must match diagrams/meeple/diagram.json
// GPIO0 and GPIO2 must be high at boot; the I2C pull-ups take care of that.
constexpr uint8_t PIN_SDA = 0;  // GPIO0
constexpr uint8_t PIN_SCL = 2;  // GPIO2
constexpr uint8_t PIN_LED = 3;  // GPIO3 (RX) via 1k, active high -> Serial is TX only
