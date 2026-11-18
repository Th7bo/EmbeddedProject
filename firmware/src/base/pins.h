#pragma once

// Must match diagrams/base/diagram.json
// Pins picked so each wire runs straight along a breadboard row.
constexpr uint8_t PIN_LCD_TX = 17;  // UART2 TX -> 3.3V/5V level converter -> RX of the SparkFun
                                    // Serial Graphic LCD backpack (ADM12864H 128x64). One-way: RX unused.
constexpr uint8_t PIN_BUTTON = 33;  // to GND, INPUT_PULLUP
constexpr uint8_t PIN_BUZZER = 32;  // passive buzzer, PWM
constexpr uint8_t PIN_LED    = 25;  // via 1k, active high
