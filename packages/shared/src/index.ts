export type ObdSignals = {
  rpm?: number;
  speedKmh?: number;
  loadPct?: number;
  throttlePct?: number;
  voltage?: number;
  coolantC?: number;
  intakeTempC?: number;
  intakePressureKpa?: number;
  boostKpa?: number;
  boostBar?: number;
  boostRatio?: number;
  mafGps?: number;
  airMassPerStrokeMg?: number;
  estimatedDieselFuelRateLh?: number;
  estimatedDieselInjectionMgStroke?: number;
  engineFuelRateLh?: number;
  estimatedPowerKw?: number;
  estimatedPowerHp?: number;
  estimatedTorqueNm?: number;
  timingAdvanceDeg?: number;
  fuelRailPressureKpa?: number;
  equivalenceRatioB1S1?: number;
  oxygenSensorVoltageB1S1?: number;
  commandedEgrPct?: number;
  egrErrorPct?: number;
  fuelLevelPct?: number;
  runtimeSec?: number;
  distanceWithMilKm?: number;
  warmupsSinceClear?: number;
  barometricKpa?: number;
  ambientTempC?: number;
  relativeThrottlePct?: number;
  acceleratorPedalDPct?: number;
  acceleratorPedalEPct?: number;
  commandedThrottlePct?: number;
  oilTempC?: number;
  distanceSinceClearKm?: number;
  speedPer1000RpmKmh?: number;
  lastZeroToHundredSec?: number;
  bestZeroToHundredSec?: number;
  lastEightyToOneTwentySec?: number;
  bestEightyToOneTwentySec?: number;
};

export type DeviceHealth = {
  rssi?: number;
  txFailures?: number;
  rxFrames?: number;
  txRequests?: number;
  obdResponses?: number;
  lastResponseAgeMs?: number;
};

export type ObdTelemetryPayload = {
  schema: "obd.telemetry.v1";
  deviceId: string;
  seq: number;
  deviceTsMs: number;
  sessionId?: string;
  signals: ObdSignals;
  health?: DeviceHealth;
};

export type LiveEnvelope<TPayload> = {
  type: "telemetry" | "health" | "status" | "event";
  deviceId: string;
  receivedAt: string;
  payload: TPayload;
};
