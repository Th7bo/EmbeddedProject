// Hardware smoke test for the meeple: prints the UID of the tag under the
// PN532 and lights the LED while a tag is present.
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PN532.h>
#include "pins.h"

Adafruit_PN532 nfc(-1, -1, &Wire);  // no IRQ / reset lines on the ESP-01

void setup() {
  Serial.begin(115200, SERIAL_8N1, SERIAL_TX_ONLY);  // RX pin is the LED
  pinMode(PIN_LED, OUTPUT);

  Wire.begin(PIN_SDA, PIN_SCL);
  if (!nfc.begin() || !nfc.getFirmwareVersion()) {
    Serial.println("PN532 not found");
    for (;;) {
      digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      delay(100);
    }
  }
  nfc.SAMConfig();
  Serial.println("PN532 ready");
}

void loop() {
  uint8_t uid[10];
  uint8_t len = 0;
  bool found = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &len, 100);

  digitalWrite(PIN_LED, found);
  if (found) {
    for (uint8_t i = 0; i < len; i++) Serial.printf("%02X", uid[i]);
    Serial.println();
  }
}
