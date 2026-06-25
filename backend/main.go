package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/gorilla/websocket"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/segmentio/kafka-go"
)

type Config struct {
	HTTPAddr      string
	MQTTURL       string
	MQTTTopic     string
	KafkaEnabled  bool
	KafkaBrokers  []string
	KafkaTopicRaw string
}

type LiveEnvelope struct {
	Type       string          `json:"type"`
	DeviceID   string          `json:"deviceId"`
	ReceivedAt string          `json:"receivedAt"`
	Payload    json.RawMessage `json:"payload"`
}

type TelemetryHeader struct {
	Schema   string `json:"schema"`
	DeviceID string `json:"deviceId"`
}

type TelemetryPayload struct {
	Schema     string              `json:"schema"`
	DeviceID   string              `json:"deviceId"`
	Seq        uint64              `json:"seq"`
	DeviceTsMs int64               `json:"deviceTsMs"`
	SessionID  string              `json:"sessionId"`
	Signals    map[string]*float64 `json:"signals"`
	Health     map[string]*float64 `json:"health"`
}

type Hub struct {
	mu      sync.RWMutex
	clients map[*websocket.Conn]struct{}
}

func NewHub() *Hub {
	return &Hub{clients: make(map[*websocket.Conn]struct{})}
}

func (h *Hub) Add(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[conn] = struct{}{}
}

func (h *Hub) Remove(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.clients, conn)
	_ = conn.Close()
}

func (h *Hub) Broadcast(payload []byte) {
	h.mu.RLock()
	clients := make([]*websocket.Conn, 0, len(h.clients))
	for conn := range h.clients {
		clients = append(clients, conn)
	}
	h.mu.RUnlock()

	for _, conn := range clients {
		_ = conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
		if err := conn.WriteMessage(websocket.TextMessage, payload); err != nil {
			log.Printf("websocket write failed: %v", err)
			h.Remove(conn)
		}
	}
}

func (h *Hub) Count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

func main() {
	config := loadConfig()
	hub := NewHub()
	metrics := newMetrics()
	ctx := context.Background()

	var kafkaWriter *kafka.Writer
	if config.KafkaEnabled {
		kafkaWriter = &kafka.Writer{
			Addr:         kafka.TCP(config.KafkaBrokers...),
			Topic:        config.KafkaTopicRaw,
			Balancer:     &kafka.Hash{},
			RequiredAcks: kafka.RequireOne,
			Async:        false,
		}
		defer kafkaWriter.Close()
	}

	mqttClient := connectMQTT(config, func(client mqtt.Client, message mqtt.Message) {
		envelope, err := buildEnvelope(message.Topic(), message.Payload())
		if err != nil {
			log.Printf("invalid telemetry payload topic=%s error=%v", message.Topic(), err)
			metrics.parseErrors.Inc()
			return
		}

		serialized, err := json.Marshal(envelope)
		if err != nil {
			log.Printf("envelope marshal failed: %v", err)
			return
		}

		metrics.observeEnvelope(envelope)
		hub.Broadcast(serialized)

		if kafkaWriter != nil {
			err = kafkaWriter.WriteMessages(ctx, kafka.Message{
				Key:   []byte(envelope.DeviceID),
				Value: serialized,
				Time:  time.Now(),
			})
			if err != nil {
				log.Printf("redpanda write failed: %v", err)
			}
		}
	})
	defer mqttClient.Disconnect(250)

	upgrader := websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool {
			return true
		},
	}

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		metrics.websocketClients.Set(float64(hub.Count()))
		writeJSON(w, map[string]any{
			"ok":               true,
			"mqttConnected":    mqttClient.IsConnected(),
			"websocketClients": hub.Count(),
			"kafkaEnabled":     config.KafkaEnabled,
		})
	})

	http.Handle("/metrics", promhttp.Handler())

	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("websocket upgrade failed: %v", err)
			return
		}

		hub.Add(conn)
		defer hub.Remove(conn)

		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	})

	log.Printf("backend listening on %s", config.HTTPAddr)
	if err := http.ListenAndServe(config.HTTPAddr, nil); err != nil {
		log.Fatal(err)
	}
}

func loadConfig() Config {
	return Config{
		HTTPAddr:      env("HTTP_ADDR", ":3000"),
		MQTTURL:       env("MQTT_URL", "tcp://localhost:1883"),
		MQTTTopic:     env("MQTT_TOPIC", "obd/v1/+/+"),
		KafkaEnabled:  env("KAFKA_ENABLED", "true") != "false",
		KafkaBrokers:  strings.Split(env("KAFKA_BROKERS", "localhost:19092"), ","),
		KafkaTopicRaw: env("KAFKA_TOPIC_RAW", "obd.telemetry.raw"),
	}
}

func connectMQTT(config Config, handler mqtt.MessageHandler) mqtt.Client {
	options := mqtt.NewClientOptions().
		AddBroker(config.MQTTURL).
		SetClientID("obd-backend-" + time.Now().Format("20060102150405")).
		SetCleanSession(true).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(time.Second)

	options.OnConnect = func(client mqtt.Client) {
		log.Printf("mqtt connected, subscribing to %s", config.MQTTTopic)
		token := client.Subscribe(config.MQTTTopic, 1, handler)
		token.Wait()
		if token.Error() != nil {
			log.Printf("mqtt subscribe failed: %v", token.Error())
		}
	}

	options.OnConnectionLost = func(client mqtt.Client, err error) {
		log.Printf("mqtt connection lost: %v", err)
	}

	client := mqtt.NewClient(options)
	token := client.Connect()
	token.Wait()
	if token.Error() != nil {
		log.Fatalf("mqtt connect failed: %v", token.Error())
	}

	return client
}

type appMetrics struct {
	mqttMessages     prometheus.Counter
	telemetryPackets prometheus.Counter
	parseErrors      prometheus.Counter
	signalValue      *prometheus.GaugeVec
	healthValue      *prometheus.GaugeVec
	lastSeenUnix     *prometheus.GaugeVec
	websocketClients prometheus.Gauge
}

func newMetrics() *appMetrics {
	m := &appMetrics{
		mqttMessages: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "obd_mqtt_messages_total",
			Help: "Total MQTT messages processed by the backend.",
		}),
		telemetryPackets: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "obd_telemetry_packets_total",
			Help: "Total telemetry packets processed by the backend.",
		}),
		parseErrors: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "obd_parse_errors_total",
			Help: "Total MQTT payload parse errors.",
		}),
		signalValue: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "obd_signal_value",
			Help: "Latest OBD signal value by device and signal.",
		}, []string{"device_id", "signal"}),
		healthValue: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "obd_health_value",
			Help: "Latest OBD health value by device and metric.",
		}, []string{"device_id", "metric"}),
		lastSeenUnix: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "obd_device_last_seen_unix",
			Help: "Last telemetry receive time as Unix timestamp.",
		}, []string{"device_id"}),
		websocketClients: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "obd_websocket_clients",
			Help: "Currently connected WebSocket clients.",
		}),
	}

	prometheus.MustRegister(
		m.mqttMessages,
		m.telemetryPackets,
		m.parseErrors,
		m.signalValue,
		m.healthValue,
		m.lastSeenUnix,
		m.websocketClients,
	)
	return m
}

func (m *appMetrics) observeEnvelope(envelope LiveEnvelope) {
	m.mqttMessages.Inc()
	if envelope.Type != "telemetry" {
		return
	}

	var payload TelemetryPayload
	if err := json.Unmarshal(envelope.Payload, &payload); err != nil {
		m.parseErrors.Inc()
		return
	}

	deviceID := payload.DeviceID
	if deviceID == "" {
		deviceID = envelope.DeviceID
	}
	if deviceID == "" {
		deviceID = "unknown"
	}

	m.telemetryPackets.Inc()
	m.lastSeenUnix.WithLabelValues(deviceID).Set(float64(time.Now().Unix()))

	for signal, value := range payload.Signals {
		if value != nil {
			m.signalValue.WithLabelValues(deviceID, signal).Set(*value)
		}
	}
	for metric, value := range payload.Health {
		if value != nil {
			m.healthValue.WithLabelValues(deviceID, metric).Set(*value)
		}
	}
}

func buildEnvelope(topic string, payload []byte) (LiveEnvelope, error) {
	var header TelemetryHeader
	if err := json.Unmarshal(payload, &header); err != nil {
		return LiveEnvelope{}, err
	}

	parts := strings.Split(topic, "/")
	deviceID := header.DeviceID
	if deviceID == "" {
		if len(parts) >= 3 {
			deviceID = parts[2]
		}
	}
	if deviceID == "" {
		deviceID = "unknown"
	}

	envelopeType := "event"
	if len(parts) > 0 {
		envelopeType = parts[len(parts)-1]
		if envelopeType == "events" {
			envelopeType = "event"
		}
	}
	if envelopeType == "" {
		envelopeType = "event"
	}

	return LiveEnvelope{
		Type:       envelopeType,
		DeviceID:   deviceID,
		ReceivedAt: time.Now().UTC().Format(time.RFC3339Nano),
		Payload:    json.RawMessage(payload),
	}, nil
}

func writeJSON(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

func env(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}
