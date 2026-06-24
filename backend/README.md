# OBD backend

Backend Go per ingest realtime:

```text
MQTT broker -> Go backend -> WebSocket clients
                         -> Redpanda topic
```

## Run

```sh
go run .
```

## Environment

```sh
HTTP_ADDR=:3000
MQTT_URL=tcp://localhost:1883
MQTT_TOPIC=obd/v1/+/telemetry
KAFKA_BROKERS=localhost:19092
KAFKA_TOPIC_RAW=obd.telemetry.raw
KAFKA_ENABLED=true
```

## Endpoints

```text
GET /health
GET /ws
```
