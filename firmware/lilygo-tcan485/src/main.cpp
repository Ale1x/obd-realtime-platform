#include <Arduino.h>

#include "can_driver.h"
#include "config.h"
#include "serial_protocol.h"

static bool canReady = false;

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);

  serialProtocolPrintReady();
  canReady = canDriverStart();
}

void loop() {
  serialProtocolService();

  if (!canReady) {
    delay(250);
    return;
  }

  canDriverService();

  twai_message_t frame = {};
  esp_err_t err = ESP_OK;
  if (canDriverReceive(frame, CAN_RX_TIMEOUT_MS, err)) {
    serialProtocolPrintFrame(frame);
  } else if (err != ESP_ERR_TIMEOUT) {
    serialProtocolPrintError("twai receive failed");
  }
}
