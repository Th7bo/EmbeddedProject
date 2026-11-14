#pragma once
// Network task: owns Wi-Fi and the PubSubClient. Other tasks never touch the
// client (it is not thread-safe); they hand messages over via netPublishButton().
#include <Arduino.h>

void netStart();
void netPublishButton(bool longPress);  // non-blocking, safe from any task
