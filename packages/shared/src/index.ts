export type ObdSignals = {
  rpm?: number;
  speedKmh?: number;
  loadPct?: number;
  throttlePct?: number;
  voltage?: number;
  coolantC?: number;
  intakeTempC?: number;
  intakePressureKpa?: number;
  mafGps?: number;
  timingAdvanceDeg?: number;
  fuelLevelPct?: number;
  runtimeSec?: number;
  barometricKpa?: number;
  ambientTempC?: number;
  oilTempC?: number;
  distanceSinceClearKm?: number;
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
