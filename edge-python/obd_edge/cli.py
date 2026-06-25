from __future__ import annotations

import argparse
import sys
import time

from .advanced_obd import DiagnosticError, IsoTpLiteClient, read_dtcs, read_uds_did, read_vin, supported_pids
from .advanced_profiles import scan_common_uds_dids
from .lilygo_bus import LilygoSerialBus
from .mqtt_publisher import MqttConfig, MqttPublisher
from .obd2 import Obd2Poller

DEFAULT_PIDS = [
    0x0C,
    0x0D,
    0x11,
    0x04,
    0x42,
    0x05,
    0x0F,
    0x0B,
    0x10,
    0x0E,
    0x23,
    0x2C,
    0x2D,
    0x2F,
    0x1F,
    0x21,
    0x30,
    0x31,
    0x33,
    0x45,
    0x46,
    0x49,
    0x4A,
    0x4C,
    0x5C,
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="obd-edge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    poll = subparsers.add_parser("poll-obd", help="Poll OBD-II PIDs through the LILYGO bridge")
    add_common_args(poll)
    poll.add_argument("--publish-ms", type=int, default=200)
    poll.add_argument("--pid-interval-ms", type=int, default=80)
    poll.add_argument(
        "--diagnostics-on-start",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publish a read-only diagnostic snapshot before live polling",
    )

    sniff = subparsers.add_parser("sniff", help="Publish raw CAN frames as MQTT events")
    add_common_args(sniff)

    scan = subparsers.add_parser("scan-obd", help="Read supported PIDs, VIN and DTCs")
    add_common_args(scan)

    raw = subparsers.add_parser("obd-request", help="Send a read-only OBD request and publish the response")
    add_common_args(raw)
    raw.add_argument("--service", required=True, help="OBD service hex byte, for example 09")
    raw.add_argument("--pid", help="Optional OBD PID hex byte, for example 02")

    uds_read = subparsers.add_parser("uds-read-did", help="Read a UDS DID through ISO-TP")
    add_common_args(uds_read)
    uds_read.add_argument("--tx-id", default="7E0", help="Physical request CAN ID in hex")
    uds_read.add_argument("--rx-id", default="7E8", help="Physical response CAN ID in hex")
    uds_read.add_argument("--did", required=True, help="DID in hex, for example F190")

    uds_scan = subparsers.add_parser("uds-scan-common", help="Read common read-only UDS DIDs")
    add_common_args(uds_scan)
    uds_scan.add_argument("--tx-id", default="7E0", help="Physical request CAN ID in hex")
    uds_scan.add_argument("--rx-id", default="7E8", help="Physical response CAN ID in hex")

    uds = subparsers.add_parser("uds-shell-info", help="Show how to mount ISO-TP/UDS on the bridge")
    add_common_args(uds)

    args = parser.parse_args(argv)

    if args.command == "poll-obd":
        return run_poll_obd(args)
    if args.command == "sniff":
        return run_sniff(args)
    if args.command == "scan-obd":
        return run_scan_obd(args)
    if args.command == "obd-request":
        return run_obd_request(args)
    if args.command == "uds-read-did":
        return run_uds_read_did(args)
    if args.command == "uds-scan-common":
        return run_uds_scan_common(args)
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
        if args.diagnostics_on_start:
            publisher.publish_event(build_scan_obd_result(args.device_id, IsoTpLiteClient(bus)))

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


def run_scan_obd(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    client = IsoTpLiteClient(bus)
    try:
        result = build_scan_obd_result(args.device_id, client)
        print(result)
        publisher.publish_event(result)
        return 0
    finally:
        bus.shutdown()
        publisher.close()


def build_scan_obd_result(device_id: str, client: IsoTpLiteClient) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": "obd.diagnostics.v1",
        "deviceId": device_id,
        "ts": time.time(),
        "kind": "scan-obd",
    }

    try:
        result["supportedPids"] = [f"{pid:02X}" for pid in supported_pids(client)]
    except DiagnosticError as error:
        result["supportedPidsError"] = str(error)

    try:
        result["vin"] = read_vin(client)
    except DiagnosticError as error:
        result["vinError"] = str(error)

    for service, name in ((0x03, "storedDtcs"), (0x07, "pendingDtcs"), (0x0A, "permanentDtcs")):
        try:
            result[name] = read_dtcs(client, service)
        except DiagnosticError as error:
            result[f"{name}Error"] = str(error)

    return result


def run_obd_request(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    client = IsoTpLiteClient(bus)
    try:
        service = parse_hex_byte(args.service)
        payload = bytes([service])
        if args.pid:
            payload += bytes([parse_hex_byte(args.pid)])

        response = client.request(
            0x7DF,
            payload,
            response_min_id=0x7E8,
            response_max_id=0x7EF,
        )
        event = {
            "schema": "obd.diagnostics.v1",
            "deviceId": args.device_id,
            "ts": time.time(),
            "kind": "obd-request",
            "request": payload.hex().upper(),
            "responseId": f"{response.arbitration_id:X}",
            "response": response.payload.hex().upper(),
        }
        print(event)
        publisher.publish_event(event)
        return 0
    finally:
        bus.shutdown()
        publisher.close()


def run_uds_read_did(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    client = IsoTpLiteClient(bus)
    try:
        tx_id = int(args.tx_id, 16)
        rx_id = int(args.rx_id, 16)
        did = int(args.did, 16)
        data = read_uds_did(client, tx_id=tx_id, rx_id=rx_id, did=did)
        event = {
            "schema": "obd.uds_read_did.v1",
            "deviceId": args.device_id,
            "ts": time.time(),
            "txId": f"{tx_id:X}",
            "rxId": f"{rx_id:X}",
            "did": f"{did:04X}",
            "data": data.hex().upper(),
            "ascii": bytes_to_printable_ascii(data),
        }
        print(event)
        publisher.publish_event(event)
        return 0
    finally:
        bus.shutdown()
        publisher.close()


def run_uds_scan_common(args: argparse.Namespace) -> int:
    publisher = MqttPublisher(MqttConfig(url=args.mqtt, device_id=args.device_id))
    bus = make_bus(args)
    client = IsoTpLiteClient(bus)
    try:
        tx_id = int(args.tx_id, 16)
        rx_id = int(args.rx_id, 16)
        reads = scan_common_uds_dids(client, tx_id=tx_id, rx_id=rx_id)
        event = {
            "schema": "obd.uds_common_scan.v1",
            "deviceId": args.device_id,
            "ts": time.time(),
            "txId": f"{tx_id:X}",
            "rxId": f"{rx_id:X}",
            "items": [read.as_event() for read in reads],
        }
        print(event)
        publisher.publish_event(event)
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


def parse_hex_byte(value: str) -> int:
    parsed = int(value, 16)
    if parsed < 0 or parsed > 0xFF:
        raise argparse.ArgumentTypeError("value must fit in one byte")
    return parsed


def bytes_to_printable_ascii(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
