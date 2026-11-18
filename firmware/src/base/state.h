#pragma once
// State shared between tasks. Everything in Shared is guarded by one mutex:
// writers are rare (MQTT messages), readers copy a snapshot and work on that.
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

constexpr int NONE = -1;  // stands for JSON null in int fields
constexpr uint8_t MAX_PLAYERS = 4;

// wire-schemas §4.2 `phase`
enum class Phase : uint8_t { Unknown, Join, Pairing, Setup, Roll, Move, Climb, Slide, Over };
enum class Game : uint8_t { Unknown, Lobby, Running, Finished };
enum class Online : uint8_t { Unknown, No, Yes };

struct PlayerInfo {
  int p = 0;
  int hp = 0;
  int cell = NONE;
  bool skip = false;
  bool on = false;  // meeple online
};

// Mirror of the retained snl/game/state JSON.
struct GameState {
  bool valid = false;  // false until the first retained state arrives
  Game state = Game::Unknown;
  Phase phase = Phase::Unknown;
  int turn = NONE;
  int roll = NONE;
  int target = NONE;
  int dist = NONE;
  int cell = NONE;
  int joining = NONE;
  int winner = NONE;
  bool paused = false;
  uint8_t nPlayers = 0;
  PlayerInfo players[MAX_PLAYERS];
};

constexpr size_t FLASH_LEN = 21;  // one LCD line

struct Shared {
  bool wifiUp = false;
  bool mqttUp = false;
  Online ctrl = Online::Unknown;
  GameState game;
  char flash[FLASH_LEN + 1] = "";  // short LCD message triggered by an event
  uint32_t flashUntil = 0;         // millis() when the flash expires
};

void stateInit();

// Scoped lock so every early return releases the mutex.
class StateLock {
 public:
  StateLock();
  ~StateLock();
  Shared& operator*();
  Shared* operator->();
};

Shared stateSnapshot();
Phase phaseFromString(const char* s);
