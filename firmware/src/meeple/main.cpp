// Meeple (ESP-01): reads the RFID tag under the meeple and publishes it over MQTT,
// drives its LED from the controller. Contract: docs/wire-schemas.md
//
// LED at boot: 3 slow blinks = ESP-01 + LED OK. While the PN532 is missing the LED
// flickers very fast (20 Hz) and init is retried every 2 s.
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_PN532.h>
#include "config.h"
#include "pins.h"

ADC_MODE(ADC_VCC);  // ESP.getVcc() reads the supply voltage, A0 is not wired anyway

// Timing
constexpr uint32_t POLL_TIMEOUT_MS = 100;    // one PN532 read attempt
constexpr uint8_t TAG_MISSES_FOR_GONE = 3;   // ~300 ms debounce before publishing "-"
constexpr uint32_t BATT_PERIOD_MS = 60000;
constexpr uint32_t PN532_RETRY_MS = 2000;

Adafruit_PN532 nfc(-1, -1, &Wire);  // no IRQ / reset lines on the ESP-01
WiFiClient wifi;
PubSubClient mqtt(wifi);

String mac;  // lowercase hex, no separators
String topicOnline, topicTag, topicBatt, topicLed;
const char *TOPIC_CTRL_ONLINE = TOPIC_PREFIX "ctrl/online";

enum class LedMode { Off, On, Slow, Fast, Error };
LedMode ledMode = LedMode::Off;   // what the controller asked for
bool ctrlOnline = false;
bool nfcOk = false;

String tag = "-";        // last published value
uint8_t misses = 0;

// ---------------------------------------------------------------- LED

static void blink(uint8_t times, uint16_t ms) {
  for (uint8_t i = 0; i < times; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(ms);
    digitalWrite(PIN_LED, LOW);
    delay(ms);
  }
}

static void updateLed() {
  LedMode mode = !nfcOk ? LedMode::Error : (ctrlOnline ? ledMode : LedMode::Off);
  uint32_t t = millis();
  bool on = false;
  switch (mode) {
    case LedMode::Off:   on = false; break;
    case LedMode::On:    on = true; break;
    case LedMode::Slow:  on = (t / 500) % 2; break;   // ~1 Hz
    case LedMode::Fast:  on = (t / 125) % 2; break;   // ~4 Hz
    case LedMode::Error: on = (t / 25) % 2; break;    // 20 Hz flicker
  }
  digitalWrite(PIN_LED, on);
}

// ---------------------------------------------------------------- PN532

static bool nfcInit() {
  uint32_t version = 0;
  if (!nfc.begin() || !(version = nfc.getFirmwareVersion())) {
    Serial.println("PN532 not found");
    return false;
  }
  Serial.printf("PN532 found: chip PN5%02X, firmware %u.%u\n", (unsigned)(version >> 24) & 0xFF,
                (unsigned)(version >> 16) & 0xFF, (unsigned)(version >> 8) & 0xFF);
  nfc.SAMConfig();
  return true;
}

// Returns the UID under the reader, or "" when none was seen in this poll.
static String readTag() {
  uint8_t uid[10];
  uint8_t len = 0;
  if (!nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &len, POLL_TIMEOUT_MS)) return "";
  char hex[21];
  for (uint8_t i = 0; i < len && i < 10; i++) sprintf(hex + 2 * i, "%02X", uid[i]);
  return String(hex);
}

static void publishTag() {
  if (mqtt.connected()) mqtt.publish(topicTag.c_str(), tag.c_str(), true);
  Serial.printf("tag %s\n", tag.c_str());
}

// New UID: publish at once. Missing UID: only after a few misses (the PN532 drops reads).
static void pollTag() {
  String uid = readTag();
  if (uid.length()) {
    misses = 0;
    if (uid != tag) {
      tag = uid;
      publishTag();
    }
  } else if (tag != "-" && ++misses >= TAG_MISSES_FOR_GONE) {
    tag = "-";
    publishTag();
  }
}

// ---------------------------------------------------------------- MQTT

static void publishBatt() {
  if (!mqtt.connected()) return;
  char mv[8];
  snprintf(mv, sizeof mv, "%u", ESP.getVcc());
  mqtt.publish(topicBatt.c_str(), mv, true);
}

static void onMessage(char *topic, uint8_t *payload, unsigned int len) {
  String msg;
  msg.reserve(len);
  for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
  Serial.printf("rx %s = %s\n", topic, msg.c_str());

  if (topicLed == topic) {
    if (msg == "on") ledMode = LedMode::On;
    else if (msg == "slow") ledMode = LedMode::Slow;
    else if (msg == "fast") ledMode = LedMode::Fast;
    else ledMode = LedMode::Off;
  } else if (strcmp(topic, TOPIC_CTRL_ONLINE) == 0) {
    ctrlOnline = msg == "1";
  }
}

// Non-blocking: one connect attempt per call, at most every 2 s.
static void mqttMaintain() {
  static uint32_t lastTry = 0;
  if (mqtt.connected()) {
    mqtt.loop();
    return;
  }
  if (WiFi.status() != WL_CONNECTED || millis() - lastTry < 2000) return;
  lastTry = millis();

  String clientId = "snl-meeple-" + mac;
  Serial.printf("MQTT connect %s:%d ... ", MQTT_HOST, MQTT_PORT);
  if (!mqtt.connect(clientId.c_str(), topicOnline.c_str(), 0, true, "0")) {
    Serial.printf("failed (%d)\n", mqtt.state());
    return;
  }
  Serial.println("ok");
  mqtt.publish(topicOnline.c_str(), "1", true);
  mqtt.subscribe(topicLed.c_str(), 1);
  mqtt.subscribe(TOPIC_CTRL_ONLINE, 1);
  publishTag();  // controller rebuilds positions from this
  publishBatt();
}

// ---------------------------------------------------------------- main

void setup() {
  Serial.begin(115200, SERIAL_8N1, SERIAL_TX_ONLY);  // RX pin is the LED
  pinMode(PIN_LED, OUTPUT);
  Serial.println("\nmeeple boot");
  blink(3, 300);

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  mac = WiFi.macAddress();
  mac.replace(":", "");
  mac.toLowerCase();
  String base = String(TOPIC_PREFIX "meeple/") + mac + "/";
  topicOnline = base + "online";
  topicTag = base + "tag";
  topicBatt = base + "batt";
  topicLed = base + "led";
  Serial.printf("id %s\n", mac.c_str());

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  mqtt.setSocketTimeout(2);  // a dead broker must not freeze tag polling for long
  mqtt.setCallback(onMessage);

  Wire.begin(PIN_SDA, PIN_SCL);
  nfcOk = nfcInit();
}

void loop() {
  static uint32_t lastBatt = 0, lastNfcTry = 0;
  static bool wifiWas = false;

  bool wifiNow = WiFi.status() == WL_CONNECTED;
  if (wifiNow != wifiWas) {
    wifiWas = wifiNow;
    Serial.printf("WiFi %s %s\n", wifiNow ? "up" : "down", wifiNow ? WiFi.localIP().toString().c_str() : "");
  }
  mqttMaintain();

  if (nfcOk) {
    pollTag();
  } else if (millis() - lastNfcTry > PN532_RETRY_MS) {
    lastNfcTry = millis();
    nfcOk = nfcInit();
  }

  if (millis() - lastBatt > BATT_PERIOD_MS) {
    lastBatt = millis();
    publishBatt();
  }
  updateLed();
  delay(1);  // let the Wi-Fi stack run
}
