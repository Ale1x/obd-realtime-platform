#pragma once

#include <Arduino.h>
#include "driver/twai.h"

bool canDriverStart();
bool canDriverSend(const twai_message_t &frame, uint32_t timeoutMs, esp_err_t &err);
bool canDriverReceive(twai_message_t &frame, uint32_t timeoutMs, esp_err_t &err);
void canDriverPrintStatus();
