from __future__ import annotations

import string
import time
from dataclasses import dataclass

import can


FUNCTIONAL_OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_MIN_ID = 0x7E8
OBD_RESPONSE_MAX_ID = 0x7EF


class DiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiagnosticResponse:
    arbitration_id: int
    payload: bytes


class IsoTpLiteClient:
    """Small ISO-TP client for read-only diagnostic requests over python-can.

    It supports the subset we need for OBD Mode 09, DTC reads and UDS ReadDataByIdentifier:
    single-frame requests, single-frame responses, and multi-frame responses.
    """

    def __init__(self, bus: can.BusABC, timeout: float = 1.0) -> None:
        self.bus = bus
        self.timeout = timeout

    def request(
        self,
        arbitration_id: int,
        payload: bytes,
        response_min_id: int | None = None,
        response_max_id: int | None = None,
        expected_response_id: int | None = None,
        extended_id: bool = False,
    ) -> DiagnosticResponse:
        if len(payload) > 7:
            raise DiagnosticError("Only single-frame requests are supported")

        frame_data = bytes([len(payload)]) + payload
        frame_data = frame_data.ljust(8, b"\x00")
        self.bus.send(
            can.Message(
                arbitration_id=arbitration_id,
                is_extended_id=extended_id,
                data=frame_data,
            ),
            timeout=self.timeout,
        )

        return self._read_response(
            request_id=arbitration_id,
            response_min_id=response_min_id,
            response_max_id=response_max_id,
            expected_response_id=expected_response_id,
            extended_id=extended_id,
        )

    def _read_response(
        self,
        request_id: int,
        response_min_id: int | None,
        response_max_id: int | None,
        expected_response_id: int | None,
        extended_id: bool,
    ) -> DiagnosticResponse:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=max(0.0, deadline - time.monotonic()))
            if msg is None:
                break
            if expected_response_id is not None and msg.arbitration_id != expected_response_id:
                continue
            if response_min_id is not None and msg.arbitration_id < response_min_id:
                continue
            if response_max_id is not None and msg.arbitration_id > response_max_id:
                continue

            data = bytes(msg.data)
            pci = data[0]
            frame_type = pci >> 4

            if frame_type == 0x0:
                length = pci & 0x0F
                return DiagnosticResponse(msg.arbitration_id, data[1 : 1 + length])

            if frame_type == 0x1:
                total_len = ((pci & 0x0F) << 8) | data[1]
                payload = bytearray(data[2:8])
                self._send_flow_control(msg.arbitration_id, request_id, extended_id)
                expected_sn = 1

                while len(payload) < total_len and time.monotonic() < deadline:
                    cf = self.bus.recv(timeout=max(0.0, deadline - time.monotonic()))
                    if cf is None or cf.arbitration_id != msg.arbitration_id:
                        continue
                    cf_data = bytes(cf.data)
                    if cf_data[0] >> 4 != 0x2:
                        continue
                    sequence = cf_data[0] & 0x0F
                    if sequence != expected_sn:
                        raise DiagnosticError("ISO-TP sequence mismatch")
                    expected_sn = (expected_sn + 1) & 0x0F
                    payload.extend(cf_data[1:8])

                return DiagnosticResponse(msg.arbitration_id, bytes(payload[:total_len]))

        raise DiagnosticError("diagnostic response timeout")

    def _send_flow_control(self, response_id: int, request_id: int, extended_id: bool) -> None:
        flow_control_id = request_id
        if OBD_RESPONSE_MIN_ID <= response_id <= OBD_RESPONSE_MAX_ID:
            flow_control_id = response_id - 8

        self.bus.send(
            can.Message(
                arbitration_id=flow_control_id,
                is_extended_id=extended_id,
                data=[0x30, 0x00, 0x00, 0, 0, 0, 0, 0],
            ),
            timeout=self.timeout,
        )


def supported_pids(client: IsoTpLiteClient) -> list[int]:
    supported: list[int] = []
    for base_pid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
        response = client.request(
            FUNCTIONAL_OBD_REQUEST_ID,
            bytes([0x01, base_pid]),
            response_min_id=OBD_RESPONSE_MIN_ID,
            response_max_id=OBD_RESPONSE_MAX_ID,
        )
        payload = response.payload
        if len(payload) < 6 or payload[0] != 0x41 or payload[1] != base_pid:
            break

        bitmask = int.from_bytes(payload[2:6], "big")
        for bit in range(32):
            if bitmask & (1 << (31 - bit)):
                supported.append(base_pid + bit + 1)

        if base_pid + 0x20 not in supported:
            break

    return supported


def read_vin(client: IsoTpLiteClient) -> str | None:
    response = client.request(
        FUNCTIONAL_OBD_REQUEST_ID,
        b"\x09\x02",
        response_min_id=OBD_RESPONSE_MIN_ID,
        response_max_id=OBD_RESPONSE_MAX_ID,
    )
    payload = response.payload
    if len(payload) < 3 or payload[0] != 0x49 or payload[1] != 0x02:
        return None

    raw = payload[3:] if len(payload) > 3 else b""
    vin = "".join(chr(byte) for byte in raw if chr(byte) in string.ascii_letters + string.digits)
    return vin or None


def read_dtcs(client: IsoTpLiteClient, service: int) -> list[str]:
    response = client.request(
        FUNCTIONAL_OBD_REQUEST_ID,
        bytes([service]),
        response_min_id=OBD_RESPONSE_MIN_ID,
        response_max_id=OBD_RESPONSE_MAX_ID,
    )
    payload = response.payload
    positive_service = service + 0x40
    if not payload or payload[0] != positive_service:
        return []

    dtcs: list[str] = []
    for i in range(1, len(payload) - 1, 2):
        a = payload[i]
        b = payload[i + 1]
        if a == 0 and b == 0:
            continue
        dtcs.append(decode_dtc(a, b))
    return dtcs


def decode_dtc(a: int, b: int) -> str:
    system = ["P", "C", "B", "U"][(a & 0xC0) >> 6]
    first = (a & 0x30) >> 4
    second = a & 0x0F
    return f"{system}{first}{second:X}{b:02X}"


def read_uds_did(client: IsoTpLiteClient, tx_id: int, rx_id: int, did: int) -> bytes:
    response = client.request(
        tx_id,
        bytes([0x22, (did >> 8) & 0xFF, did & 0xFF]),
        expected_response_id=rx_id,
    )
    payload = response.payload
    if len(payload) < 3 or payload[0] != 0x62 or payload[1] != ((did >> 8) & 0xFF) or payload[2] != (did & 0xFF):
        raise DiagnosticError("unexpected UDS DID response")
    return payload[3:]
