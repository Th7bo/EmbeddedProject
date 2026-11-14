#pragma once
// State shared between tasks. Everything in Shared is guarded by one mutex:
// writers are rare (MQTT messages), readers copy a snapshot and work on that.
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

constexpr int NONE = -1;  // stands for JSON null in int fields

enum class Phase : uint8_t { Unknown, Unpaired, Pairing, Wait, Roll, Move, Slide, Climb, Done };
enum class Game : uint8_t { Unknown, Lobby, Running, Finished };
enum class Online : uint8_t { Unknown, No, Yes };

struct BaseStatus {
  bool valid = false;  // false until the first retained status arrives
  int p = 0;
  int hp = 0;
  int cell = NONE;
  int roll = NONE;
  int target = NONE;
  int dist = NONE;
  bool turn = false;
  bool skip = false;
  Phase phase = Phase::Unknown;
};

struct GameState {
  Game state = Game::Unknown;
  int players = 0;  // only the count is shown
  int turn = NONE;
  int winner = NONE;
};

struct Shared {
  bool wifiUp = false;
  bool mqttUp = false;
  Online ctrl = Online::Unknown;
  BaseStatus status;
  GameState game;
  char flash[17] = "";     // short LCD message triggered by an event
  uint32_t flashUntil = 0; // millis() when the flash expires
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
