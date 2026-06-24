# OBD realtime architecture

## Obiettivo

Costruire una piattaforma OBD affidabile e realtime partendo dal prototipo ESP32/LILYGO T-CAN485 gia testato in auto.

La direzione scelta e:

```text
ESP32/LILYGO
  CAN / OBD-II
  MQTT QoS 1
      |
      v
MQTT broker
      |
      v
Backend ingest
      |
      +--> WebSocket live API --> Web app
      |
      +--> Redpanda/Kafka stream log
      |
      +--> PostgreSQL/TimescaleDB storico
```

## Principi

- L'ESP32 deve fare poco e farlo bene: acquisizione CAN, scheduler OBD, buffer locale, pubblicazione MQTT.
- Il browser non deve parlare con il dispositivo: parla con il backend via WebSocket.
- MQTT e il protocollo edge: leggero, robusto in riconnessione, adatto a microcontrollori.
- Redpanda/Kafka e il log eventi: replay, piu consumer indipendenti, analytics, alerting, esportazioni.
- Il backend e il confine di fiducia: valida payload, timestampa, normalizza, decide cosa salvare e cosa trasmettere live.
- Ogni dato deve avere timestamp, sequenza e freshness. Un valore vecchio non deve sembrare live.

## Componenti

### Firmware ESP32 gateway

Responsabilita:

- Inizializzare TWAI/CAN a 500 kbps.
- Scoprire PID OBD-II supportati all'avvio.
- Eseguire polling OBD con scheduler a priorita.
- Pubblicare telemetria MQTT.
- Pubblicare health del dispositivo e stato bus.
- Gestire riconnessione WiFi/MQTT senza bloccare il loop CAN.
- Limitare traffico verso ECU per non saturare la rete veicolo.

Da rimuovere nel percorso target:

- Web server HTML embedded.
- Polling HTTP `/api`.
- `Serial.print` per ogni frame in modalita produzione.
- Credenziali WiFi hardcoded.

### MQTT broker

Scelta iniziale:

- Locale/dev: Mosquitto.
- Produzione o multi-device: EMQX oppure HiveMQ CE.

QoS:

- Telemetria live: QoS 0 o QoS 1 in base al profilo.
- Health/status: QoS 1.
- Comandi verso device: QoS 1.

Retained:

- `status` retained.
- `health` non retained o retained solo per ultimo snapshot.
- `telemetry` non retained.

### Backend ingest Go

Responsabilita:

- Sottoscrivere topic MQTT.
- Validare schema e versione payload.
- Aggiungere `receivedAt`.
- Calcolare latenze e freshness.
- Pubblicare eventi raw/normalized su Redpanda.
- Salvare snapshot/sessioni su PostgreSQL/TimescaleDB.
- Esporre WebSocket ai client web.
- Esporre REST per health, sessioni, storico, configurazione device.

Implementazione iniziale:

- Go standard `net/http`.
- `github.com/eclipse/paho.mqtt.golang` per MQTT.
- `github.com/gorilla/websocket` per WebSocket.
- `github.com/segmentio/kafka-go` per Redpanda/Kafka.

### Redpanda stream log

Serve quando vogliamo:

- Replay di una sessione.
- Piu consumer indipendenti.
- Alerting separato dal live backend.
- Esportazione dati.
- Analytics successiva.

Topic consigliati:

```text
obd.telemetry.raw
obd.telemetry.normalized
obd.health
obd.events
obd.commands
```

Chiave evento:

```text
deviceId
```

Cosi gli eventi dello stesso device restano ordinati nella stessa partition.

### PostgreSQL / TimescaleDB

Serve per:

- Sessioni di guida.
- Query storiche.
- Grafici retrospettivi.
- Aggregazioni per minuto/secondo.
- Diagnostica device.

Tabelle iniziali:

```text
devices
drive_sessions
telemetry_points
device_health
device_events
```

## Data flow live

1. Firmware legge risposta OBD.
2. Firmware aggiorna snapshot locale.
3. Firmware pubblica evento MQTT.
4. Backend riceve e valida.
5. Backend inoltra subito via WebSocket ai client iscritti.
6. Backend produce evento su Redpanda.
7. Storage writer salva su database.

Il path realtime per la UI non aspetta il database.

## MQTT topic design

```text
obd/v1/{deviceId}/telemetry
obd/v1/{deviceId}/health
obd/v1/{deviceId}/status
obd/v1/{deviceId}/events
obd/v1/{deviceId}/command
```

Esempio telemetria:

```json
{
  "schema": "obd.telemetry.v1",
  "deviceId": "lilygo-001",
  "seq": 10422,
  "deviceTsMs": 923441,
  "sessionId": "2026-06-24T18-40-12Z-lilygo-001",
  "signals": {
    "rpm": 1840,
    "speedKmh": 52,
    "throttlePct": 18.4,
    "coolantC": 88
  },
  "health": {
    "rssi": -61,
    "txFailures": 0,
    "lastResponseAgeMs": 35
  }
}
```

Esempio health:

```json
{
  "schema": "obd.health.v1",
  "deviceId": "lilygo-001",
  "seq": 322,
  "deviceTsMs": 923500,
  "wifi": {
    "rssi": -61,
    "connected": true
  },
  "mqtt": {
    "connected": true,
    "queuedMessages": 0
  },
  "can": {
    "state": "running",
    "rxFrames": 12840,
    "txRequests": 1840,
    "txFailures": 0,
    "busErrors": 0
  }
}
```

## WebSocket API

Endpoint:

```text
GET /ws
```

Messaggi server-to-client:

```json
{
  "type": "telemetry",
  "deviceId": "lilygo-001",
  "receivedAt": "2026-06-24T18:40:12.250Z",
  "payload": {}
}
```

Messaggi client-to-server:

```json
{
  "type": "subscribe",
  "deviceId": "lilygo-001"
}
```

All'inizio si puo broadcastare tutto a tutti. Quando ci saranno piu device o utenti, il backend deve filtrare per autorizzazione e subscription.

## Scheduler OBD

Non tutti i PID devono avere la stessa frequenza.

Fast group:

```text
rpm, speedKmh, throttlePct, loadPct, mafGps
```

Target: 5-10 Hz complessivi compatibilmente con ECU.

Slow group:

```text
coolantC, oilTempC, ambientTempC, intakeTempC, voltage, fuelLevelPct
```

Target: 0.5-1 Hz.

Diagnostic group:

```text
runtimeSec, distanceSinceClearKm, barometricKpa, DTC status
```

Target: ogni 5-30 s o on-demand.

Regole:

- Una richiesta in flight alla volta per ECU functional polling.
- Timeout esplicito per PID.
- Backoff per PID che non rispondono.
- Priorita ai segnali usati dalla dashboard live.
- Misurare `requestSentAt`, `responseAt`, `latencyMs`.

## Affidabilita

### Device

- Ring buffer RAM per messaggi quando MQTT cade.
- Drop policy esplicita: per telemetria live si scarta il piu vecchio, per eventi diagnostici si conserva.
- Sequence number monotono.
- Watchdog abilitato.
- Nessuna operazione di rete bloccante nel task CAN.

### MQTT

- Last Will Testament su `obd/v1/{deviceId}/status`.
- Keepalive breve, per esempio 15-30 s.
- Reconnect con backoff.
- QoS 1 per health/status/comandi.

### Backend

- Idempotenza via `(deviceId, seq)`.
- Validazione schema.
- Metriche ingest: msg/sec, lag, errori parse, reconnect device.
- WebSocket heartbeat/ping.
- Backpressure: se un client web e lento, si disconnette o riceve snapshot ridotto.

### Stream

- Retention topic raw: breve in dev, estesa in prod.
- Retention normalized: in base a sessioni.
- Consumer group separati: live, storage, alerts.

## Latenza target

Budget ragionevole locale:

```text
OBD request/response:    20-150 ms
ESP32 -> MQTT broker:     5-50 ms
Backend processing:       1-10 ms
WebSocket -> browser:     5-30 ms
UI render:               16-50 ms
```

Target end-to-end:

```text
p50 < 150 ms
p95 < 400 ms
offline detection < 3 s
```

La latenza reale sara dominata dall'ECU e dallo scheduler PID, non dal WebSocket.

## Sicurezza

- Non committare SSID/password.
- Configurare firmware con `secrets.h` locale o provisioning.
- MQTT con user/password in LAN; TLS se fuori LAN.
- Nessun comando CAN arbitrario dalla web app.
- Allowlist comandi backend-device.
- Modalita read-only come default.
- Rate limit su ogni comando verso device.

## Roadmap

### Fase 1: monorepo e simulatore

- Backend Go MQTT -> WebSocket.
- React SPA live minimale.
- Simulatore Go che pubblica telemetria MQTT senza ESP e senza auto.
- Docker Compose con MQTT, Redpanda, Postgres.
- Script simulatore che pubblica telemetria MQTT.

### Fase 2: firmware MQTT

- Estrarre credenziali.
- Aggiungere client MQTT.
- Pubblicare `telemetry`, `health`, `status`.
- Rimuovere web server embedded dalla modalita produzione.

### Fase 3: storage e replay

- Redpanda producer nel backend Go.
- Storage writer verso TimescaleDB.
- Session start/stop.
- Replay sessione nella web app.

### Fase 4: produzione

- Auth utenti/device.
- TLS MQTT.
- OTA firmware.
- Metriche Prometheus.
- Alerting.
- Multi-device.

## Decisioni iniziali

- Edge protocol: MQTT.
- Browser protocol: WebSocket.
- Stream log: Redpanda/Kafka-compatible.
- Storage: PostgreSQL con estensione TimescaleDB quando serve time-series serio.
- Frontend: app separata dal firmware.
- Firmware: gateway real-time, non web server applicativo.
