from __future__ import annotations

import argparse
import sys
import time

import can

from .lilygo_bus import LilygoSerialBus
from .mqtt_publisher import MqttConfig, MqttPublisher
from .obd2 import Obd2Poller

DEFAULT_PIDS = [0x0C, 0x0D, 0x11, 0x04, 0x42, 0x05, 0x0F, 0x0B, 0x10, 0x0E, 0x2F, 0x1F, 0x33, 0x46, 0x5C, 0x31]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="obd-edge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    poll = subparsers.add_parser("poll-obd", help="Poll OBD-II PIDs through the LILYGO bridge")
    add_common_args(poll)
    poll.add_argument("--publish-ms", type=int, default=200)
    poll.add_argument("--pid-interval-ms", type=int, default=80)

    sniff = subparsers.add_parser("sniff", help="Publish raw CAN frames as MQTT events")
    add_common_args(sniff)

    uds = subparsers.add_parser("uds-shell-info", help="Show how to mount ISO-TP/UDS on the bridge")
    add_common_args(uds)

    args = parser.parse_args(argv)

    if args.command == "poll-obd":
        return run_poll_obd(args)
    if args.command == "sniff":
        return run_sniff(args)
    if args.command == "uds-shell-info":
        return run_uds_info(args)
    return 2


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--serial", required=True, help="LILYGO serial device path")
    parser.add_argument("--mqtt", default="tcp://localhost:1883")
    parser.add_argument("--device-id", default="lilygo-python")
    parser.add_argument("--baudrate", type=int, default=115200)


def make_bus(args: argparse.Namespace) -> LilygoSerialBus:
    return LilygoSerialBus(channel=args.serial, baudrate=args.baudrate)


def run_poll_obd(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    poller = Obd2Poller(bus)
    session_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{args.device_id}"
    started_at = time.monotonic()
    seq = 0
    pid_index = 0
    last_publish = 0.0

    try:
      while True:
          poller.poll(DEFAULT_PIDS[pid_index])
          pid_index = (pid_index + 1) % len(DEFAULT_PIDS)

          now = time.monotonic()
          if (now - last_publish) * 1000 >= args.publish_ms:
              seq += 1
              last_publish = now
              last_age_ms = 0
              if poller.state.last_response_at is not None:
                  last_age_ms = int((time.time() - poller.state.last_response_at) * 1000)

              publisher.publish_telemetry(
                  {
                      "schema": "obd.telemetry.v1",
                      "deviceId": args.device_id,
                      "seq": seq,
                      "deviceTsMs": int((now - started_at) * 1000),
                      "sessionId": session_id,
                      "signals": poller.state.signals,
                      "health": {
                          "txRequests": poller.state.tx_requests,
                          "txFailures": poller.state.tx_failures,
                          "rxFrames": poller.state.rx_frames,
                          "obdResponses": poller.state.obd_responses,
                          "lastResponseAgeMs": last_age_ms,
                      },
                  }
              )
          time.sleep(args.pid_interval_ms / 1000)
    except KeyboardInterrupt:
        return 0
    finally:
        bus.shutdown()
        publisher.close()


def run_sniff(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    try:
        while True:
            message = bus.recv(timeout=1)
            if message is None:
                continue
            publisher.publish_event(
                {
                    "schema": "obd.can_frame.v1",
                    "deviceId": args.device_id,
                    "ts": time.time(),
                    "id": message.arbitration_id,
                    "extended": message.is_extended_id,
                    "rtr": message.is_remote_frame,
                    "data": bytes(message.data).hex().upper(),
                }
            )
    except KeyboardInterrupt:
        return 0
    finally:
        bus.shutdown()
        publisher.close()


def run_uds_info(args: argparse.Namespace) -> int:
    print("The LILYGO bridge exposes a python-can BusABC:")
    print()
    print("  from obd_edge import LilygoSerialBus")
    print("  import isotp")
    print("  import udsoncan")
    print()
    print(f"  bus = LilygoSerialBus(channel={args.serial!r})")
    print("  # Mount can-isotp + udsoncan here with explicit tx/rx IDs for your ECU.")
    print()
    print("UDS write/reset/flashing commands are intentionally not exposed by this CLI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
