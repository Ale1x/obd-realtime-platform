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
MQTT_TOPIC=obd/v1/+/+
KAFKA_BROKERS=localhost:19092
KAFKA_TOPIC_RAW=obd.telemetry.raw
KAFKA_ENABLED=true
```

## Endpoints

```text
GET /health
GET /metrics
GET /ws
```

`/metrics` is scraped by Prometheus and exposes `obd_signal_value`, `obd_health_value`, packet counters and WebSocket client count.
