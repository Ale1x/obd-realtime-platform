# OBD edge Python

Python edge layer for:

```text
Auto CAN/OBD -> LILYGO serial CAN bridge -> Python automotive stack -> MQTT -> Go backend
```

The backend and web app do not change. This app publishes the same telemetry shape used by the Go simulator:

```text
obd/v1/{deviceId}/telemetry
obd/v1/{deviceId}/status
```

## Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Run OBD-II polling through the LILYGO

Flash the firmware with `APP_MODE MODE_SERIAL_CAN_BRIDGE`, then:

```sh
.venv/bin/obd-edge poll-obd \
  --serial /dev/cu.usbserial-5B320392561 \
  --mqtt tcp://localhost:1883 \
  --device-id lilygo-python
```

## Sniff raw CAN

```sh
.venv/bin/obd-edge sniff \
  --serial /dev/cu.usbserial-5B320392561 \
  --mqtt tcp://localhost:1883 \
  --device-id lilygo-python
```

## Advanced read-only diagnostics

```sh
.venv/bin/obd-edge scan-obd --serial /dev/cu.usbserial-5B320392561
.venv/bin/obd-edge obd-request --serial /dev/cu.usbserial-5B320392561 --service 09 --pid 02
.venv/bin/obd-edge uds-read-did --serial /dev/cu.usbserial-5B320392561 --tx-id 7E0 --rx-id 7E8 --did F190
.venv/bin/obd-edge uds-scan-common --serial /dev/cu.usbserial-5B320392561 --tx-id 7E0 --rx-id 7E8
```

Implemented read-only operations:

- supported PID discovery
- VIN read
- stored, pending and permanent DTC reads
- raw OBD request/response
- UDS ReadDataByIdentifier over ISO-TP
- common UDS DID scan for VIN, ECU software, ECU hardware, supplier and serial metadata

## Advanced stack

The package installs the core libraries for idiomatic automotive Python:

- `python-can`: CAN BusABC adapter exposed by `LilygoSerialBus`.
- `can-isotp`: ISO-TP transport can be mounted on the bus.
- `udsoncan`: UDS client can run over ISO-TP.
- `cantools`: DBC/ARXML/KCD/SYM decoding.
- optional `python-OBD`: ELM327 style adapters, separate from LILYGO bridge.

Dangerous write/reset/flashing operations are intentionally not exposed as CLI commands yet. Add explicit allowlisted commands before using UDS services that write to an ECU.
