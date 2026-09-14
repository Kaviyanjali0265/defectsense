import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const DEFECT_META = {
  thermal_excursion:  { color: "#ff6b6b", icon: "🌡️", label: "Thermal Excursion" },
  pressure_deviation: { color: "#ffa94d", icon: "🔵", label: "Pressure Deviation" },
  contamination:      { color: "#cc5de8", icon: "☣️", label: "Contamination" },
  mechanical_fault:   { color: "#f06595", icon: "⚙️", label: "Mechanical Fault" },
  flow_anomaly:       { color: "#4dabf7", icon: "💧", label: "Flow Anomaly" },
  unknown:            { color: "#868e96", icon: "❓", label: "Unknown" },
};

export default function App() {
  const [reports, setReports] = useState([]);
  const [stats, setStats] = useState({ total_reports: 0, by_defect_type: {} });
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [rRes, sRes] = await Promise.all([
          fetch(`${API}/reports`),
          fetch(`${API}/reports/stats`),
        ]);
        setReports((await rRes.json()).reports || []);
        setStats(await sRes.json());
        setLastUpdated(new Date().toLocaleTimeString());
      } catch {}
    };
    fetchData();
    const id = setInterval(fetchData, 3000);
    return () => clearInterval(id);
  }, []);

  const avgConfidence = reports.length
    ? (reports.reduce((s, r) => s + (r.confidence || 0), 0) / reports.length * 100).toFixed(0)
    : 0;

  const topDefect = Object.entries(stats.by_defect_type).sort((a, b) => b[1] - a[1])[0];

  return (
    <div style={{ fontFamily: "'Segoe UI', sans-serif", background: "#0b0d14", minHeight: "100vh", color: "#e0e0e0", padding: "28px 32px" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "28px" }}>
        <div>
          <h1 style={{ color: "#00d4ff", margin: 0, fontSize: "26px", fontWeight: 700, letterSpacing: "1px" }}>
            ⬡ DefectSense
          </h1>
          <p style={{ color: "#555", margin: "4px 0 0", fontSize: "13px" }}>AI-Powered Semiconductor Defect Triage System</p>
        </div>
        <div style={{ textAlign: "right", fontSize: "12px", color: "#444" }}>
          <div style={{ color: "#51cf66", fontSize: "11px", marginBottom: "2px" }}>● LIVE</div>
          {lastUpdated && <div>Updated {lastUpdated}</div>}
        </div>
      </div>

      {/* KPI Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "14px", marginBottom: "24px" }}>
        <KpiCard label="Total Triaged" value={stats.total_reports} unit="defects" color="#00d4ff" />
        <KpiCard label="Defect Types" value={Object.keys(stats.by_defect_type).length} unit="distinct" color="#cc5de8" />
        <KpiCard label="Avg Confidence" value={`${avgConfidence}%`} unit="LLM accuracy" color="#51cf66" />
        <KpiCard label="Top Defect" value={topDefect ? (DEFECT_META[topDefect[0]]?.icon || "?") : "—"}
          unit={topDefect ? DEFECT_META[topDefect[0]]?.label || topDefect[0] : "none yet"} color="#ffa94d" />
      </div>

      {/* Middle row: Breakdown cards + Bar chart */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <TypeCards byType={stats.by_defect_type} total={stats.total_reports} />
        <BarChart byType={stats.by_defect_type} />
      </div>

      {/* Table */}
      <DefectTable reports={reports} />
    </div>
  );
}

function KpiCard({ label, value, unit, color }) {
  return (
    <div style={{ background: "#13151f", border: `1px solid ${color}33`, borderRadius: "10px", padding: "18px 20px" }}>
      <div style={{ fontSize: "30px", fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: "11px", color: "#888", marginTop: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>{label}</div>
      <div style={{ fontSize: "11px", color: "#555", marginTop: "2px" }}>{unit}</div>
    </div>
  );
}

function TypeCards({ byType, total }) {
  return (
    <div style={{ background: "#13151f", borderRadius: "10px", padding: "18px 20px" }}>
      <SectionTitle>Defect Type Breakdown</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "14px" }}>
        {Object.entries(DEFECT_META).map(([type, meta]) => {
          const count = byType[type] || 0;
          const pct = total > 0 ? ((count / total) * 100).toFixed(0) : 0;
          return (
            <div key={type} style={{
              background: count > 0 ? `${meta.color}11` : "#1a1d27",
              border: `1px solid ${count > 0 ? meta.color + "44" : "#2a2d3a"}`,
              borderRadius: "8px", padding: "10px 12px",
              opacity: count > 0 ? 1 : 0.4,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", color: meta.color }}>{meta.icon} {meta.label}</span>
                <span style={{ fontWeight: 700, color: meta.color, fontSize: "18px" }}>{count}</span>
              </div>
              <div style={{ background: "#0b0d14", borderRadius: "3px", height: "4px", marginTop: "8px" }}>
                <div style={{ background: meta.color, width: `${pct}%`, height: "4px", borderRadius: "3px", transition: "width 0.5s" }} />
              </div>
              <div style={{ fontSize: "10px", color: "#555", marginTop: "4px" }}>{pct}% of total</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BarChart({ byType }) {
  const entries = Object.entries(byType);
  const max = entries.length ? Math.max(...entries.map(([, v]) => v)) : 1;
  return (
    <div style={{ background: "#13151f", borderRadius: "10px", padding: "18px 20px" }}>
      <SectionTitle>Triage Volume by Type</SectionTitle>
      {entries.length === 0 ? (
        <div style={{ color: "#444", fontSize: "13px", marginTop: "20px" }}>Waiting for data...</div>
      ) : (
        <div style={{ marginTop: "18px", display: "flex", flexDirection: "column", gap: "14px" }}>
          {entries.sort((a, b) => b[1] - a[1]).map(([type, count]) => {
            const meta = DEFECT_META[type] || DEFECT_META.unknown;
            const pct = (count / max) * 100;
            return (
              <div key={type}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "5px" }}>
                  <span style={{ color: "#ccc" }}>{meta.icon} {meta.label}</span>
                  <span style={{ color: meta.color, fontWeight: 600 }}>{count}</span>
                </div>
                <div style={{ background: "#1e2130", borderRadius: "4px", height: "10px" }}>
                  <div style={{
                    background: `linear-gradient(90deg, ${meta.color}cc, ${meta.color})`,
                    width: `${pct}%`, height: "10px", borderRadius: "4px",
                    transition: "width 0.5s ease", boxShadow: `0 0 8px ${meta.color}55`
                  }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function downloadCSV(reports) {
  const headers = ["wafer_id", "defect_type", "root_cause_step", "confidence", "status", "explanation"];
  const rows = reports.map(r =>
    headers.map(h => {
      const val = h === "confidence" ? ((r[h] || 0) * 100).toFixed(0) + "%" : (r[h] || "");
      return `"${String(val).replace(/"/g, '""')}"`;
    }).join(",")
  );
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `defectsense_report_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function DefectTable({ reports }) {
  return (
    <div style={{ background: "#13151f", borderRadius: "10px", overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", borderBottom: "1px solid #1e2130", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <SectionTitle style={{ margin: 0 }}>Live Defect Feed</SectionTitle>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "12px", color: "#555" }}>{reports.length} reports</span>
          {reports.length > 0 && (
            <button onClick={() => downloadCSV(reports)} style={{
              background: "#00d4ff22", border: "1px solid #00d4ff55", color: "#00d4ff",
              padding: "5px 12px", borderRadius: "6px", fontSize: "11px", cursor: "pointer",
              fontWeight: 600, letterSpacing: "0.5px"
            }}>
              ⬇ Download CSV
            </button>
          )}
        </div>
      </div>
      {reports.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", color: "#444", fontSize: "13px" }}>
          No reports yet — run the generator to stream events.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ background: "#0e1018" }}>
                {["Wafer ID", "Defect Type", "Root Cause Step", "Confidence", "Status", "Explanation"].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#555", fontWeight: 600, fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reports.map((r, i) => {
                const meta = DEFECT_META[r.defect_type] || DEFECT_META.unknown;
                const conf = r.confidence || 0;
                const confColor = conf >= 0.8 ? "#51cf66" : conf >= 0.65 ? "#ffa94d" : "#ff6b6b";
                return (
                  <tr key={r.event_id || i} style={{ borderTop: "1px solid #1a1d27", transition: "background 0.2s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "#1a1d27"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                    <td style={{ padding: "10px 16px", color: "#00d4ff", fontFamily: "monospace", fontWeight: 600 }}>{r.wafer_id}</td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ background: `${meta.color}22`, color: meta.color, padding: "3px 10px", borderRadius: "12px", fontSize: "11px", fontWeight: 600 }}>
                        {meta.icon} {meta.label}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", color: "#aaa", textTransform: "capitalize" }}>{r.root_cause_step || "—"}</td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ color: confColor, fontWeight: 700 }}>{conf ? `${(conf * 100).toFixed(0)}%` : "—"}</span>
                      <div style={{ background: "#1e2130", borderRadius: "2px", height: "3px", width: "50px", marginTop: "4px" }}>
                        <div style={{ background: confColor, width: `${conf * 100}%`, height: "3px", borderRadius: "2px" }} />
                      </div>
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ background: "#51cf6622", color: "#51cf66", padding: "3px 8px", borderRadius: "10px", fontSize: "11px" }}>
                        ✓ {r.status || "triaged"}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", color: "#666", maxWidth: "300px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "12px" }}>
                      {r.explanation || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }) {
  return <div style={{ fontSize: "11px", color: "#666", textTransform: "uppercase", letterSpacing: "1px", fontWeight: 600 }}>{children}</div>;
}
