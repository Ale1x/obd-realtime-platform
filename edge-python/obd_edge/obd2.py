from __future__ import annotations

import time
from dataclasses import dataclass, field

import can


OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_MIN_ID = 0x7E8
OBD_RESPONSE_MAX_ID = 0x7EF
DIESEL_STOICH_AFR = 14.5
DIESEL_DENSITY_G_PER_L = 832
DIESEL_LOWER_HEATING_VALUE_J_PER_L = 35_800_000
ASSUMED_DIESEL_ENGINE_EFFICIENCY = 0.38
ENGINE_CYLINDERS = 4


@dataclass
class ObdState:
    signals: dict[str, float | int | None] = field(default_factory=dict)
    tx_requests: int = 0
    tx_failures: int = 0
    rx_frames: int = 0
    obd_responses: int = 0
    last_response_at: float | None = None
    consecutive_timeouts: int = 0
    zero_to_hundred_started_at: float | None = None
    eighty_to_one_twenty_started_at: float | None = None
    last_speed_kmh: float | None = None


class Obd2Poller:
    def __init__(self, bus: can.BusABC, timeout: float = 0.15) -> None:
        self.bus = bus
        self.timeout = timeout
        self.state = ObdState()

    def poll(self, pid: int) -> None:
        if self.state.consecutive_timeouts >= 20:
            time.sleep(0.4)

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
                self.state.consecutive_timeouts += 1
                return
            self.state.rx_frames += 1
            if self._handle_response(response):
                self.state.consecutive_timeouts = 0
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
        c = data[5] if len(data) > 5 else 0
        d = data[6] if len(data) > 6 else 0
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
        elif pid == 0x21:
            self.state.signals["distanceWithMilKm"] = (a * 256) + b
        elif pid == 0x23:
            self.state.signals["fuelRailPressureKpa"] = ((a * 256) + b) * 10
        elif pid == 0x24:
            self.state.signals["equivalenceRatioB1S1"] = round(((a * 256) + b) * 2 / 65536, 4)
            self.state.signals["oxygenSensorVoltageB1S1"] = round(((c * 256) + d) * 8 / 65536, 3)
        elif pid == 0x2F:
            self.state.signals["fuelLevelPct"] = round(a * 100 / 255, 1)
        elif pid == 0x2C:
            self.state.signals["commandedEgrPct"] = round(a * 100 / 255, 1)
        elif pid == 0x2D:
            self.state.signals["egrErrorPct"] = round((a - 128) * 100 / 128, 1)
        elif pid == 0x30:
            self.state.signals["warmupsSinceClear"] = a
        elif pid == 0x1F:
            self.state.signals["runtimeSec"] = (a * 256) + b
        elif pid == 0x33:
            self.state.signals["barometricKpa"] = a
        elif pid == 0x45:
            self.state.signals["relativeThrottlePct"] = round(a * 100 / 255, 1)
        elif pid == 0x46:
            self.state.signals["ambientTempC"] = a - 40
        elif pid == 0x49:
            self.state.signals["acceleratorPedalDPct"] = round(a * 100 / 255, 1)
        elif pid == 0x4A:
            self.state.signals["acceleratorPedalEPct"] = round(a * 100 / 255, 1)
        elif pid == 0x4C:
            self.state.signals["commandedThrottlePct"] = round(a * 100 / 255, 1)
        elif pid == 0x5C:
            self.state.signals["oilTempC"] = a - 40
        elif pid == 0x5E:
            self.state.signals["engineFuelRateLh"] = round(((a * 256) + b) * 0.05, 2)
        elif pid == 0x31:
            self.state.signals["distanceSinceClearKm"] = (a * 256) + b
        else:
            return False
        self._update_derived_signals()
        self._update_performance_timers()
        return True

    def _update_derived_signals(self) -> None:
        intake_pressure = self._number_signal("intakePressureKpa")
        barometric_pressure = self._number_signal("barometricKpa")
        if intake_pressure is not None and barometric_pressure is not None:
            boost_kpa = max(0.0, intake_pressure - barometric_pressure)
            self.state.signals["boostKpa"] = round(boost_kpa, 1)
            self.state.signals["boostBar"] = round(boost_kpa / 100, 2)
            if barometric_pressure > 0:
                self.state.signals["boostRatio"] = round(intake_pressure / barometric_pressure, 2)

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
                self.state.signals["airMassPerStrokeMg"] = round(
                    maf_gps * 1000 / injection_events_per_second,
                    1,
                )
                self.state.signals["estimatedDieselInjectionMgStroke"] = round(
                    fuel_gps * 1000 / injection_events_per_second,
                    2,
                )

        fuel_rate_lh = self._number_signal("engineFuelRateLh") or self._number_signal("estimatedDieselFuelRateLh")
        rpm = self._number_signal("rpm")
        if fuel_rate_lh is not None:
            power_kw = (
                fuel_rate_lh
                * DIESEL_LOWER_HEATING_VALUE_J_PER_L
                / 3600
                * ASSUMED_DIESEL_ENGINE_EFFICIENCY
                / 1000
            )
            self.state.signals["estimatedPowerKw"] = round(power_kw, 1)
            self.state.signals["estimatedPowerHp"] = round(power_kw * 1.34102, 1)
            if rpm is not None and rpm > 0:
                self.state.signals["estimatedTorqueNm"] = round(power_kw * 9550 / rpm, 1)

        speed = self._number_signal("speedKmh")
        if speed is not None and rpm is not None and rpm > 0:
            self.state.signals["speedPer1000RpmKmh"] = round(speed / rpm * 1000, 2)

    def _update_performance_timers(self) -> None:
        speed = self._number_signal("speedKmh")
        now = time.monotonic()
        if speed is None:
            return

        previous_speed = self.state.last_speed_kmh
        self.state.last_speed_kmh = speed

        if speed < 2:
            self.state.zero_to_hundred_started_at = None
        elif self.state.zero_to_hundred_started_at is None and (previous_speed is None or previous_speed < 2):
            self.state.zero_to_hundred_started_at = now
        elif self.state.zero_to_hundred_started_at is not None and speed >= 100:
            elapsed = now - self.state.zero_to_hundred_started_at
            self.state.signals["lastZeroToHundredSec"] = round(elapsed, 2)
            best = self._number_signal("bestZeroToHundredSec")
            self.state.signals["bestZeroToHundredSec"] = round(min(best or elapsed, elapsed), 2)
            self.state.zero_to_hundred_started_at = None

        if speed < 75:
            self.state.eighty_to_one_twenty_started_at = None
        elif speed >= 80 and speed < 120 and self.state.eighty_to_one_twenty_started_at is None:
            self.state.eighty_to_one_twenty_started_at = now
        elif self.state.eighty_to_one_twenty_started_at is not None and speed >= 120:
            elapsed = now - self.state.eighty_to_one_twenty_started_at
            self.state.signals["lastEightyToOneTwentySec"] = round(elapsed, 2)
            best = self._number_signal("bestEightyToOneTwentySec")
            self.state.signals["bestEightyToOneTwentySec"] = round(min(best or elapsed, elapsed), 2)
            self.state.eighty_to_one_twenty_started_at = None

    def _number_signal(self, name: str) -> float | None:
        value = self.state.signals.get(name)
        return float(value) if isinstance(value, (int, float)) else None
