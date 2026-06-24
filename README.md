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
├── infra/                    # Docker Compose: MQTT, Redpanda, Postgres
├── packages/
│   └── shared/               # Shared TypeScript telemetry types
├── simulator/                # Go MQTT telemetry simulator
├── docs/                     # Architecture notes
└── Taskfile.yml              # Local workflow commands
```

## Requirements

- Go
- Python 3.9+
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
- Go simulator publishing fake OBD telemetry
- React SPA on `5173`

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
```

Write/reset/flashing UDS operations are intentionally not exposed as one-line commands. Add explicit allowlisted operations before using dangerous ECU services.

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

The Go backend forwards the same envelope to browser clients over WebSocket.

## Security

- No WiFi passwords, MQTT passwords, API keys, or tokens should be committed.
- Firmware defaults use placeholders only.
- Keep `.env` local; commit only `.env.example`.
- The default car-facing path is read-only OBD-II polling.
- Do not expose arbitrary CAN or UDS write commands through the web app.

## Documentation

See [docs/architecture.md](docs/architecture.md).
