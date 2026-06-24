#pragma once

#include <Arduino.h>
#include "driver/twai.h"

void serialProtocolPrintReady();
void serialProtocolPrintFrame(const twai_message_t &frame);
void serialProtocolPrintError(const char *message);
void serialProtocolService();
