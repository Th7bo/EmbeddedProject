#include "ui.h"
#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "pins.h"
#include "state.h"

namespace {

LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);

constexpr uint32_t TICK_MS = 50;
constexpr uint32_t LED_HALF_PERIOD_MS = 250;  // ~2 Hz flash while it's our turn
constexpr char HEART = '\x01';                // custom glyph slot (0 would end C strings)

const uint8_t HEART_GLYPH[8] = {0b00000, 0b01010, 0b11111, 0b11111, 0b01110, 0b00100, 0b00000, 0b00000};

struct Screen {
  char line[2][LCD_COLS + 1];
};

void fmtNum(char* out, size_t n, int v) {
  if (v == NONE) strlcpy(out, "--", n);
  else snprintf(out, n, "%d", v);
}

// Top line: title on the left, hearts count right-aligned in the last 2 columns.
void title(Screen& sc, const Shared& s, const char* text) {
  if (s.status.valid) snprintf(sc.line[0], sizeof(sc.line[0]), "%-14.14s%c%d", text, HEART, s.status.hp);
  else snprintf(sc.line[0], sizeof(sc.line[0]), "%.16s", text);
}

void body(Screen& sc, const char* text) { snprintf(sc.line[1], sizeof(sc.line[1]), "%.16s", text); }

void walkLine(Screen& sc, const BaseStatus& st) {
  char at[4], go[4], left[4];
  fmtNum(at, sizeof(at), st.cell);
  fmtNum(go, sizeof(go), st.target);
  fmtNum(left, sizeof(left), st.dist);
  char buf[24];  // worst case is 16 chars ("At16 Go16 Left12"); body() clips anything longer
  snprintf(buf, sizeof(buf), "At%s Go%s Left%s", at, go, left);
  body(sc, buf);
}

Screen compose(const Shared& s) {
  Screen sc{};
  char buf[17];
  const BaseStatus& st = s.status;

  if (!s.wifiUp || !s.mqttUp) {
    title(sc, s, "Connecting...");
    body(sc, s.wifiUp ? "MQTT broker" : "Wi-Fi");
    return sc;
  }
  if (s.ctrl == Online::No) {
    title(sc, s, "Controller");
    body(sc, "offline");
    return sc;
  }
  if (s.game.state == Game::Finished) {
    title(sc, s, "Game over");
    if (s.game.winner != NONE && s.game.winner == st.p) body(sc, "You win!");
    else {
      snprintf(buf, sizeof(buf), "Player %d wins!", s.game.winner);
      body(sc, s.game.winner == NONE ? "" : buf);
    }
    return sc;
  }
  if (!st.valid) {
    title(sc, s, "S&L Hot or Cold");
    body(sc, "Waiting for ctrl");
    return sc;
  }

  // "P2 " prefix tells players which base is theirs.
  char head[15];
  auto withPlayer = [&](const char* t) {
    if (st.p > 0) snprintf(head, sizeof(head), "P%d %s", st.p, t);
    else strlcpy(head, t, sizeof(head));
    title(sc, s, head);
  };

  switch (st.phase) {
    case Phase::Unpaired:
      withPlayer("Welcome");
      body(sc, "Press to join");
      break;
    case Phase::Pairing:
      withPlayer("Pairing");
      body(sc, "Place meeple");
      break;
    case Phase::Wait:
      withPlayer("Waiting");
      if (st.skip) body(sc, "Skip next turn");
      else if (s.game.state == Game::Lobby && s.game.players >= 2) body(sc, "Hold to start");
      else if (s.game.state == Game::Lobby) body(sc, "Need 2 players");
      else if (s.game.turn != NONE) {
        snprintf(buf, sizeof(buf), "Player %d's turn", s.game.turn);
        body(sc, buf);
      } else body(sc, "");
      break;
    case Phase::Roll:
      withPlayer("Your turn!");
      body(sc, "Press to roll");
      break;
    case Phase::Move: {
      char r[4];
      fmtNum(r, sizeof(r), st.roll);
      snprintf(buf, sizeof(buf), "Rolled %s", r);
      withPlayer(buf);
      walkLine(sc, st);
      break;
    }
    case Phase::Slide:
      withPlayer("Snake!");
      walkLine(sc, st);
      break;
    case Phase::Climb:
      withPlayer("Ladder!");
      walkLine(sc, st);
      break;
    case Phase::Done:
      withPlayer("Turn done");
      body(sc, st.skip ? "Skip next turn" : "Next player...");
      break;
    case Phase::Unknown:
      withPlayer("");
      body(sc, "");
      break;
  }

  // Event flashes replace the detail line briefly; hp/title stay visible.
  if ((int32_t)(s.flashUntil - millis()) > 0 && s.flash[0]) body(sc, s.flash);
  return sc;
}

void draw(const Screen& sc, Screen& shown) {
  for (uint8_t row = 0; row < LCD_ROWS; row++) {
    // Only rewrite changed lines: a full redraw every tick flickers and hogs I2C.
    if (strcmp(sc.line[row], shown.line[row]) == 0) continue;
    char padded[LCD_COLS + 1];
    snprintf(padded, sizeof(padded), "%-16s", sc.line[row]);
    lcd.setCursor(0, row);
    lcd.print(padded);
    strlcpy(shown.line[row], sc.line[row], sizeof(shown.line[row]));
  }
}

bool ledLevel(const Shared& s) {
  if (s.game.state == Game::Finished && s.status.valid && s.status.p > 0 && s.game.winner == s.status.p)
    return true;
  if (s.mqttUp && s.ctrl != Online::No && s.status.valid && s.status.turn)
    return (millis() / LED_HALF_PERIOD_MS) % 2 == 0;
  return false;
}

void uiTask(void*) {
  Screen shown{};
  shown.line[0][0] = shown.line[1][0] = '\x7f';  // force the first draw
  for (;;) {
    Shared s = stateSnapshot();
    draw(compose(s), shown);
    digitalWrite(PIN_LED, ledLevel(s));
    vTaskDelay(pdMS_TO_TICKS(TICK_MS));
  }
}

}  // namespace

void uiStart() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  Wire.begin(PIN_SDA, PIN_SCL);
  lcd.init();
  lcd.backlight();
  lcd.createChar(HEART, const_cast<uint8_t*>(HEART_GLYPH));
  xTaskCreatePinnedToCore(uiTask, "ui", 4096, nullptr, 1, nullptr, 1);
}
