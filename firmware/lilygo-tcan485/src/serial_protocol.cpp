#include "serial_protocol.h"

#include "can_driver.h"
#include "config.h"

static String commandLine;

static int hexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static bool parseByte(const String &hex, uint8_t &value) {
  if (hex.length() != 2) {
    return false;
  }

  int high = hexValue(hex.charAt(0));
  int low = hexValue(hex.charAt(1));
  if (high < 0 || low < 0) {
    return false;
  }

  value = static_cast<uint8_t>((high << 4) | low);
  return true;
}

static String nextToken(String &line) {
  line.trim();
  int space = line.indexOf(' ');
  if (space < 0) {
    String token = line;
    line = "";
    return token;
  }

  String token = line.substring(0, space);
  line = line.substring(space + 1);
  line.trim();
  return token;
}

void serialProtocolPrintReady() {
  Serial.println("{\"type\":\"ready\",\"mode\":\"serial-can-bridge\",\"protocol\":\"line-json-v1\"}");
}

void serialProtocolPrintFrame(const twai_message_t &frame) {
  Serial.print("{\"type\":\"rx\",\"ts\":");
  Serial.print(millis());
  Serial.print(",\"id\":");
  Serial.print(frame.identifier);
  Serial.print(",\"extended\":");
  Serial.print(frame.extd ? "true" : "false");
  Serial.print(",\"rtr\":");
  Serial.print(frame.rtr ? "true" : "false");
  Serial.print(",\"dlc\":");
  Serial.print(frame.data_length_code);
  Serial.print(",\"data\":\"");

  for (uint8_t i = 0; i < frame.data_length_code; i++) {
    if (frame.data[i] < 0x10) {
      Serial.print('0');
    }
    Serial.print(frame.data[i], HEX);
  }

  Serial.println("\"}");
}

void serialProtocolPrintError(const char *message) {
  Serial.print("{\"type\":\"err\",\"ts\":");
  Serial.print(millis());
  Serial.print(",\"message\":\"");
  Serial.print(message);
  Serial.println("\"}");
}

static void printTxResult(bool ok, esp_err_t err) {
  Serial.print("{\"type\":\"tx\",\"ts\":");
  Serial.print(millis());
  Serial.print(",\"ok\":");
  Serial.print(ok ? "true" : "false");
  Serial.print(",\"err\":");
  Serial.print(static_cast<int>(err));
  Serial.println("}");
}

static void handleTxCommand(String line) {
  bool extended = false;
  String command = nextToken(line);

  if (command == "TXE") {
    extended = true;
  } else if (command != "TX") {
    serialProtocolPrintError("unknown command");
    return;
  }

  String idToken = nextToken(line);
  String dlcToken = nextToken(line);
  if (idToken.length() == 0 || dlcToken.length() == 0) {
    serialProtocolPrintError("usage: TX id dlc bytes...");
    return;
  }

  twai_message_t frame = {};
  frame.identifier = strtoul(idToken.c_str(), nullptr, 16);
  frame.extd = extended ? 1 : 0;
  frame.rtr = 0;
  frame.data_length_code = static_cast<uint8_t>(dlcToken.toInt());
  if (frame.data_length_code > 8) {
    serialProtocolPrintError("dlc too large");
    return;
  }

  for (uint8_t i = 0; i < frame.data_length_code; i++) {
    String byteToken = nextToken(line);
    if (!parseByte(byteToken, frame.data[i])) {
      serialProtocolPrintError("invalid data byte");
      return;
    }
  }

  esp_err_t err = ESP_OK;
  bool ok = canDriverSend(frame, CAN_TX_TIMEOUT_MS, err);
  printTxResult(ok, err);
}

static void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) {
    return;
  }

  if (line == "PING") {
    Serial.print("{\"type\":\"pong\",\"ts\":");
    Serial.print(millis());
    Serial.println("}");
    return;
  }

  if (line == "STATUS") {
    canDriverPrintStatus();
    return;
  }

  if (line == "RECOVER") {
    canDriverRecover();
    return;
  }

  handleTxCommand(line);
}

void serialProtocolService() {
  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      handleCommand(commandLine);
      commandLine = "";
      continue;
    }

    if (commandLine.length() >= SERIAL_COMMAND_MAX_LEN) {
      commandLine = "";
      serialProtocolPrintError("command too long");
      continue;
    }

    commandLine += c;
  }
}
