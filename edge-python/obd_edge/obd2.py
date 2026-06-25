from __future__ import annotations

import time
from dataclasses import dataclass, field

import can


OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_MIN_ID = 0x7E8
OBD_RESPONSE_MAX_ID = 0x7EF
DIESEL_STOICH_AFR = 14.5
DIESEL_DENSITY_G_PER_L = 832
ENGINE_CYLINDERS = 4


@dataclass
class ObdState:
    signals: dict[str, float | int | None] = field(default_factory=dict)
    tx_requests: int = 0
    tx_failures: int = 0
    rx_frames: int = 0
    obd_responses: int = 0
    last_response_at: float | None = None


class Obd2Poller:
    def __init__(self, bus: can.BusABC, timeout: float = 0.15) -> None:
        self.bus = bus
        self.timeout = timeout
        self.state = ObdState()

    def poll(self, pid: int) -> None:
        request = can.Message(
            arbitration_id=OBD_REQUEST_ID,
            is_extended_id=False,
            data=[0x02, 0x01, pid, 0, 0, 0, 0, 0],
        )
        try:
            self.bus.send(request, timeout=self.timeout)
            self.state.tx_requests += 1
        except can.CanError:
            self.state.tx_failures += 1
            return

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = self.bus.recv(timeout=max(0.0, deadline - time.monotonic()))
            if response is None:
                return
            self.state.rx_frames += 1
            if self._handle_response(response):
                return

    def _handle_response(self, frame: can.Message) -> bool:
        if frame.is_extended_id:
            return False
        if not OBD_RESPONSE_MIN_ID <= frame.arbitration_id <= OBD_RESPONSE_MAX_ID:
            return False
        data = bytes(frame.data)
        if len(data) < 4 or data[1] != 0x41:
            return False

        pid = data[2]
        a = data[3]
        b = data[4] if len(data) > 4 else 0
        self.state.obd_responses += 1
        self.state.last_response_at = time.time()

        if pid == 0x0C:
            self.state.signals["rpm"] = int(((a * 256) + b) / 4)
        elif pid == 0x05:
            self.state.signals["coolantC"] = a - 40
        elif pid == 0x0D:
            self.state.signals["speedKmh"] = a
        elif pid == 0x04:
            self.state.signals["loadPct"] = round(a * 100 / 255, 1)
        elif pid == 0x11:
            self.state.signals["throttlePct"] = round(a * 100 / 255, 1)
        elif pid == 0x42:
            self.state.signals["voltage"] = round(((a * 256) + b) / 1000, 3)
        elif pid == 0x0F:
            self.state.signals["intakeTempC"] = a - 40
        elif pid == 0x0B:
            self.state.signals["intakePressureKpa"] = a
        elif pid == 0x10:
            self.state.signals["mafGps"] = round(((a * 256) + b) / 100, 2)
        elif pid == 0x0E:
            self.state.signals["timingAdvanceDeg"] = round((a / 2) - 64, 1)
        elif pid == 0x2F:
            self.state.signals["fuelLevelPct"] = round(a * 100 / 255, 1)
        elif pid == 0x1F:
            self.state.signals["runtimeSec"] = (a * 256) + b
        elif pid == 0x33:
            self.state.signals["barometricKpa"] = a
        elif pid == 0x46:
            self.state.signals["ambientTempC"] = a - 40
        elif pid == 0x5C:
            self.state.signals["oilTempC"] = a - 40
        elif pid == 0x31:
            self.state.signals["distanceSinceClearKm"] = (a * 256) + b
        else:
            return False
        self._update_derived_signals()
        return True

    def _update_derived_signals(self) -> None:
        intake_pressure = self._number_signal("intakePressureKpa")
        barometric_pressure = self._number_signal("barometricKpa")
        if intake_pressure is not None and barometric_pressure is not None:
            boost_kpa = max(0.0, intake_pressure - barometric_pressure)
            self.state.signals["boostKpa"] = round(boost_kpa, 1)
            self.state.signals["boostBar"] = round(boost_kpa / 100, 2)

        maf_gps = self._number_signal("mafGps")
        if maf_gps is not None:
            fuel_gps = maf_gps / DIESEL_STOICH_AFR
            self.state.signals["estimatedDieselFuelRateLh"] = round(
                fuel_gps * 3600 / DIESEL_DENSITY_G_PER_L,
                2,
            )

            rpm = self._number_signal("rpm")
            if rpm is not None and rpm > 0:
                injection_events_per_second = rpm / 60 * (ENGINE_CYLINDERS / 2)
                self.state.signals["estimatedDieselInjectionMgStroke"] = round(
                    fuel_gps * 1000 / injection_events_per_second,
                    2,
                )

    def _number_signal(self, name: str) -> float | None:
        value = self.state.signals.get(name)
        return float(value) if isinstance(value, (int, float)) else None
