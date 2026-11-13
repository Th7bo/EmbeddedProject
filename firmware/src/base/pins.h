#pragma once

// Must match diagrams/base/diagram.json
// Pins picked so each wire runs straight along a breadboard row.
constexpr uint8_t PIN_SDA    = 18;  // LCD
constexpr uint8_t PIN_SCL    = 5;   // LCD
constexpr uint8_t PIN_BUTTON = 33;  // to GND, INPUT_PULLUP
constexpr uint8_t PIN_BUZZER = 32;  // passive buzzer, PWM
constexpr uint8_t PIN_LED    = 25;  // via 1k, active high

constexpr uint8_t LCD_ADDR = 0x27;
constexpr uint8_t LCD_COLS = 16;
constexpr uint8_t LCD_ROWS = 2;
