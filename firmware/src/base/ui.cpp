#include "ui.h"
#include <Arduino.h>
#include <stdarg.h>
#include "glcd.h"
#include "pins.h"
#include "state.h"

// Screen layout, 21 columns x 8 rows:
//   0  header: "SNAKES&LADDERS" + link status (right-aligned, 7 chars)
//   1  who is active and what to do (wire-schemas §4.2 phase table),
//      or an overlay: Connecting WiFi / broker, Controller offline, Paused
//   2  details: roll / cell / target / steps left, or the 2nd half of a hint
//   3  event flash for ~2 s ("P2 rolled 3!"), a separator line otherwise
//   4-7 one line per joined player: marker, id, cell, hp, OFF/SKIP
//      marker '>' = active player, '*' = winner
//
// LED: fast blink (4 Hz) while the active player has to roll, slow blink (1 Hz)
// while they walk (move/climb/slide), solid on after a win, off otherwise
// (lobby, paused, offline).

namespace {

constexpr uint32_t TICK_MS = 50;
constexpr uint32_t HEAL_MS = 1000;  // one full-line rewrite per second (see uiTask)
constexpr uint32_t LED_FAST_HALF_MS = 125;  // 4 Hz
constexpr uint32_t LED_SLOW_HALF_MS = 500;  // 1 Hz
constexpr uint8_t BACKLIGHT_PCT = 100;

constexpr uint8_t COLS = Glcd::COLS;
constexpr uint8_t ROWS = Glcd::ROWS;
constexpr uint8_t ROW_HEAD = 0, ROW_DO = 1, ROW_INFO = 2, ROW_FLASH = 3, ROW_PLAYERS = 4;

Glcd lcd;

struct Screen {
  char line[ROWS][COLS + 1];
};

void fmtNum(char* out, size_t n, int v) {
  if (v == NONE) strlcpy(out, "--", n);
  else snprintf(out, n, "%d", v);
}

// printf into a screen line; output longer than 21 chars is clipped (on purpose,
// via a wider scratch buffer so the compiler doesn't flag every format).
void line(Screen& sc, uint8_t row, const char* fmt, ...) __attribute__((format(printf, 3, 4)));
void line(Screen& sc, uint8_t row, const char* fmt, ...) {
  char buf[64];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  strlcpy(sc.line[row], buf, sizeof(sc.line[row]));
}


const char* linkStatus(const Shared& s) {
  if (!s.wifiUp) return "no wifi";
  if (!s.mqttUp) return "no mqtt";
  if (s.ctrl == Online::No) return "no ctrl";
  if (s.game.valid && s.game.paused) return " paused";
  return "     ok";
}

const PlayerInfo* findPlayer(const GameState& g, int p) {
  for (uint8_t i = 0; i < g.nPlayers; i++)
    if (g.players[i].p == p) return &g.players[i];
  return nullptr;
}

// "Roll 3 At 6 Left 2" (worst case "Roll 4 At 16 Left 12" = 20 chars)
void walkInfo(Screen& sc, const GameState& g) {
  char r[4], at[4], left[4];
  fmtNum(r, sizeof(r), g.roll);
  fmtNum(at, sizeof(at), g.cell);
  fmtNum(left, sizeof(left), g.dist);
  line(sc, ROW_INFO, "Roll %s At %s Left %s", r, at, left);
}

void composePhase(Screen& sc, const GameState& g) {
  char tgt[4];
  fmtNum(tgt, sizeof(tgt), g.target);
  switch (g.phase) {
    case Phase::Join:
      if (g.nPlayers >= MAX_PLAYERS) line(sc, ROW_DO, "%d players joined", g.nPlayers);
      else line(sc, ROW_DO, "Press: add player");
      line(sc, ROW_INFO, "%s", g.nPlayers >= 2 ? "Hold: start game" : "Need 2+ players");
      break;
    case Phase::Pairing:
      line(sc, ROW_DO, "Place P%d's meeple", g.joining);
      line(sc, ROW_INFO, "Press: cancel");
      break;
    case Phase::Setup:  // new game: every meeple back on the start cell
      line(sc, ROW_DO, "Put meeples on cell 1");
      line(sc, ROW_INFO, "Hold: start anyway");
      break;
    case Phase::Roll: {
      line(sc, ROW_DO, "P%d: press to roll", g.turn);
      char at[4];
      fmtNum(at, sizeof(at), g.cell);
      line(sc, ROW_INFO, "On cell %s", at);
      break;
    }
    case Phase::Move:
      line(sc, ROW_DO, "P%d: walk to cell %s", g.turn, tgt);
      walkInfo(sc, g);
      break;
    case Phase::Climb:
      line(sc, ROW_DO, "Ladder! P%d go to %s", g.turn, tgt);
      walkInfo(sc, g);
      break;
    case Phase::Slide:
      line(sc, ROW_DO, "Snake! P%d go to %s", g.turn, tgt);
      walkInfo(sc, g);
      break;
    case Phase::Over:
      if (g.winner != NONE) line(sc, ROW_DO, "P%d wins!", g.winner);
      else line(sc, ROW_DO, "Game over");
      line(sc, ROW_INFO, "Hold: new game");
      break;
    case Phase::Unknown:
      line(sc, ROW_DO, "Waiting for game...");
      break;
  }
}

// ">P2 cell 16 hp 4 SKIP"
void composePlayers(Screen& sc, const GameState& g) {
  if (g.nPlayers == 0) {
    if (g.valid) line(sc, ROW_PLAYERS, "No players yet");
    return;
  }
  for (uint8_t i = 0; i < g.nPlayers && ROW_PLAYERS + i < ROWS; i++) {
    const PlayerInfo& pl = g.players[i];
    char mark = ' ';
    if (g.state == Game::Finished && pl.p == g.winner) mark = '*';
    else if (g.state == Game::Running && pl.p == g.turn) mark = '>';
    char cell[4];
    fmtNum(cell, sizeof(cell), pl.cell);
    // Offline outranks skip: it is what blocks the game right now.
    const char* flag = !pl.on ? " OFF" : pl.skip ? " SKIP" : "";
    line(sc, ROW_PLAYERS + i, "%cP%d cell %2s hp %d%s", mark, pl.p, cell, pl.hp, flag);
  }
}

Screen compose(const Shared& s) {
  Screen sc{};
  const GameState& g = s.game;
  line(sc, ROW_HEAD, "SNAKES&LADDERS%7s", linkStatus(s));

  // Overlays take the instruction lines; player list (hp) stays visible.
  if (!s.wifiUp) {
    line(sc, ROW_DO, "Connecting WiFi...");
  } else if (!s.mqttUp) {
    line(sc, ROW_DO, "Connecting broker...");
  } else if (s.ctrl == Online::No) {
    line(sc, ROW_DO, "Controller offline");
    line(sc, ROW_INFO, "Waiting for it...");
  } else if (!g.valid) {
    line(sc, ROW_DO, "Waiting for game...");
  } else if (g.paused) {
    const PlayerInfo* act = findPlayer(g, g.turn);
    if (act && !act->on) {
      line(sc, ROW_DO, "P%d meeple offline", act->p);
      line(sc, ROW_INFO, "Hold: remove P%d", act->p);
    } else {
      line(sc, ROW_DO, "** Paused **");
      line(sc, ROW_INFO, "Waiting for devices");
    }
  } else {
    composePhase(sc, g);
  }

  if ((int32_t)(s.flashUntil - millis()) > 0 && s.flash[0]) line(sc, ROW_FLASH, "%s", s.flash);
  else memset(sc.line[ROW_FLASH], '-', COLS);  // Screen{} zeroed, so it stays terminated

  composePlayers(sc, g);
  return sc;
}

// Pads a line to exactly COLS chars (spaces), so two lines compare column by column.
void padded(const char* in, char* out) {
  bool ended = false;
  for (uint8_t i = 0; i < COLS; i++) {
    if (!ended && in[i] == '\0') ended = true;
    out[i] = ended ? ' ' : in[i];
  }
}

// Only sends the characters that changed. A cursor move costs 6 bytes, so changed
// stretches closer than that are merged into one write.
constexpr uint8_t MERGE_GAP = 6;

void draw(const Screen& sc, Screen& shown) {
  for (uint8_t row = 0; row < ROWS; row++) {
    char want[COLS], have[COLS];
    padded(sc.line[row], want);
    padded(shown.line[row], have);
    uint8_t i = 0;
    while (i < COLS) {
      if (want[i] == have[i]) { i++; continue; }
      uint8_t start = i, end = i, same = 0;  // [start, end] changed, end inclusive
      for (uint8_t j = i + 1; j < COLS && same < MERGE_GAP; j++) {
        if (want[j] != have[j]) { end = j; same = 0; } else same++;
      }
      lcd.writeAt(start, row, want + start, end - start + 1);
      i = end + 1;
    }
    memcpy(shown.line[row], want, COLS);
    shown.line[row][COLS] = '\0';
  }
}

// Marks every line as unknown so the next draw() rewrites all of them.
void invalidate(Screen& shown) {
  for (auto& l : shown.line) {  // 0x7f is never produced by compose()
    memset(l, '\x7f', COLS);
    l[COLS] = '\0';
  }
}

bool ledLevel(const Shared& s) {
  const GameState& g = s.game;
  if (!s.mqttUp || s.ctrl == Online::No || !g.valid) return false;
  if (g.state == Game::Finished && g.winner != NONE) return true;
  if (g.state != Game::Running || g.paused) return false;
  uint32_t half = 0;
  if (g.phase == Phase::Roll) half = LED_FAST_HALF_MS;
  else if (g.phase == Phase::Move || g.phase == Phase::Climb || g.phase == Phase::Slide) half = LED_SLOW_HALF_MS;
  return half && (millis() / half) % 2 == 0;
}

void uiTask(void*) {
  lcd.begin(Serial2, PIN_LCD_TX);  // waits out the splash screen
  lcd.clear();                     // the only full clear; after this lines are overwritten
  lcd.backlight(BACKLIGHT_PCT);

  Screen shown;
  invalidate(shown);
  Game lastState = Game::Unknown;
  uint8_t lastPlayers = 0xFF, healRow = 0;
  uint32_t lastHeal = millis();
  for (;;) {
    Shared s = stateSnapshot();
    digitalWrite(PIN_LED, ledLevel(s));
    // New game / game over / players joined: start from a clean screen. The backpack
    // sometimes drops characters, and the diff in draw() would never repaint them.
    if (s.game.state != lastState || s.game.nPlayers != lastPlayers) {
      lastState = s.game.state;
      lastPlayers = s.game.nPlayers;
      lcd.clear();
      invalidate(shown);
    }
    // Self-healing: rewrite one whole line per second, all 8 within ~8 s.
    if (millis() - lastHeal >= HEAL_MS) {
      lastHeal = millis();
      memset(shown.line[healRow], '\x7f', COLS);
      healRow = (healRow + 1) % ROWS;
    }
    draw(compose(s), shown);
    vTaskDelay(pdMS_TO_TICKS(TICK_MS));
  }
}

}  // namespace

void uiStart() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  xTaskCreatePinnedToCore(uiTask, "ui", 4096, nullptr, 1, nullptr, 1);
}
