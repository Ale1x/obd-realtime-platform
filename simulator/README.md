# OBD simulator

Publisher MQTT per sviluppo locale senza ESP e senza auto.

## Run

```sh
go run .
```

Default:

```text
MQTT_URL=tcp://localhost:1883
DEVICE_ID=dev-simulator
SIM_RATE_MS=200
```

Topic pubblicato:

```text
obd/v1/dev-simulator/telemetry
```
