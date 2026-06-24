package main

import (
	"encoding/json"
	"log"
	"math"
	"os"
	"strconv"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
)

type Telemetry struct {
	Schema     string  `json:"schema"`
	DeviceID   string  `json:"deviceId"`
	Seq        uint64  `json:"seq"`
	DeviceTsMs int64   `json:"deviceTsMs"`
	SessionID  string  `json:"sessionId"`
	Signals    Signals `json:"signals"`
	Health     Health  `json:"health"`
}

type Signals struct {
	RPM                  int     `json:"rpm"`
	SpeedKmh             int     `json:"speedKmh"`
	LoadPct              float64 `json:"loadPct"`
	ThrottlePct          float64 `json:"throttlePct"`
	Voltage              float64 `json:"voltage"`
	CoolantC             int     `json:"coolantC"`
	IntakeTempC          int     `json:"intakeTempC"`
	IntakePressureKpa    int     `json:"intakePressureKpa"`
	MafGps               float64 `json:"mafGps"`
	TimingAdvanceDeg     float64 `json:"timingAdvanceDeg"`
	FuelLevelPct         float64 `json:"fuelLevelPct"`
	RuntimeSec           int     `json:"runtimeSec"`
	BarometricKpa        int     `json:"barometricKpa"`
	AmbientTempC         int     `json:"ambientTempC"`
	OilTempC             int     `json:"oilTempC"`
	DistanceSinceClearKm int     `json:"distanceSinceClearKm"`
}

type Health struct {
	RSSI              int `json:"rssi"`
	TxRequests        int `json:"txRequests"`
	TxFailures        int `json:"txFailures"`
	RxFrames          int `json:"rxFrames"`
	ObdResponses      int `json:"obdResponses"`
	LastResponseAgeMs int `json:"lastResponseAgeMs"`
}

type Config struct {
	DeviceID    string
	MQTTURL     string
	PublishRate time.Duration
}

func main() {
	config := Config{
		DeviceID:    env("DEVICE_ID", "dev-simulator"),
		MQTTURL:     env("MQTT_URL", "tcp://localhost:1883"),
		PublishRate: time.Duration(envInt("SIM_RATE_MS", 200)) * time.Millisecond,
	}

	sessionID := time.Now().UTC().Format("20060102T150405Z") + "-" + config.DeviceID
	topic := "obd/v1/" + config.DeviceID + "/telemetry"
	statusTopic := "obd/v1/" + config.DeviceID + "/status"

	client := connectMQTT(config)
	defer client.Disconnect(250)

	publish(client, statusTopic, []byte(`{"schema":"obd.status.v1","status":"online"}`), true)

	startedAt := time.Now()
	ticker := time.NewTicker(config.PublishRate)
	defer ticker.Stop()

	var seq uint64
	log.Printf("simulator publishing to %s every %s", topic, config.PublishRate)

	for now := range ticker.C {
		seq++
		elapsed := now.Sub(startedAt)
		payload := buildTelemetry(config.DeviceID, sessionID, seq, elapsed)
		serialized, err := json.Marshal(payload)
		if err != nil {
			log.Printf("telemetry marshal failed: %v", err)
			continue
		}

		publish(client, topic, serialized, false)
	}
}

func connectMQTT(config Config) mqtt.Client {
	options := mqtt.NewClientOptions().
		AddBroker(config.MQTTURL).
		SetClientID("obd-simulator-" + config.DeviceID).
		SetCleanSession(true).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(time.Second)

	options.OnConnect = func(client mqtt.Client) {
		log.Printf("mqtt connected to %s", config.MQTTURL)
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

func buildTelemetry(deviceID string, sessionID string, seq uint64, elapsed time.Duration) Telemetry {
	seconds := elapsed.Seconds()
	speed := driveCycleSpeed(seconds)
	throttle := clamp(16+18*math.Sin(seconds/5)+30*accelPulse(seconds), 0, 92)
	load := clamp(24+throttle*0.65+12*math.Sin(seconds/9), 8, 96)
	rpm := int(clamp(850+speed*42+throttle*22+140*math.Sin(seconds*2.8), 780, 6100))
	coolant := int(clamp(30+seconds*0.18, 30, 91))
	oil := int(clamp(28+seconds*0.14, 28, 96))
	intakeTemp := int(24 + 4*math.Sin(seconds/25))
	voltage := 13.9 + 0.18*math.Sin(seconds/7)
	maf := clamp((float64(rpm)/1000)*(load/100)*12.5, 1.2, 115)

	return Telemetry{
		Schema:     "obd.telemetry.v1",
		DeviceID:   deviceID,
		Seq:        seq,
		DeviceTsMs: elapsed.Milliseconds(),
		SessionID:  sessionID,
		Signals: Signals{
			RPM:                  rpm,
			SpeedKmh:             int(speed),
			LoadPct:              round(load, 1),
			ThrottlePct:          round(throttle, 1),
			Voltage:              round(voltage, 3),
			CoolantC:             coolant,
			IntakeTempC:          intakeTemp,
			IntakePressureKpa:    int(clamp(35+load*0.72, 30, 105)),
			MafGps:               round(maf, 2),
			TimingAdvanceDeg:     round(clamp(12+speed*0.08-throttle*0.05, -8, 36), 1),
			FuelLevelPct:         round(clamp(77-seconds*0.002, 0, 100), 1),
			RuntimeSec:           int(seconds),
			BarometricKpa:        101,
			AmbientTempC:         22,
			OilTempC:             oil,
			DistanceSinceClearKm: 420,
		},
		Health: Health{
			RSSI:              -55 + int(4*math.Sin(seconds/11)),
			TxRequests:        int(seq),
			TxFailures:        0,
			RxFrames:          int(seq * 2),
			ObdResponses:      int(seq),
			LastResponseAgeMs: 20 + int(25*math.Abs(math.Sin(seconds*1.7))),
		},
	}
}

func driveCycleSpeed(seconds float64) float64 {
	base := 52 + 34*math.Sin(seconds/18) + 14*math.Sin(seconds/4.7)
	if math.Mod(seconds, 55) > 43 {
		base *= 0.35
	}
	return clamp(base, 0, 132)
}

func accelPulse(seconds float64) float64 {
	phase := math.Mod(seconds, 18)
	if phase > 2.5 {
		return 0
	}
	return 1 - phase/2.5
}

func publish(client mqtt.Client, topic string, payload []byte, retained bool) {
	token := client.Publish(topic, 1, retained, payload)
	token.Wait()
	if token.Error() != nil {
		log.Printf("publish failed topic=%s error=%v", topic, token.Error())
	}
}

func round(value float64, decimals int) float64 {
	scale := math.Pow10(decimals)
	return math.Round(value*scale) / scale
}

func clamp(value float64, minValue float64, maxValue float64) float64 {
	return math.Max(minValue, math.Min(maxValue, value))
}

func env(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func envInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}
