#include "can_driver.h"

#include "config.h"

static bool timingForBitrate(uint32_t bitrate, twai_timing_config_t &timingConfig) {
  switch (bitrate) {
    case 125000:
      timingConfig = TWAI_TIMING_CONFIG_125KBITS();
      return true;
    case 250000:
      timingConfig = TWAI_TIMING_CONFIG_250KBITS();
      return true;
    case 500000:
      timingConfig = TWAI_TIMING_CONFIG_500KBITS();
      return true;
    case 1000000:
      timingConfig = TWAI_TIMING_CONFIG_1MBITS();
      return true;
    default:
      return false;
  }
}

static const char *twaiStateName(twai_state_t state) {
  switch (state) {
    case TWAI_STATE_STOPPED:
      return "stopped";
    case TWAI_STATE_RUNNING:
      return "running";
    case TWAI_STATE_BUS_OFF:
      return "bus_off";
    case TWAI_STATE_RECOVERING:
      return "recovering";
    default:
      return "unknown";
  }
}

bool canDriverStart() {
  pinMode(CAN_SE_PIN, OUTPUT);
  digitalWrite(CAN_SE_PIN, CAN_SE_ENABLE_LEVEL);

  twai_timing_config_t timingConfig = {};
  if (!timingForBitrate(CAN_BITRATE, timingConfig)) {
    Serial.println("{\"type\":\"err\",\"message\":\"unsupported bitrate\"}");
    return false;
  }

  twai_general_config_t generalConfig = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
  twai_filter_config_t filterConfig = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  esp_err_t err = twai_driver_install(&generalConfig, &timingConfig, &filterConfig);
  if (err != ESP_OK) {
    Serial.print("{\"type\":\"err\",\"message\":\"twai install failed\",\"err\":");
    Serial.print(static_cast<int>(err));
    Serial.println("}");
    return false;
  }

  err = twai_start();
  if (err != ESP_OK) {
    Serial.print("{\"type\":\"err\",\"message\":\"twai start failed\",\"err\":");
    Serial.print(static_cast<int>(err));
    Serial.println("}");
    twai_driver_uninstall();
    return false;
  }

  uint32_t alerts = TWAI_ALERT_RX_DATA | TWAI_ALERT_BUS_ERROR | TWAI_ALERT_RX_QUEUE_FULL |
                    TWAI_ALERT_TX_FAILED | TWAI_ALERT_ARB_LOST | TWAI_ALERT_BUS_OFF |
                    TWAI_ALERT_BUS_RECOVERED | TWAI_ALERT_ERR_PASS | TWAI_ALERT_ABOVE_ERR_WARN;
  twai_reconfigure_alerts(alerts, nullptr);

  Serial.print("{\"type\":\"can_ready\",\"bitrate\":");
  Serial.print(CAN_BITRATE);
  Serial.println("}");
  return true;
}

bool canDriverSend(const twai_message_t &frame, uint32_t timeoutMs, esp_err_t &err) {
  err = twai_transmit(&frame, pdMS_TO_TICKS(timeoutMs));
  return err == ESP_OK;
}

bool canDriverReceive(twai_message_t &frame, uint32_t timeoutMs, esp_err_t &err) {
  err = twai_receive(&frame, pdMS_TO_TICKS(timeoutMs));
  return err == ESP_OK;
}

void canDriverPrintStatus() {
  twai_status_info_t status = {};
  esp_err_t err = twai_get_status_info(&status);
  if (err != ESP_OK) {
    Serial.print("{\"type\":\"err\",\"message\":\"twai status failed\",\"err\":");
    Serial.print(static_cast<int>(err));
    Serial.println("}");
    return;
  }

  Serial.print("{\"type\":\"status\",\"state\":\"");
  Serial.print(twaiStateName(status.state));
  Serial.print("\",\"rxq\":");
  Serial.print(status.msgs_to_rx);
  Serial.print(",\"txq\":");
  Serial.print(status.msgs_to_tx);
  Serial.print(",\"rxErr\":");
  Serial.print(status.rx_error_counter);
  Serial.print(",\"txErr\":");
  Serial.print(status.tx_error_counter);
  Serial.print(",\"busErr\":");
  Serial.print(status.bus_error_count);
  Serial.print(",\"rxMissed\":");
  Serial.print(status.rx_missed_count);
  Serial.print(",\"rxOverrun\":");
  Serial.print(status.rx_overrun_count);
  Serial.print(",\"arbLost\":");
  Serial.print(status.arb_lost_count);
  Serial.print(",\"txFailed\":");
  Serial.print(status.tx_failed_count);
  Serial.println("}");
}
