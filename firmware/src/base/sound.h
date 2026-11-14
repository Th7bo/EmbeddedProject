#pragma once
// Buzzer task: one-off event melodies from a queue, plus the local hot/cold beep.
#include <Arduino.h>

enum class Sound : uint8_t {
  Turn, Roll, Reached, Wrong, Ladder, Snake, HpLost, HpZero, TurnEnd, Paired, Win
};

struct SoundReq {
  Sound sound;
  uint8_t n;  // beep count for Roll, ignored otherwise
};

void soundStart();
void soundPlay(Sound s, uint8_t n = 0);  // non-blocking, safe from any task
