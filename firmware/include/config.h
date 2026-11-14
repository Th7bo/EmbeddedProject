#pragma once
// Shared network config for base + meeple. Topic contract: docs/wire-schemas.md
#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "include/secrets.h missing, using secrets.example.h placeholders"
#include "secrets.example.h"
#endif

#define TOPIC_PREFIX "snl/"
constexpr uint16_t MQTT_KEEPALIVE_S = 5;
