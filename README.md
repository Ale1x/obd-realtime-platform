# OBD Realtime Platform

Realtime OBD/CAN platform with:

- LILYGO T-CAN485 / ESP32 firmware as a serial CAN bridge.
- Python edge layer using idiomatic automotive libraries.
- MQTT ingest.
- Go backend with WebSocket live API.
- React SPA dashboard.
- Local simulator for development without a car.

## Architecture

```text
Car CAN / OBD-II
  -> LILYGO ESP32 serial CAN bridge
  -> Python edge layer
  -> MQTT
  -> Go backend
  -> WebSocket
  -> React dashboard
```

For local development without the car:

```text
Go simulator -> MQTT -> Go backend -> WebSocket -> React dashboard
```

## Repository Layout

```text
.
├── backend/                  # Go MQTT ingest + WebSocket API
├── edge-python/              # Python CAN/OBD/UDS/DBC edge layer
├── firmware/
│   └── lilygo-tcan485/       # PlatformIO firmware for LILYGO T-CAN485
├── frontend/                 # React SPA
├── infra/                    # Docker Compose: MQTT, Redpanda, Postgres, Prometheus, Grafana
├── packages/
│   └── shared/               # Shared TypeScript telemetry types
├── simulator/                # Go MQTT telemetry simulator
├── docs/                     # Architecture notes
└── Taskfile.yml              # Local workflow commands
```

## Requirements

- Go
- Python 3.10+
- Node.js + pnpm
- Docker or OrbStack
- PlatformIO
- Taskfile (`task`)

## First Setup

```sh
task setup
```

This creates local dependency folders such as `node_modules/`, `frontend/node_modules/`, Python virtualenvs, and build caches. They are required for local development only and are ignored by Git.

## Local Dev Without Car

```sh
task dev
```

Open:

```text
http://localhost:5173/
```

This starts:

- Mosquitto MQTT on `1883`
- Go backend on `3000`
- Prometheus on `9090`
- Grafana on `3002`
- Go simulator publishing fake OBD telemetry
- React SPA on `5173`

Grafana login:

```text
http://localhost:3002/
user: admin
password: obd
```

The pre-provisioned dashboard is `OBD / OBD Live`.

## Real Car Dev With LILYGO

Flash the bridge firmware once:

```sh
task firmware:upload
```

Then plug the LILYGO into the car OBD port and into the computer via USB, then run:

```sh
SERIAL_PORT=/dev/cu.usbserial-5B320392561 task dev:edge
```

Open:

```text
http://localhost:5173/
```

If the serial port changes:

```sh
ls /dev/cu.usbserial*
SERIAL_PORT=/dev/cu.usbserial-XXXX task dev:edge
```

`task dev:edge` starts MQTT, backend, Python edge, and frontend. The Python edge polls OBD-II through the LILYGO serial CAN bridge and publishes:

```text
obd/v1/lilygo-python/telemetry
obd/v1/lilygo-python/status
```

At startup the Python edge also publishes one read-only diagnostic snapshot with supported PIDs, VIN and DTCs. That snapshot populates the dashboard `Diagnostic Summary`.

## Python Automotive Layer

The Python edge is where advanced automotive tooling belongs:

- `python-can`: idiomatic CAN bus interface.
- `can-isotp`: ISO-TP transport.
- `udsoncan`: UDS diagnostic client.
- `cantools`: DBC/ARXML/KCD/SYM decoding and encoding.
- optional `python-OBD` for ELM327 style adapters.

The current CLI exposes safe read paths:

```sh
task edge:poll-obd
task edge:sniff
task edge:scan-obd
SERVICE=09 PID=02 task edge:obd-request
DID=F190 TX_ID=7E0 RX_ID=7E8 task edge:uds-read-did
TX_ID=7E0 RX_ID=7E8 task edge:uds-scan-common
```

Write/reset/flashing UDS operations are intentionally not exposed as one-line commands. Add explicit allowlisted operations before using dangerous ECU services.

Read-only advanced features currently implemented:

- supported PID discovery
- VIN read via OBD Mode 09 PID 02
- stored DTC read via Mode 03
- pending DTC read via Mode 07
- permanent DTC read via Mode 0A
- raw OBD request/response
- UDS ReadDataByIdentifier over ISO-TP
- common UDS DID scan for VIN, ECU software, ECU hardware, supplier and serial metadata

## Useful Tasks

```sh
task --list
task setup
task dev
task dev:edge
task test
task firmware:build
task firmware:upload
task edge:poll-obd
task edge:sniff
task edge:scan-obd
task edge:obd-request
task edge:uds-read-did
task edge:uds-scan-common
task infra:up
task infra:down
```

## Telemetry Contract

Telemetry is published as MQTT JSON:

```json
{
  "schema": "obd.telemetry.v1",
  "deviceId": "lilygo-python",
  "seq": 1,
  "deviceTsMs": 1000,
  "sessionId": "session-id",
  "signals": {
    "rpm": 1200,
    "speedKmh": 42
  },
  "health": {
    "txRequests": 10,
    "txFailures": 0,
    "rxFrames": 12,
    "obdResponses": 10,
    "lastResponseAgeMs": 20
  }
}
```

The Go backend forwards telemetry, status and diagnostic event envelopes to browser clients over WebSocket.

## Prometheus And Grafana

The backend exposes metrics at:

```text
http://localhost:3000/metrics
```

Prometheus scrapes the backend every second and stores the latest telemetry as time-series:

```text
obd_signal_value{device_id="...",signal="rpm"}
obd_health_value{device_id="...",metric="txRequests"}
obd_telemetry_packets_total
obd_websocket_clients
```

Start observability:

```sh
task infra:observability
```

Open:

```text
Prometheus: http://localhost:9090/
Grafana:    http://localhost:3002/
```

## Security

- No WiFi passwords, MQTT passwords, API keys, or tokens should be committed.
- Firmware defaults use placeholders only.
- Keep `.env` local; commit only `.env.example`.
- The default car-facing path is read-only OBD-II polling.
- Do not expose arbitrary CAN or UDS write commands through the web app.

## Documentation

See [docs/architecture.md](docs/architecture.md).
