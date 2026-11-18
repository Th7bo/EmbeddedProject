#pragma once
// ADM12864H 128x64 graphic LCD behind a SparkFun Serial Graphic LCD backpack
// (LCD-09352), driven one-way over UART. Every command starts with 0x7C.
// Text uses the backpack's 6x8 font: 21 columns x 8 rows.
//
// The backpack has a tiny input buffer and draws slowly, so writes are paced
// and the screen is never cleared after start-up: callers overwrite whole
// fixed-width lines (writeLine pads to 21 chars) and only the ones that changed.
#include <Arduino.h>

class Glcd {
 public:
  static constexpr uint8_t COLS = 21;
  static constexpr uint8_t ROWS = 8;
  static constexpr uint8_t WIDTH = 128;
  static constexpr uint8_t HEIGHT = 64;

  // Starts the UART (TX only) and waits out the backpack's splash screen.
  // Blocks ~1 s; call it from a task, not before the scheduler matters.
  void begin(HardwareSerial& port, int8_t txPin, uint32_t baud = 115200);

  void clear();
  void backlight(uint8_t percent);  // 0-100
  void reverseToggle();             // inverts the whole screen

  // Writes text at the start of `row`, padded/clipped to exactly COLS chars.
  void writeLine(uint8_t row, const char* text);
  // Writes `len` chars of `text` starting at column `col` (no padding). Used to
  // update only the part of a line that changed: the backpack draws every glyph
  // in software, so fewer bytes = a faster, more reliable screen.
  void writeAt(uint8_t col, uint8_t row, const char* text, uint8_t len);

  // Pixel coordinates, (0,0) top-left regardless of LCD_Y_FROM_TOP.
  void box(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2);
  void erase(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2);

 private:
  void cmd(const uint8_t* bytes, size_t n);
  void setTextPos(uint8_t col, uint8_t row);
  static uint8_t yPix(uint8_t yTop);  // top-left y -> backpack y
  HardwareSerial* port_ = nullptr;
};
