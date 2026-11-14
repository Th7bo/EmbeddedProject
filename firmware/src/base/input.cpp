#include "input.h"
#include <Arduino.h>
#include "net.h"
#include "pins.h"

namespace {

constexpr uint32_t POLL_MS = 5;
constexpr uint32_t DEBOUNCE_MS = 30;
constexpr uint32_t LONG_MS = 2000;

void inputTask(void*) {
  bool stable = false;      // debounced state, true = pressed
  bool raw = false;
  uint32_t rawSince = millis();
  uint32_t pressedAt = 0;
  bool longSent = false;

  for (;;) {
    bool now = digitalRead(PIN_BUTTON) == LOW;
    if (now != raw) {
      raw = now;
      rawSince = millis();
    }

    if (raw != stable && millis() - rawSince >= DEBOUNCE_MS) {
      stable = raw;
      if (stable) {
        pressedAt = millis();
        longSent = false;
      } else if (!longSent) {
        // Short press is only known on release, once we're sure it wasn't long.
        Serial.println("[btn] short");
        netPublishButton(false);
      }
    }

    // Long fires while still held, so the player gets feedback without letting go.
    if (stable && !longSent && millis() - pressedAt >= LONG_MS) {
      longSent = true;
      Serial.println("[btn] long");
      netPublishButton(true);
    }

    vTaskDelay(pdMS_TO_TICKS(POLL_MS));
  }
}

}  // namespace

void inputStart() {
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  xTaskCreatePinnedToCore(inputTask, "input", 2048, nullptr, 4, nullptr, 1);
}
