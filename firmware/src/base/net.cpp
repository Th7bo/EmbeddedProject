#include "net.h"
#include <WiFi.h>
#include <esp_mac.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "sound.h"
#include "state.h"

namespace {

// Queued publish request. Only the button publishes from other tasks today.
struct PubReq {
  char topic[48];
  char payload[8];
  bool retain;
  uint32_t queuedAt;
};

// A press made while offline is stale by the time we reconnect; replaying it
// could roll the dice for the wrong turn.
constexpr uint32_t PUB_MAX_AGE_MS = 2000;

QueueHandle_t g_pubQueue;
WiFiClient g_wifi;
PubSubClient g_mqtt(g_wifi);

char g_mac[13];
char g_clientId[24];
char t_online[40], t_button[40];
const char* T_STATE = TOPIC_PREFIX "game/state";
const char* T_EVENT = TOPIC_PREFIX "game/event";
const char* T_CTRL = TOPIC_PREFIX "ctrl/online";

// State JSON with 4 players is ~350 bytes; PubSubClient drops anything larger
// than its buffer silently, so leave plenty of margin.
constexpr uint16_t MQTT_BUFFER = 1024;
constexpr uint32_t FLASH_MS = 2000;

void setFlash(const char* text) {
  StateLock s;
  strlcpy(s->flash, text, sizeof(s->flash));
  s->flashUntil = millis() + FLASH_MS;
}

int intOrNone(JsonVariantConst v) { return v.is<int>() ? v.as<int>() : NONE; }

void onState(const JsonDocument& doc) {
  GameState g;
  g.valid = true;
  const char* state = doc["state"] | "";
  g.state = !strcmp(state, "lobby")      ? Game::Lobby
            : !strcmp(state, "running")  ? Game::Running
            : !strcmp(state, "finished") ? Game::Finished
                                         : Game::Unknown;
  g.phase = phaseFromString(doc["phase"] | "");
  g.turn = intOrNone(doc["turn"]);
  g.roll = intOrNone(doc["roll"]);
  g.target = intOrNone(doc["target"]);
  g.dist = intOrNone(doc["dist"]);
  g.cell = intOrNone(doc["cell"]);
  g.joining = intOrNone(doc["joining"]);
  g.winner = intOrNone(doc["winner"]);
  g.paused = doc["paused"] | false;
  for (JsonObjectConst pl : doc["players"].as<JsonArrayConst>()) {
    if (g.nPlayers >= MAX_PLAYERS) break;
    PlayerInfo& pi = g.players[g.nPlayers++];
    pi.p = pl["p"] | 0;
    pi.hp = pl["hp"] | 0;
    pi.cell = intOrNone(pl["cell"]);
    pi.skip = pl["skip"] | false;
    pi.on = pl["on"] | false;
  }
  StateLock s;
  s->game = g;
}

void onEvent(const JsonDocument& doc) {
  const char* e = doc["e"] | "";
  int p = doc["p"] | 0;
  char buf[FLASH_LEN + 1];
  // Every flash fits the 21-column line; snprintf clips just in case.
  if (!strcmp(e, "turn")) {
    soundPlay(Sound::Turn);
    snprintf(buf, sizeof(buf), "P%d's turn!", p);
  } else if (!strcmp(e, "roll")) {
    int n = doc["n"] | 0;
    soundPlay(Sound::Roll, n);
    snprintf(buf, sizeof(buf), "P%d rolled %d!", p, n);
  } else if (!strcmp(e, "reached")) {
    soundPlay(Sound::Reached);
    snprintf(buf, sizeof(buf), "P%d reached target!", p);
  } else if (!strcmp(e, "wrong")) {
    soundPlay(Sound::Wrong);
    snprintf(buf, sizeof(buf), "P%d: wrong cell!", p);
  } else if (!strcmp(e, "ladder")) {
    soundPlay(Sound::Ladder);
    snprintf(buf, sizeof(buf), "Ladder! go to %d", doc["to"] | 0);
  } else if (!strcmp(e, "snake")) {
    soundPlay(Sound::Snake);
    snprintf(buf, sizeof(buf), "Snake! go to %d", doc["to"] | 0);
  } else if (!strcmp(e, "hp_lost")) {
    soundPlay(Sound::HpLost);
    snprintf(buf, sizeof(buf), "P%d lost 1 HP!", p);
  } else if (!strcmp(e, "hp_zero")) {
    soundPlay(Sound::HpZero);
    snprintf(buf, sizeof(buf), "P%d 0 HP: skips next", p);
  } else if (!strcmp(e, "turn_end")) {
    soundPlay(Sound::TurnEnd);
    snprintf(buf, sizeof(buf), "P%d turn over", p);
  } else if (!strcmp(e, "joined")) {
    soundPlay(Sound::Joined);
    snprintf(buf, sizeof(buf), "P%d joined!", p);
  } else if (!strcmp(e, "win")) {
    soundPlay(Sound::Win);
    snprintf(buf, sizeof(buf), "P%d wins!!!", p);
  } else {
    Serial.printf("[mqtt] unknown event '%s'\n", e);
    return;
  }
  setFlash(buf);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  Serial.printf("[mqtt] < %s %.*s\n", topic, (int)len, (const char*)payload);

  if (!strcmp(topic, T_CTRL)) {
    bool up = len > 0 && payload[0] == '1';
    StateLock s;
    s->ctrl = up ? Online::Yes : Online::No;
    return;
  }

  // Deleting a retained message delivers an empty payload: forget the game.
  if (len == 0) {
    if (!strcmp(topic, T_STATE)) {
      StateLock s;
      s->game = GameState{};
    }
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, len);
  if (err) {
    Serial.printf("[mqtt] bad JSON on %s: %s\n", topic, err.c_str());
    return;
  }
  if (!strcmp(topic, T_STATE)) onState(doc);
  else if (!strcmp(topic, T_EVENT)) onEvent(doc);
}

void setLinks(bool wifi, bool mqtt) {
  StateLock s;
  s->wifiUp = wifi;
  s->mqttUp = mqtt;
}

bool mqttConnect() {
  Serial.printf("[mqtt] connecting to %s:%d as %s\n", MQTT_HOST, MQTT_PORT, g_clientId);
  // Clean session + LWT "0" retained, so the controller sees us drop within ~1.5x keepalive.
  if (!g_mqtt.connect(g_clientId, nullptr, nullptr, t_online, 0, true, "0", true)) {
    Serial.printf("[mqtt] connect failed, state %d\n", g_mqtt.state());
    return false;
  }
  g_mqtt.publish(t_online, "1", true);
  g_mqtt.subscribe(T_STATE, 1);
  g_mqtt.subscribe(T_EVENT, 1);
  g_mqtt.subscribe(T_CTRL, 1);
  Serial.println("[mqtt] connected");
  return true;
}

void drainPublishQueue() {
  PubReq r;
  while (xQueueReceive(g_pubQueue, &r, 0) == pdTRUE) {
    if (millis() - r.queuedAt > PUB_MAX_AGE_MS || !g_mqtt.connected()) {
      Serial.printf("[mqtt] dropped stale %s %s\n", r.topic, r.payload);
      continue;
    }
    g_mqtt.publish(r.topic, r.payload, r.retain);
    Serial.printf("[mqtt] > %s %s\n", r.topic, r.payload);
  }
}

void netTask(void*) {
  // Exponential backoff for both layers, so a missing router/broker doesn't
  // keep the radio busy and spam the log.
  constexpr uint32_t WIFI_RETRY_MIN = 10000, WIFI_RETRY_MAX = 60000;
  constexpr uint32_t MQTT_RETRY_MIN = 1000, MQTT_RETRY_MAX = 16000;
  uint32_t wifiRetry = WIFI_RETRY_MIN, wifiBegunAt = millis();
  uint32_t mqttRetry = MQTT_RETRY_MIN, mqttNextTry = 0;
  bool wifiWasUp = false, mqttWasUp = false;

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);

  for (;;) {
    bool wifiUp = WiFi.status() == WL_CONNECTED;
    if (wifiUp != wifiWasUp) {
      if (wifiUp) {
        Serial.printf("[wifi] connected, ip %s\n", WiFi.localIP().toString().c_str());
        wifiRetry = WIFI_RETRY_MIN;
        mqttRetry = MQTT_RETRY_MIN;
        mqttNextTry = millis();
      } else {
        Serial.println("[wifi] disconnected");
        wifiBegunAt = millis();
      }
      wifiWasUp = wifiUp;
    }

    if (!wifiUp) {
      // Auto-reconnect usually handles it; a fresh begin() covers the cases it doesn't.
      if (millis() - wifiBegunAt > wifiRetry) {
        Serial.printf("[wifi] retry (next in %lus)\n", (unsigned long)min(wifiRetry * 2, WIFI_RETRY_MAX) / 1000);
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASS);
        wifiBegunAt = millis();
        wifiRetry = min(wifiRetry * 2, WIFI_RETRY_MAX);
      }
    } else if (!g_mqtt.connected()) {
      if ((int32_t)(millis() - mqttNextTry) >= 0) {
        if (mqttConnect()) {
          mqttRetry = MQTT_RETRY_MIN;
        } else {
          mqttNextTry = millis() + mqttRetry;
          mqttRetry = min(mqttRetry * 2, MQTT_RETRY_MAX);
        }
      }
    } else {
      g_mqtt.loop();
    }

    bool mqttUp = g_mqtt.connected();
    if (mqttWasUp && !mqttUp) Serial.printf("[mqtt] disconnected, state %d\n", g_mqtt.state());
    mqttWasUp = mqttUp;
    setLinks(wifiUp, mqttUp);

    drainPublishQueue();
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

}  // namespace

void netStart() {
  g_pubQueue = xQueueCreate(8, sizeof(PubReq));

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);  // valid before the radio is up
  snprintf(g_mac, sizeof(g_mac), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  snprintf(g_clientId, sizeof(g_clientId), "snl-base-%s", g_mac);
  snprintf(t_online, sizeof(t_online), TOPIC_PREFIX "base/%s/online", g_mac);
  snprintf(t_button, sizeof(t_button), TOPIC_PREFIX "base/%s/button", g_mac);
  Serial.printf("[net] device id %s\n", g_mac);

  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  g_mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  g_mqtt.setBufferSize(MQTT_BUFFER);
  g_mqtt.setSocketTimeout(2);  // bounds how long a dead broker can stall this task
  g_mqtt.setCallback(onMessage);

  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 2, nullptr, 0);
}

void netPublishButton(bool longPress) {
  PubReq r{};
  strlcpy(r.topic, t_button, sizeof(r.topic));
  strlcpy(r.payload, longPress ? "long" : "short", sizeof(r.payload));
  r.retain = false;
  r.queuedAt = millis();
  if (xQueueSend(g_pubQueue, &r, 0) != pdTRUE) Serial.println("[net] publish queue full");
}
