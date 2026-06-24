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
			return
		}

		serialized, err := json.Marshal(envelope)
		if err != nil {
			log.Printf("envelope marshal failed: %v", err)
			return
		}

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
		writeJSON(w, map[string]any{
			"ok":               true,
			"mqttConnected":    mqttClient.IsConnected(),
			"websocketClients": hub.Count(),
			"kafkaEnabled":     config.KafkaEnabled,
		})
	})

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
		MQTTTopic:     env("MQTT_TOPIC", "obd/v1/+/telemetry"),
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

func buildEnvelope(topic string, payload []byte) (LiveEnvelope, error) {
	var header TelemetryHeader
	if err := json.Unmarshal(payload, &header); err != nil {
		return LiveEnvelope{}, err
	}

	deviceID := header.DeviceID
	if deviceID == "" {
		parts := strings.Split(topic, "/")
		if len(parts) >= 3 {
			deviceID = parts[2]
		}
	}
	if deviceID == "" {
		deviceID = "unknown"
	}

	return LiveEnvelope{
		Type:       "telemetry",
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
