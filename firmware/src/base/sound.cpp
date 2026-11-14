#include "sound.h"
#include "pins.h"
#include "state.h"

namespace {

QueueHandle_t g_queue;

struct Note {
  uint16_t freq;  // 0 = rest
  uint16_t ms;
};

// Hot/cold beep: interval between beep starts, per wire-schemas §4.2.
// dist > 4 is not in the table; we beep every 1200 ms so "far away" still
// sounds alive but clearly colder than dist 4.
uint32_t beepInterval(int dist) {
  switch (dist) {
    case 1: return 100;
    case 2: return 250;
    case 3: return 500;
    case 4: return 800;
    default: return dist > 4 ? 1200 : 0;  // 0 or null: silent
  }
}

constexpr uint16_t BEEP_HZ = 1800;

void playNotes(const Note* notes, size_t count) {
  for (size_t i = 0; i < count; i++) {
    if (notes[i].freq) tone(PIN_BUZZER, notes[i].freq);
    else noTone(PIN_BUZZER);
    vTaskDelay(pdMS_TO_TICKS(notes[i].ms));
  }
  noTone(PIN_BUZZER);
}

#define PLAY(...)                                     \
  do {                                                \
    static const Note seq[] = {__VA_ARGS__};          \
    playNotes(seq, sizeof(seq) / sizeof(seq[0]));     \
  } while (0)

void playEvent(const SoundReq& r) {
  switch (r.sound) {
    case Sound::Turn:    PLAY({2400, 80}, {0, 80}, {2400, 80}); break;
    case Sound::Roll:
      for (uint8_t i = 0; i < r.n && i < 6; i++) PLAY({1500, 70}, {0, 130});
      break;
    case Sound::Reached: PLAY({1320, 1000}); break;
    case Sound::Wrong:   PLAY({300, 90}, {0, 90}, {300, 90}, {0, 90}, {300, 90}); break;
    case Sound::Ladder:  PLAY({784, 120}, {988, 120}, {1319, 200}); break;     // G5 B5 E6
    case Sound::Snake:   PLAY({1319, 120}, {988, 120}, {659, 250}); break;     // E6 B5 E5
    case Sound::HpLost:  PLAY({220, 700}); break;
    case Sound::HpZero:
      // Sweep down in small steps so a plain tone() sounds like a glide.
      for (uint16_t f = 800; f >= 150; f -= 25) {
        tone(PIN_BUZZER, f);
        vTaskDelay(pdMS_TO_TICKS(40));
      }
      noTone(PIN_BUZZER);
      break;
    case Sound::TurnEnd: PLAY({1000, 60}); break;
    case Sound::Paired:  PLAY({1047, 90}, {1568, 160}); break;                 // C6 G6
    case Sound::Win:
      PLAY({523, 120}, {659, 120}, {784, 120}, {1047, 250}, {0, 60}, {784, 120}, {1047, 400});
      break;
  }
}

// Hot/cold beeping only while it is our turn and the player is walking.
int activeDist(const Shared& s) {
  if (!s.mqttUp || s.ctrl == Online::No || !s.status.valid || !s.status.turn) return NONE;
  Phase ph = s.status.phase;
  if (ph != Phase::Move && ph != Phase::Slide && ph != Phase::Climb) return NONE;
  return s.status.dist;
}

void soundTask(void*) {
  uint32_t nextBeep = 0;
  for (;;) {
    // Wait for an event, but wake in time for the next hot/cold beep.
    uint32_t interval = beepInterval(activeDist(stateSnapshot()));
    TickType_t wait = pdMS_TO_TICKS(50);
    if (interval) {
      int32_t left = (int32_t)(nextBeep - millis());
      wait = left > 0 ? pdMS_TO_TICKS(min<int32_t>(left, 50)) : 0;
    }

    SoundReq req;
    if (xQueueReceive(g_queue, &req, wait) == pdTRUE) {
      // Events run to completion; the beep loop simply isn't running meanwhile,
      // so they never overlap. Leave a short gap before beeping resumes.
      playEvent(req);
      nextBeep = millis() + 300;
      continue;
    }

    interval = beepInterval(activeDist(stateSnapshot()));
    if (!interval) {
      nextBeep = millis();  // first beep starts immediately once walking begins
      continue;
    }
    if ((int32_t)(millis() - nextBeep) >= 0) {
      uint32_t len = min<uint32_t>(50, interval / 2);
      tone(PIN_BUZZER, BEEP_HZ);
      vTaskDelay(pdMS_TO_TICKS(len));
      noTone(PIN_BUZZER);
      nextBeep += interval;
      // After a long pause (event, phase change) don't try to catch up.
      if ((int32_t)(millis() - nextBeep) > 0) nextBeep = millis() + interval - len;
    }
  }
}

}  // namespace

void soundStart() {
  g_queue = xQueueCreate(8, sizeof(SoundReq));
  pinMode(PIN_BUZZER, OUTPUT);
  xTaskCreatePinnedToCore(soundTask, "sound", 3072, nullptr, 3, nullptr, 1);
}

void soundPlay(Sound s, uint8_t n) {
  SoundReq r{s, n};
  xQueueSend(g_queue, &r, 0);  // drop if 8 sounds are already queued
}
