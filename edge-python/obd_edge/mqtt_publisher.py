from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

import paho.mqtt.client as mqtt


@dataclass(frozen=True)
class MqttConfig:
    url: str
    device_id: str


class MqttPublisher:
    def __init__(self, config: MqttConfig) -> None:
        parsed = urlparse(config.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 1883

        self.device_id = config.device_id
        self.telemetry_topic = f"obd/v1/{config.device_id}/telemetry"
        self.status_topic = f"obd/v1/{config.device_id}/status"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"obd-edge-{config.device_id}")
        self.client.will_set(
            self.status_topic,
            payload=json.dumps({"schema": "obd.status.v1", "deviceId": config.device_id, "status": "offline"}),
            qos=1,
            retain=True,
        )
        self.client.connect(host, port, keepalive=30)
        self.client.loop_start()
        self.publish_status("online")

    def publish_status(self, status: str) -> None:
        self.client.publish(
            self.status_topic,
            json.dumps({"schema": "obd.status.v1", "deviceId": self.device_id, "status": status}),
            qos=1,
            retain=True,
        )

    def publish_telemetry(self, payload: dict) -> None:
        self.client.publish(self.telemetry_topic, json.dumps(payload, separators=(",", ":")), qos=1)

    def publish_event(self, event: dict) -> None:
        topic = f"obd/v1/{self.device_id}/events"
        self.client.publish(topic, json.dumps(event, separators=(",", ":")), qos=0)

    def close(self) -> None:
        self.publish_status("offline")
        self.client.loop_stop()
        self.client.disconnect()
