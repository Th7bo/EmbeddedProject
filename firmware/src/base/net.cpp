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
char t_online[40], t_button[40], t_status[40], t_event[40];
const char* T_GAME = TOPIC_PREFIX "game/state";
const char* T_CTRL = TOPIC_PREFIX "ctrl/online";

void setFlash(const char* text) {
  StateLock s;
  strlcpy(s->flash, text, sizeof(s->flash));
  s->flashUntil = millis() + 2000;
}

int intOrNone(JsonVariantConst v) { return v.is<int>() ? v.as<int>() : NONE; }

void onStatus(const JsonDocument& doc) {
  BaseStatus st;
  st.valid = true;
  st.p = doc["p"] | 0;
  st.hp = doc["hp"] | 0;
  st.cell = intOrNone(doc["cell"]);
  st.roll = intOrNone(doc["roll"]);
  st.target = intOrNone(doc["target"]);
  st.dist = intOrNone(doc["dist"]);
  st.turn = doc["turn"] | false;
  st.skip = doc["skip"] | false;
  st.phase = phaseFromString(doc["phase"] | "");
  StateLock s;
  s->status = st;
}

void onGame(const JsonDocument& doc) {
  GameState g;
  const char* state = doc["state"] | "";
  g.state = !strcmp(state, "lobby")      ? Game::Lobby
            : !strcmp(state, "running")  ? Game::Running
            : !strcmp(state, "finished") ? Game::Finished
                                         : Game::Unknown;
  g.players = doc["players"].as<JsonArrayConst>().size();
  g.turn = intOrNone(doc["turn"]);
  g.winner = intOrNone(doc["winner"]);
  StateLock s;
  s->game = g;
}

void onEvent(const JsonDocument& doc) {
  const char* e = doc["e"] | "";
  char buf[17];
  if (!strcmp(e, "turn")) {
    soundPlay(Sound::Turn);
    setFlash("Your turn!");
  } else if (!strcmp(e, "roll")) {
    int n = doc["n"] | 0;
    soundPlay(Sound::Roll, n);
    snprintf(buf, sizeof(buf), "You rolled %d!", n);
    setFlash(buf);
  } else if (!strcmp(e, "reached")) {
    soundPlay(Sound::Reached);
    setFlash("Target reached!");
  } else if (!strcmp(e, "wrong")) {
    soundPlay(Sound::Wrong);
    setFlash("Wrong cell!");
  } else if (!strcmp(e, "ladder")) {
    soundPlay(Sound::Ladder);
    snprintf(buf, sizeof(buf), "Ladder! go to %d", doc["to"] | 0);
    setFlash(buf);
  } else if (!strcmp(e, "snake")) {
    soundPlay(Sound::Snake);
    snprintf(buf, sizeof(buf), "Snake! go to %d", doc["to"] | 0);
    setFlash(buf);
  } else if (!strcmp(e, "hp_lost")) {
    soundPlay(Sound::HpLost);
    setFlash("Lost 1 HP!");
  } else if (!strcmp(e, "hp_zero")) {
    soundPlay(Sound::HpZero);
    setFlash("0 HP: skip turn");
  } else if (!strcmp(e, "turn_end")) {
    soundPlay(Sound::TurnEnd);
    setFlash("Turn over");
  } else if (!strcmp(e, "paired")) {
    soundPlay(Sound::Paired);
    setFlash("Paired!");
  } else if (!strcmp(e, "win")) {
    soundPlay(Sound::Win);
    snprintf(buf, sizeof(buf), "Player %d wins!", doc["p"] | 0);
    setFlash(buf);
  } else {
    Serial.printf("[mqtt] unknown event '%s'\n", e);
  }
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  Serial.printf("[mqtt] < %s %.*s\n", topic, (int)len, (const char*)payload);

  if (!strcmp(topic, T_CTRL)) {
    bool up = len > 0 && payload[0] == '1';
    StateLock s;
    s->ctrl = up ? Online::Yes : Online::No;
    return;
  }

  // Deleting a retained message delivers an empty payload; nothing to parse.
  if (len == 0) return;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, len);
  if (err) {
    Serial.printf("[mqtt] bad JSON on %s: %s\n", topic, err.c_str());
    return;
  }
  if (!strcmp(topic, t_status)) onStatus(doc);
  else if (!strcmp(topic, t_event)) onEvent(doc);
  else if (!strcmp(topic, T_GAME)) onGame(doc);
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
  g_mqtt.subscribe(t_status, 1);
  g_mqtt.subscribe(t_event, 1);
  g_mqtt.subscribe(T_GAME, 1);
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
  snprintf(t_status, sizeof(t_status), TOPIC_PREFIX "base/%s/status", g_mac);
  snprintf(t_event, sizeof(t_event), TOPIC_PREFIX "base/%s/event", g_mac);
  Serial.printf("[net] device id %s\n", g_mac);

  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  g_mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  g_mqtt.setBufferSize(512);
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
