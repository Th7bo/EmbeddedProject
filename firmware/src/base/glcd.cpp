#include "glcd.h"

namespace {

// Depending on the backpack firmware version, the Y coordinate counts from the
// top of the screen or from the bottom. If the 8 text lines show up in reverse
// order (header at the bottom), flip this flag.
constexpr bool LCD_Y_FROM_TOP = false;  // our backpack counts from the bottom (tested 2026-11-17)

constexpr uint8_t CMD = 0x7C;
constexpr uint32_t SPLASH_MS = 1100;   // backpack shows its splash for ~1 s after power-up
constexpr uint32_t CLEAR_MS = 50;      // a full clear takes the backpack a while
constexpr size_t CHUNK = 7;            // bytes sent before pausing, well under the input buffer
constexpr uint32_t CHUNK_GAP_MS = 2;   // ~7 glyphs drawn per gap
constexpr uint32_t CMD_GAP_MS = 2;

void pause(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms) ? pdMS_TO_TICKS(ms) : 1); }

}  // namespace

void Glcd::begin(HardwareSerial& port, int8_t txPin, uint32_t baud) {
  port_ = &port;
  // RX = -1: the backpack never talks back, so no pin is spent on it.
  port_->begin(baud, SERIAL_8N1, -1, txPin);
  pause(SPLASH_MS);
}

void Glcd::cmd(const uint8_t* bytes, size_t n) {
  port_->write(bytes, n);
  port_->flush();  // wait until it is on the wire, then give the backpack time
  pause(CMD_GAP_MS);
}

uint8_t Glcd::yPix(uint8_t yTop) { return LCD_Y_FROM_TOP ? yTop : (HEIGHT - 1) - yTop; }

void Glcd::clear() {
  const uint8_t c[] = {CMD, 0x00};
  cmd(c, sizeof(c));
  pause(CLEAR_MS);
}

void Glcd::backlight(uint8_t percent) {
  const uint8_t c[] = {CMD, 0x02, (uint8_t)min<uint8_t>(percent, 100)};
  cmd(c, sizeof(c));
}

void Glcd::reverseToggle() {
  const uint8_t c[] = {CMD, 0x12};
  cmd(c, sizeof(c));
  pause(CLEAR_MS);  // redraws the whole screen
}

void Glcd::setTextPos(uint8_t col, uint8_t row) {
  // Text position is in pixels and refers to the top-left corner of the glyph.
  const uint8_t c[] = {CMD, 0x18, (uint8_t)(col * 6), CMD, 0x19, yPix(row * 8)};
  cmd(c, sizeof(c));
}

void Glcd::writeLine(uint8_t row, const char* text) {
  char line[COLS];
  bool ended = false;
  for (uint8_t i = 0; i < COLS; i++) {
    char ch = ended ? '\0' : text[i];
    if (ch == '\0') ended = true;
    line[i] = ch ? ch : ' ';
  }
  writeAt(0, row, line, COLS);
}

void Glcd::writeAt(uint8_t col, uint8_t row, const char* text, uint8_t len) {
  if (!port_ || row >= ROWS || col >= COLS) return;
  len = min<uint8_t>(len, COLS - col);
  char out[COLS];
  for (uint8_t i = 0; i < len; i++) {
    char ch = text[i];
    // Only plain printable ASCII: control bytes move the cursor and '|' (0x7C)
    // would start a command.
    if (ch < 0x20 || ch > 0x7E || ch == '|') ch = ch == '|' ? '!' : ' ';
    out[i] = ch;
  }
  setTextPos(col, row);
  for (size_t i = 0; i < len; i += CHUNK) {
    port_->write(reinterpret_cast<const uint8_t*>(out + i), min<size_t>(CHUNK, len - i));
    port_->flush();
    pause(CHUNK_GAP_MS);
  }
}

void Glcd::box(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2) {
  const uint8_t c[] = {CMD, 0x0F, x1, yPix(y1), x2, yPix(y2), 1};
  cmd(c, sizeof(c));
}

void Glcd::erase(uint8_t x1, uint8_t y1, uint8_t x2, uint8_t y2) {
  const uint8_t c[] = {CMD, 0x05, x1, yPix(y1), x2, yPix(y2)};
  cmd(c, sizeof(c));
}
