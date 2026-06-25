import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type { LiveEnvelope, ObdSignals, ObdTelemetryPayload } from "@obd/shared";
import "./styles.css";

const wsUrl = import.meta.env.VITE_WS_URL ?? "ws://localhost:3000/ws";
type LiveMessage = LiveEnvelope<Record<string, unknown>>;
type DiagnosticSummary = {
  vin?: string;
  storedDtcs: string[];
  pendingDtcs: string[];
  permanentDtcs: string[];
  supportedPids: string[];
  udsItems: Array<{ did: string; name: string; value: string; error?: string }>;
  rawResponses: Array<{ request?: string; response?: string; responseId?: string }>;
};

const signalMeta: Array<{ key: keyof ObdSignals; label: string; unit: string; precision?: number }> = [
  { key: "rpm", label: "RPM", unit: "rpm" },
  { key: "speedKmh", label: "Speed", unit: "km/h" },
  { key: "throttlePct", label: "Throttle", unit: "%", precision: 1 },
  { key: "loadPct", label: "Load", unit: "%", precision: 1 },
  { key: "boostBar", label: "Boost", unit: "bar", precision: 2 },
  { key: "boostKpa", label: "Boost", unit: "kPa", precision: 1 },
  { key: "estimatedDieselFuelRateLh", label: "Fuel rate est.", unit: "L/h", precision: 2 },
  { key: "estimatedDieselInjectionMgStroke", label: "Injection est.", unit: "mg/str", precision: 2 },
  { key: "coolantC", label: "Coolant", unit: "C" },
  { key: "voltage", label: "Voltage", unit: "V", precision: 2 },
  { key: "intakeTempC", label: "Intake temp", unit: "C" },
  { key: "intakePressureKpa", label: "Intake pressure", unit: "kPa" },
  { key: "mafGps", label: "MAF", unit: "g/s", precision: 2 },
  { key: "timingAdvanceDeg", label: "Timing advance", unit: "deg", precision: 1 },
  { key: "fuelLevelPct", label: "Fuel", unit: "%", precision: 1 },
  { key: "runtimeSec", label: "Runtime", unit: "s" },
  { key: "barometricKpa", label: "Barometric", unit: "kPa" },
  { key: "ambientTempC", label: "Ambient", unit: "C" },
  { key: "oilTempC", label: "Oil temp", unit: "C" },
  { key: "distanceSinceClearKm", label: "Distance since clear", unit: "km" },
];

function App() {
  const [status, setStatus] = useState("connecting");
  const [message, setMessage] = useState<LiveEnvelope<ObdTelemetryPayload> | null>(null);
  const [events, setEvents] = useState<LiveMessage[]>([]);
  const [clock, setClock] = useState(Date.now());

  useEffect(() => {
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => setStatus("live"));
    socket.addEventListener("close", () => setStatus("offline"));
    socket.addEventListener("error", () => setStatus("error"));
    socket.addEventListener("message", (event) => {
      const parsed = JSON.parse(event.data) as LiveMessage;
      if (parsed.type === "telemetry") {
        setMessage(parsed as unknown as LiveEnvelope<ObdTelemetryPayload>);
        return;
      }
      setEvents((current) => [parsed, ...current].slice(0, 8));
    });

    return () => socket.close();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const signals = useMemo(() => message?.payload.signals ?? {}, [message]);
  const health = message?.payload.health ?? {};
  const packetAgeMs = message ? Math.max(0, clock - Date.parse(message.receivedAt)) : null;
  const diagnostic = useMemo(() => summarizeDiagnostics(events), [events]);
  const responseRate = health.txRequests
    ? Math.round(((health.obdResponses ?? 0) / health.txRequests) * 100)
    : undefined;

  return (
    <main>
      <header>
        <div>
          <h1>OBD Live</h1>
          <p>{message?.deviceId ?? "No device"}</p>
        </div>
        <span className={`status ${status}`}>{status}</span>
      </header>

      <section className="grid">
        <Metric label="RPM" value={signals.rpm} unit="rpm" />
        <Metric label="Speed" value={signals.speedKmh} unit="km/h" />
        <Metric label="Throttle" value={signals.throttlePct} unit="%" />
        <Metric label="Load" value={signals.loadPct} unit="%" />
        <Metric label="Boost" value={signals.boostBar} unit="bar" precision={2} />
        <Metric label="Fuel est." value={signals.estimatedDieselFuelRateLh} unit="L/h" precision={2} />
        <Metric label="Coolant" value={signals.coolantC} unit="C" />
        <Metric label="Voltage" value={signals.voltage} unit="V" precision={2} />
      </section>

      <section className="overview">
        <Panel title="Device Health">
          <div className="health-grid">
            <HealthItem label="Packet age" value={formatDuration(packetAgeMs)} tone={packetAgeMs !== null && packetAgeMs > 3000 ? "warn" : "ok"} />
            <HealthItem label="Last response" value={formatDuration(health.lastResponseAgeMs)} tone={health.lastResponseAgeMs && health.lastResponseAgeMs > 2000 ? "warn" : "ok"} />
            <HealthItem label="TX requests" value={formatNumber(health.txRequests)} />
            <HealthItem label="OBD responses" value={formatNumber(health.obdResponses)} />
            <HealthItem label="RX frames" value={formatNumber(health.rxFrames)} />
            <HealthItem label="TX failures" value={formatNumber(health.txFailures)} tone={health.txFailures ? "bad" : "ok"} />
            <HealthItem label="Response rate" value={responseRate === undefined ? "-" : `${responseRate}%`} tone={responseRate !== undefined && responseRate < 70 ? "warn" : "ok"} />
            <HealthItem label="Sequence" value={formatNumber(message?.payload.seq)} />
          </div>
        </Panel>

        <Panel title="Diagnostic Summary">
          <div className="diagnostic-grid">
            <HealthItem label="VIN" value={diagnostic.vin ?? "-"} />
            <HealthItem label="Stored DTCs" value={diagnostic.storedDtcs.length ? diagnostic.storedDtcs.join(", ") : "-"} tone={diagnostic.storedDtcs.length ? "bad" : "ok"} />
            <HealthItem label="Pending DTCs" value={diagnostic.pendingDtcs.length ? diagnostic.pendingDtcs.join(", ") : "-"} tone={diagnostic.pendingDtcs.length ? "warn" : "ok"} />
            <HealthItem label="Permanent DTCs" value={diagnostic.permanentDtcs.length ? diagnostic.permanentDtcs.join(", ") : "-"} tone={diagnostic.permanentDtcs.length ? "bad" : "ok"} />
          </div>
          <div className="pid-row">
            {diagnostic.supportedPids.slice(0, 28).map((pid) => (
              <span key={pid}>{pid}</span>
            ))}
          </div>
        </Panel>
      </section>

      <section className="table-section">
        <h2>Signals</h2>
        <p className="section-note">
          Boost is derived from manifold pressure minus barometric pressure. Diesel fuel and injection values are estimates from MAF, not ECU injection quantity.
        </p>
        <div className="signal-table">
          {signalMeta.map((signal) => (
            <div key={signal.key} className={signals[signal.key] === undefined ? "muted-row" : ""}>
              <span>{signal.label}</span>
              <strong>{formatSignal(signals[signal.key], signal.precision)}</strong>
              <small>{signal.unit}</small>
            </div>
          ))}
        </div>
      </section>

      <section className="table-section">
        <h2>UDS Data</h2>
        {diagnostic.udsItems.length === 0 ? (
          <p>No UDS reads yet</p>
        ) : (
          <div className="uds-table">
            {diagnostic.udsItems.map((item) => (
              <div key={`${item.did}-${item.name}`}>
                <span>{item.did}</span>
                <strong>{item.name}</strong>
                <code className={item.error ? "error-text" : ""}>{item.error ?? item.value}</code>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="events">
        <h2>Recent Events</h2>
        {events.length === 0 ? (
          <p>No diagnostic events yet</p>
        ) : (
          <ol>
            {events.map((event) => (
              <li key={`${event.receivedAt}-${event.type}`}>
                <span>{event.type}</span>
                <strong>{event.deviceId}</strong>
                <code>{JSON.stringify(event.payload)}</code>
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Metric({
  label,
  value,
  unit,
  precision = 0,
}: {
  label: string;
  value?: number;
  unit: string;
  precision?: number;
}) {
  return (
    <article>
      <span>{label}</span>
      <strong>{formatSignal(value, precision)}</strong>
      <small>{unit}</small>
    </article>
  );
}

function HealthItem({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn" | "bad";
}) {
  return (
    <div className={`health-item ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function summarizeDiagnostics(events: LiveMessage[]): DiagnosticSummary {
  const summary: DiagnosticSummary = {
    storedDtcs: [],
    pendingDtcs: [],
    permanentDtcs: [],
    supportedPids: [],
    udsItems: [],
    rawResponses: [],
  };

  for (const event of [...events].reverse()) {
    const payload = event.payload;
    const kind = stringValue(payload.kind);
    if (kind === "scan-obd") {
      summary.vin = stringValue(payload.vin) ?? summary.vin;
      summary.supportedPids = stringArray(payload.supportedPids) ?? summary.supportedPids;
      summary.storedDtcs = stringArray(payload.storedDtcs) ?? summary.storedDtcs;
      summary.pendingDtcs = stringArray(payload.pendingDtcs) ?? summary.pendingDtcs;
      summary.permanentDtcs = stringArray(payload.permanentDtcs) ?? summary.permanentDtcs;
    }
    if (kind === "obd-request") {
      summary.rawResponses.unshift({
        request: stringValue(payload.request),
        response: stringValue(payload.response),
        responseId: stringValue(payload.responseId),
      });
    }
    if (payload.schema === "obd.uds_read_did.v1") {
      summary.udsItems.unshift({
        did: stringValue(payload.did) ?? "-",
        name: "readDataByIdentifier",
        value: stringValue(payload.ascii) || stringValue(payload.data) || "-",
      });
      if (stringValue(payload.did) === "F190") {
        summary.vin = stringValue(payload.ascii) ?? summary.vin;
      }
    }
    if (payload.schema === "obd.uds_common_scan.v1" && Array.isArray(payload.items)) {
      for (const item of payload.items as Array<Record<string, unknown>>) {
        const did = stringValue(item.did) ?? "-";
        const name = stringValue(item.name) ?? "unknown";
        const error = stringValue(item.error);
        const value = stringValue(item.ascii) || stringValue(item.data) || "-";
        summary.udsItems.unshift({ did, name, value, error });
        if (did === "F190" && !error) {
          summary.vin = value;
        }
      }
    }
  }

  summary.udsItems = summary.udsItems.slice(0, 16);
  summary.rawResponses = summary.rawResponses.slice(0, 8);
  return summary;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function stringArray(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;
}

function formatSignal(value: number | undefined, precision = 0) {
  return value === undefined ? "-" : value.toFixed(precision);
}

function formatNumber(value: number | undefined) {
  return value === undefined ? "-" : String(value);
}

function formatDuration(valueMs: number | undefined | null) {
  if (valueMs === undefined || valueMs === null) {
    return "-";
  }
  if (valueMs < 1000) {
    return `${Math.round(valueMs)} ms`;
  }
  return `${(valueMs / 1000).toFixed(1)} s`;
}

createRoot(document.getElementById("root")!).render(<App />);
