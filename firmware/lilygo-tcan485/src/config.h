#pragma once

#include <Arduino.h>
#include "driver/twai.h"

static constexpr gpio_num_t CAN_TX_PIN = GPIO_NUM_27;
static constexpr gpio_num_t CAN_RX_PIN = GPIO_NUM_26;
static constexpr int CAN_SE_PIN = 23;
static constexpr uint8_t CAN_SE_ENABLE_LEVEL = LOW;

static constexpr uint32_t SERIAL_BAUD = 115200;
static constexpr uint32_t CAN_BITRATE = 500000;
static constexpr uint16_t SERIAL_COMMAND_MAX_LEN = 160;
static constexpr uint16_t CAN_RX_TIMEOUT_MS = 5;
static constexpr uint16_t CAN_TX_TIMEOUT_MS = 100;
