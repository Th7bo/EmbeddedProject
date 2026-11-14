#include "state.h"
#include <string.h>

static Shared g_shared;
static SemaphoreHandle_t g_mutex;

void stateInit() { g_mutex = xSemaphoreCreateMutex(); }

StateLock::StateLock() { xSemaphoreTake(g_mutex, portMAX_DELAY); }
StateLock::~StateLock() { xSemaphoreGive(g_mutex); }
Shared& StateLock::operator*() { return g_shared; }
Shared* StateLock::operator->() { return &g_shared; }

Shared stateSnapshot() {
  StateLock lock;
  return *lock;
}

Phase phaseFromString(const char* s) {
  if (!s) return Phase::Unknown;
  static const struct { const char* name; Phase phase; } map[] = {
      {"unpaired", Phase::Unpaired}, {"pairing", Phase::Pairing}, {"wait", Phase::Wait},
      {"roll", Phase::Roll},         {"move", Phase::Move},       {"slide", Phase::Slide},
      {"climb", Phase::Climb},       {"done", Phase::Done},
  };
  for (const auto& m : map)
    if (strcmp(s, m.name) == 0) return m.phase;
  return Phase::Unknown;
}
