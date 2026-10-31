import { useEffect, useState } from "react";
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  ArcElement, Tooltip, Legend, Filler,
} from "chart.js";
import { Line, Doughnut } from "react-chartjs-2";
import { getOverview, post } from "./api.js";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, ArcElement, Tooltip, Legend, Filler);

const COLORS = { normal: "#2e7d5b", warning: "#c98a0b", high: "#d4561f", critical: "#b3202a" };
const SCENARIO_NAMES = {
  cpu_spike: "CPU spike", memory_leak: "Memory leak", disk_fill: "Disk filling",
  network_flood: "Network flood", full_failure: "Full failure",
};
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour12: false });

/* ---------- small building blocks ---------- */

function RiskGauge({ risk, severity, status }) {
  const color = COLORS[severity] || COLORS.normal;
  const data = {
    datasets: [{ data: [risk, 100 - risk], backgroundColor: [color, "#e3e8ec"], borderWidth: 0 }],
  };
  const options = {
    rotation: -90, circumference: 180, cutout: "76%", animation: { duration: 300 }, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
  };
  return (
    <div className="gauge">
      <Doughnut data={data} options={options} />
      <div className="gauge-label">
        <span className="gauge-value" style={{ color }}>{Math.round(risk)}%</span>
        <span className="gauge-caption">estimated failure risk</span>
        <span className="pill" style={{ background: color }}>{status}</span>
      </div>
    </div>
  );
}

function Tile({ label, value, unit, warn }) {
  return (
    <div className={`tile ${warn ? "tile-warn" : ""}`}>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}<small>{unit}</small></span>
    </div>
  );
}

const baseOptions = (yMax) => ({
  responsive: true, maintainAspectRatio: false, animation: false,
  interaction: { mode: "index", intersect: false },
  plugins: { legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } } },
  scales: {
    x: { ticks: { maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } },
    y: { min: 0, ...(yMax ? { max: yMax } : {}), grid: { color: "#e3e8ec" } },
  },
});
const line = (label, data, color, extra = {}) => ({
  label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0.3, ...extra,
});

function Panel({ title, note, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <header><h2>{title}</h2>{note && <span className="note">{note}</span>}</header>
      {children}
    </section>
  );
}

function SeverityBadge({ s }) {
  return <span className="badge" style={{ background: COLORS[s] || "#667" }}>{s}</span>;
}

/* ---------- demo controls ---------- */

function DemoControls({ data, onChanged }) {
  const [key, setKey] = useState(sessionStorage.getItem("apiKey") || "");
  const [msg, setMsg] = useState(null);
  const sim = data.simulation;

  async function run(fn) {
    setMsg(null);
    sessionStorage.setItem("apiKey", key);
    try { await fn(); onChanged(); }
    catch (e) { setMsg(e.message); }
  }

  return (
    <Panel title="Demo controls" note="Inject a fault to watch the full workflow">
      <label className="field">
        API key
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)}
               placeholder="the API_KEY configured on the server" autoComplete="off" />
      </label>
      <div className="buttons">
        {Object.entries(data.scenarios).map(([id, desc]) => (
          <button key={id} title={desc} disabled={!key || !!sim.active}
                  onClick={() => run(() => post("/api/simulate", { scenario: id }, key))}>
            {SCENARIO_NAMES[id]}
          </button>
        ))}
        <button className="ghost" disabled={!key || !sim.active}
                onClick={() => run(() => post("/api/simulate/stop", null, key))}>Stop</button>
        <button className="ghost" disabled={!key}
                onClick={() => run(() => post("/api/retrain", null, key))}>Retrain model</button>
      </div>
      {sim.active && (
        <p className="sim-on">Injecting <b>{SCENARIO_NAMES[sim.active]}</b> — {sim.remaining} samples left</p>
      )}
      {msg && <p className="error" role="alert">{msg}</p>}
    </Panel>
  );
}

/* ---------- main app ---------- */

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  async function refresh() {
    try { setData(await getOverview()); setError(null); }
    catch (e) { setError("Cannot reach the backend. Make sure the FastAPI server is running on port 8000."); }
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, []);

  if (!data) {
    return <main className="center">{error || "Connecting to the monitoring backend…"}</main>;
  }

  const { server, latest, history, anomalies, alerts, model, integrations } = data;
  const labels = history.map((h) => clock(h.timestamp));
  const anomalyPoints = history.map((h) => (h.is_anomaly && h.severity !== "normal" ? h.failure_risk : null));

  const resources = {
    labels,
    datasets: [
      line("CPU %", history.map((h) => h.cpu), "#1f5f8b"),
      line("Memory %", history.map((h) => h.memory), "#7a4fa0"),
      line("Disk %", history.map((h) => h.disk), "#8a8f94"),
    ],
  };
  const network = {
    labels,
    datasets: [
      line("Inbound KB/s", history.map((h) => h.net_in), "#0e8a8a", { fill: true, backgroundColor: "#0e8a8a22" }),
      line("Outbound KB/s", history.map((h) => h.net_out), "#c98a0b"),
    ],
  };
  const risk = {
    labels,
    datasets: [
      line("Failure risk %", history.map((h) => h.failure_risk), "#b3202a", { fill: true, backgroundColor: "#b3202a14" }),
      line("Anomaly score", history.map((h) => h.anomaly_score), "#7a8791", { borderDash: [5, 4], borderWidth: 1.5 }),
      { label: "Anomaly detected", data: anomalyPoints, showLine: false, type: "line",
        pointRadius: 4, pointBackgroundColor: "#b3202a", borderColor: "#b3202a" },
    ],
  };

  const sourceLabel = server.metrics_source === "simulated" ? "Simulated metrics" : "Live server metrics";
  const learning = !model.trained;

  return (
    <main>
      {error && <div className="banner" role="alert">{error} Showing the last data received.</div>}

      <header className="top">
        <div>
          <h1>Infrastructure health</h1>
          <p className="sub">{server.id} · {sourceLabel} · updated {latest ? clock(latest.timestamp) : "—"}</p>
        </div>
        <ul className="chips" aria-label="Integrations">
          <li className={integrations.sns ? "on" : ""}>SNS email {integrations.sns ? "on" : "off"}</li>
          <li className={integrations.dynamodb ? "on" : ""}>DynamoDB {integrations.dynamodb ? "on" : "off"}</li>
          <li className={integrations.cloudwatch ? "on" : ""}>CloudWatch {integrations.cloudwatch ? "on" : "off"}</li>
        </ul>
      </header>

      {learning && (
        <div className="banner info">
          The model is learning this server's normal behaviour — {model.warmup_remaining} more samples needed.
        </div>
      )}

      <div className="grid-top">
        <Panel title="Server health" className="health">
          <RiskGauge risk={server.failure_risk} severity={server.severity} status={server.status} />
          <p className="model-line">
            {model.type} · v{model.version} · trained on {model.trained_on} samples
          </p>
        </Panel>
        <div className="tiles">
          <Tile label="CPU" value={latest?.cpu ?? "–"} unit="%" warn={latest?.cpu > 85} />
          <Tile label="Memory" value={latest?.memory ?? "–"} unit="%" warn={latest?.memory > 85} />
          <Tile label="Disk" value={latest?.disk ?? "–"} unit="%" warn={latest?.disk > 85} />
          <Tile label="Network in" value={latest ? Math.round(latest.net_in) : "–"} unit=" KB/s" />
          <Tile label="Network out" value={latest ? Math.round(latest.net_out) : "–"} unit=" KB/s" />
          <Tile label="Anomaly score" value={latest?.anomaly_score ?? "–"} unit="/100" warn={latest?.is_anomaly} />
        </div>
        <DemoControls data={data} onChanged={refresh} />
      </div>

      <div className="grid-charts">
        <Panel title="CPU, memory and disk" note="last 120 samples">
          <div className="chart"><Line data={resources} options={baseOptions(100)} /></div>
        </Panel>
        <Panel title="Network traffic">
          <div className="chart"><Line data={network} options={baseOptions()} /></div>
        </Panel>
        <Panel title="Failure risk and anomalies" className="wide">
          <div className="chart"><Line data={risk} options={baseOptions(100)} /></div>
        </Panel>
      </div>

      <div className="grid-tables">
        <Panel title="Anomaly history" note={`${anomalies.length} recent`}>
          {anomalies.length === 0 ? <p className="empty">No anomalies yet. Inject a fault with the demo controls.</p> : (
            <div className="scroll"><table>
              <thead><tr><th>Time</th><th>Severity</th><th>Risk</th><th>Main cause</th><th>Details</th></tr></thead>
              <tbody>{anomalies.map((a, i) => (
                <tr key={i}>
                  <td>{clock(a.timestamp)}</td><td><SeverityBadge s={a.severity} /></td>
                  <td>{a.failure_risk}%</td><td>{a.culprit}{a.injected ? " (injected)" : ""}</td><td>{a.summary}</td>
                </tr>))}
              </tbody></table></div>)}
        </Panel>
        <Panel title="Alerts sent" note="critical only">
          {alerts.length === 0 ? <p className="empty">No alerts yet. A critical anomaly that lasts 2 samples triggers one.</p> : (
            <div className="scroll"><table>
              <thead><tr><th>Time</th><th>Subject</th><th>Delivery</th></tr></thead>
              <tbody>{alerts.map((a) => (
                <tr key={a.id}><td>{clock(a.timestamp)}</td><td>{a.subject}</td>
                  <td>{a.delivery === "sent-via-sns" ? "Email via SNS" : a.delivery === "sns-failed" ? "SNS failed" : "Logged locally (SNS not configured)"}</td></tr>))}
              </tbody></table></div>)}
        </Panel>
      </div>
    </main>
  );
}
