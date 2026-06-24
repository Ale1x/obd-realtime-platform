from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

import can
import serial


class LilygoSerialBus(can.BusABC):
    """python-can BusABC adapter for the LILYGO serial CAN bridge firmware."""

    def __init__(
        self,
        channel: str,
        bitrate: int = 500_000,
        baudrate: int = 115_200,
        timeout: float = 0.2,
        **kwargs: Any,
    ) -> None:
        super().__init__(channel=channel, **kwargs)
        self.channel_info = f"lilygo-serial:{channel}@{bitrate}"
        self._serial = serial.Serial(channel, baudrate=baudrate, timeout=timeout)
        self._rx: queue.Queue[can.Message] = queue.Queue(maxsize=4096)
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name="lilygo-serial-reader", daemon=True)
        self._reader.start()

    def send(self, msg: can.Message, timeout: float | None = None) -> None:
        command = "TXE" if msg.is_extended_id else "TX"
        data = " ".join(f"{byte:02X}" for byte in msg.data)
        line = f"{command} {msg.arbitration_id:X} {msg.dlc} {data}\n"
        self._serial.write(line.encode("ascii"))
        self._serial.flush()

    def _recv_internal(self, timeout: float | None) -> tuple[can.Message | None, bool]:
        try:
            return self._rx.get(timeout=timeout), False
        except queue.Empty:
            return None, False

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._serial.close()
        finally:
            super().shutdown()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._serial.readline()
            except serial.SerialException:
                return
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("{"):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "rx":
                continue

            data = bytes.fromhex(event.get("data", ""))
            message = can.Message(
                timestamp=time.time(),
                arbitration_id=int(event["id"]),
                is_extended_id=bool(event.get("extended", False)),
                is_remote_frame=bool(event.get("rtr", False)),
                data=data,
                dlc=int(event.get("dlc", len(data))),
                channel=self.channel_info,
            )

            try:
                self._rx.put_nowait(message)
            except queue.Full:
                _ = self._rx.get_nowait()
                self._rx.put_nowait(message)
