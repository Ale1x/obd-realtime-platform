import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type { LiveEnvelope, ObdTelemetryPayload } from "@obd/shared";
import "./styles.css";

const wsUrl = import.meta.env.VITE_WS_URL ?? "ws://localhost:3000/ws";

function App() {
  const [status, setStatus] = useState("connecting");
  const [message, setMessage] = useState<LiveEnvelope<ObdTelemetryPayload> | null>(null);

  useEffect(() => {
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => setStatus("live"));
    socket.addEventListener("close", () => setStatus("offline"));
    socket.addEventListener("error", () => setStatus("error"));
    socket.addEventListener("message", (event) => {
      setMessage(JSON.parse(event.data));
    });

    return () => socket.close();
  }, []);

  const signals = useMemo(() => message?.payload.signals ?? {}, [message]);

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
        <Metric label="Coolant" value={signals.coolantC} unit="C" />
        <Metric label="Voltage" value={signals.voltage} unit="V" />
      </section>

      <footer>
        Last packet: {message?.receivedAt ?? "-"}
      </footer>
    </main>
  );
}

function Metric({ label, value, unit }: { label: string; value?: number; unit: string }) {
  return (
    <article>
      <span>{label}</span>
      <strong>{value ?? "-"}</strong>
      <small>{unit}</small>
    </article>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
