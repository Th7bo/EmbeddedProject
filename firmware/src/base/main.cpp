// Control base for Snakes & Ladders: Hot or Cold.
// MQTT contract: docs/wire-schemas.md. Each concern runs in its own FreeRTOS task:
//   net   (core 0) Wi-Fi + MQTT, the only task touching PubSubClient
//   input (core 1) button debounce -> short/long publish requests
//   sound (core 1) event melodies + local hot/cold beeping
//   ui    (core 1) LCD + turn LED
// Tasks share state through state.h (mutex) and talk via queues.
#include <Arduino.h>
#include "input.h"
#include "net.h"
#include "sound.h"
#include "state.h"
#include "ui.h"

void setup() {
  Serial.begin(115200);
  Serial.println("\n[base] boot");
  stateInit();
  soundStart();  // before net: incoming events push into the sound queue
  uiStart();
  netStart();
  inputStart();  // last: it publishes through net's queue
}

void loop() {
  vTaskDelete(nullptr);  // all work happens in the tasks above
}
