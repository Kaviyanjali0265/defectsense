import { useState, useEffect, Fragment } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// category is the 5-way rollup (core/mechanisms.py CATEGORY); mechanism is the
// specific finding (one of 18 + unrecognized_pattern). unclassified === unrecognized_pattern.
const CATEGORY_META = {
  thermal_excursion:  { color: "#ff6b6b", icon: "🌡️", label: "Thermal Excursion" },
  pressure_deviation: { color: "#ffa94d", icon: "🔵", label: "Pressure Deviation" },
  contamination:      { color: "#cc5de8", icon: "☣️", label: "Contamination" },
  mechanical_fault:   { color: "#f06595", icon: "⚙️", label: "Mechanical Fault" },
  flow_anomaly:       { color: "#4dabf7", icon: "💧", label: "Flow Anomaly" },
  unclassified:       { color: "#868e96", icon: "❓", label: "Unrecognized" },
};

const STATUS_META = {
  triaged:          { color: "#51cf66", icon: "✓" },
  needs_review:     { color: "#ffa94d", icon: "⚠" },
  verified:         { color: "#00d4ff", icon: "✓" },
  diagnosis_failed: { color: "#ff6b6b", icon: "✕" },
};

function catMeta(category) {
  return CATEGORY_META[category] || CATEGORY_META.unclassified;
}

export default function App() {
  const [reports, setReports] = useState([]);
  const [stats, setStats] = useState({ total: 0, by_status: {}, by_mechanism: {}, verified: 0, model_accuracy: "0/0" });
  const [mechanisms, setMechanisms] = useState([]);
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

  // Mechanism taxonomy — fetched once, used to populate the verify dropdown.
  useEffect(() => {
    fetch(`${API}/mechanisms`)
      .then(r => r.json())
      .then(d => setMechanisms(d.mechanisms || []))
      .catch(() => {});
  }, []);

  const refetchReports = () => {
    fetch(`${API}/reports`).then(r => r.json()).then(d => setReports(d.reports || [])).catch(() => {});
    fetch(`${API}/reports/stats`).then(r => r.json()).then(setStats).catch(() => {});
  };

  // Category breakdown computed client-side from the visible reports (stats only
  // aggregates by mechanism/status/step, not by the 5-way category rollup).
  const byCategory = reports.reduce((acc, r) => {
    const c = r.category || "unclassified";
    acc[c] = (acc[c] || 0) + 1;
    return acc;
  }, {});
  const topCategory = Object.entries(byCategory).sort((a, b) => b[1] - a[1])[0];
  const needsReview = stats.by_status?.needs_review || 0;

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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "14px", marginBottom: "24px" }}>
        <KpiCard label="Total Triaged" value={stats.total ?? 0} unit="reports" color="#00d4ff" />
        <KpiCard label="Needs Review" value={needsReview} unit="awaiting engineer" color="#ffa94d" />
        <KpiCard label="Verified" value={stats.verified ?? 0} unit="human-confirmed" color="#00d4ff" />
        <KpiCard label="Model Accuracy" value={stats.model_accuracy ?? "0/0"} unit="of verified cases" color="#51cf66" />
        <KpiCard label="Top Category" value={topCategory ? catMeta(topCategory[0]).icon : "—"}
          unit={topCategory ? catMeta(topCategory[0]).label : "none yet"} color="#ffa94d" />
      </div>

      {/* Middle row: Breakdown cards + Bar chart */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
        <TypeCards byCategory={byCategory} total={reports.length} />
        <BarChart byCategory={byCategory} />
      </div>

      {/* Table */}
      <DefectTable
        reports={reports}
        mechanisms={mechanisms}
        onVerified={refetchReports}
      />
    </div>
  );
}

function KpiCard({ label, value, unit, color }) {
  return (
    <div style={{ background: "#13151f", border: `1px solid ${color}33`, borderRadius: "10px", padding: "18px 20px" }}>
      <div style={{ fontSize: "26px", fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: "11px", color: "#888", marginTop: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>{label}</div>
      <div style={{ fontSize: "11px", color: "#555", marginTop: "2px" }}>{unit}</div>
    </div>
  );
}

function TypeCards({ byCategory, total }) {
  return (
    <div style={{ background: "#13151f", borderRadius: "10px", padding: "18px 20px" }}>
      <SectionTitle>Category Breakdown</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginTop: "14px" }}>
        {Object.entries(CATEGORY_META).map(([cat, meta]) => {
          const count = byCategory[cat] || 0;
          const pct = total > 0 ? ((count / total) * 100).toFixed(0) : 0;
          return (
            <div key={cat} style={{
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

function BarChart({ byCategory }) {
  const entries = Object.entries(byCategory);
  const max = entries.length ? Math.max(...entries.map(([, v]) => v)) : 1;
  return (
    <div style={{ background: "#13151f", borderRadius: "10px", padding: "18px 20px" }}>
      <SectionTitle>Triage Volume by Category</SectionTitle>
      {entries.length === 0 ? (
        <div style={{ color: "#444", fontSize: "13px", marginTop: "20px" }}>Waiting for data...</div>
      ) : (
        <div style={{ marginTop: "18px", display: "flex", flexDirection: "column", gap: "14px" }}>
          {entries.sort((a, b) => b[1] - a[1]).map(([cat, count]) => {
            const meta = catMeta(cat);
            const pct = (count / max) * 100;
            return (
              <div key={cat}>
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
  const headers = ["wafer_id", "mechanism", "category", "root_cause_step", "confidence", "status", "verified_mechanism", "explanation"];
  const rows = reports.map(r =>
    headers.map(h => {
      const val = h === "confidence" ? ((r[h] || 0) * 100).toFixed(0) + "%" : (r[h] ?? "");
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

function DefectTable({ reports, mechanisms, onVerified }) {
  const [verifyingId, setVerifyingId] = useState(null);
  const [draftMechanism, setDraftMechanism] = useState("");
  const [draftFix, setDraftFix] = useState("");
  const [verifyError, setVerifyError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const startVerify = (r) => {
    setVerifyingId(r.event_id);
    setDraftMechanism(r.mechanism || "");
    setDraftFix("");
    setVerifyError("");
  };

  const cancelVerify = () => {
    setVerifyingId(null);
    setVerifyError("");
  };

  const submitVerify = async (eventId) => {
    setSubmitting(true);
    setVerifyError("");
    try {
      const res = await fetch(`${API}/reports/${eventId}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verified_mechanism: draftMechanism, fix_applied: draftFix || null }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body.detail
          ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))
          : `HTTP ${res.status}`;
        setVerifyError(detail);
        return;
      }
      setVerifyingId(null);
      onVerified();
    } catch (e) {
      setVerifyError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  // Candidates for the dropdown: mechanisms valid for this report's step (+ unrecognized_pattern),
  // same scoping the LLM itself sees — an engineer shouldn't be offered mechanisms from other steps.
  const candidatesFor = (step) =>
    mechanisms.filter(m => m.step === step || m.step === null || m.id === "unrecognized_pattern");

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
                {["Wafer ID", "Mechanism", "Category", "Root Cause Step", "Confidence", "Status", "Explanation", ""].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#555", fontWeight: 600, fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reports.map((r, i) => {
                const meta = catMeta(r.category);
                const conf = r.confidence || 0;
                const confColor = conf >= 0.8 ? "#51cf66" : conf >= 0.65 ? "#ffa94d" : "#ff6b6b";
                const statusMeta = STATUS_META[r.status] || STATUS_META.needs_review;
                const isVerified = !!r.verified_at;
                const isVerifying = verifyingId === r.event_id;
                const wasCorrected = isVerified && r.verified_mechanism && r.verified_mechanism !== r.mechanism;

                return (
                  <Fragment key={r.event_id || i}>
                    <tr style={{ borderTop: "1px solid #1a1d27" }}>
                      <td style={{ padding: "10px 16px", color: "#00d4ff", fontFamily: "monospace", fontWeight: 600 }}>{r.wafer_id}</td>
                      <td style={{ padding: "10px 16px", color: "#ddd" }}>
                        {(r.mechanism || "—").replace(/_/g, " ")}
                        {r.recurrence_count > 0 && (
                          <span style={{ color: "#555", fontSize: "11px" }}> · seen {r.recurrence_count}×</span>
                        )}
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <span style={{ background: `${meta.color}22`, color: meta.color, padding: "3px 10px", borderRadius: "12px", fontSize: "11px", fontWeight: 600 }}>
                          {meta.icon} {meta.label}
                        </span>
                      </td>
                      <td style={{ padding: "10px 16px", color: "#aaa", textTransform: "capitalize" }}>{(r.root_cause_step || r.process_step || "—").replace(/_/g, " ")}</td>
                      <td style={{ padding: "10px 16px" }}>
                        <span style={{ color: confColor, fontWeight: 700 }}>{conf ? `${(conf * 100).toFixed(0)}%` : "—"}</span>
                        <div style={{ background: "#1e2130", borderRadius: "2px", height: "3px", width: "50px", marginTop: "4px" }}>
                          <div style={{ background: confColor, width: `${conf * 100}%`, height: "3px", borderRadius: "2px" }} />
                        </div>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <span style={{ background: `${statusMeta.color}22`, color: statusMeta.color, padding: "3px 8px", borderRadius: "10px", fontSize: "11px" }}>
                          {statusMeta.icon} {(r.status || "needs_review").replace(/_/g, " ")}
                        </span>
                        {wasCorrected && (
                          <div style={{ color: "#ffa94d", fontSize: "10px", marginTop: "3px" }}>
                            corrected → {r.verified_mechanism.replace(/_/g, " ")}
                          </div>
                        )}
                        {!isVerified && r.review_reason && (
                          <div style={{ color: "#888", fontSize: "10px", marginTop: "3px" }}>
                            {r.review_reason}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "10px 16px", color: "#666", maxWidth: "280px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "12px" }}>
                        {r.explanation || "—"}
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        {isVerified ? (
                          <span style={{ color: "#00d4ff", fontSize: "11px" }}>✓ verified</span>
                        ) : r.status === "triaged" ? (
                          <span style={{ color: "#555", fontSize: "11px" }}>auto-approved</span>
                        ) : (
                          <button
                            onClick={() => (isVerifying ? cancelVerify() : startVerify(r))}
                            style={{
                              background: isVerifying ? "#ff6b6b22" : "#00d4ff22",
                              border: `1px solid ${isVerifying ? "#ff6b6b55" : "#00d4ff55"}`,
                              color: isVerifying ? "#ff6b6b" : "#00d4ff",
                              padding: "4px 10px", borderRadius: "6px", fontSize: "11px", cursor: "pointer", fontWeight: 600,
                            }}
                          >
                            {isVerifying ? "Cancel" : "Verify"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {isVerifying && (
                      <tr style={{ background: "#0e1018" }}>
                        <td colSpan={8} style={{ padding: "14px 16px" }}>
                          <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
                            <label style={{ fontSize: "11px", color: "#888" }}>Confirmed mechanism:</label>
                            <select
                              value={draftMechanism}
                              onChange={e => setDraftMechanism(e.target.value)}
                              style={{ background: "#1a1d27", color: "#eee", border: "1px solid #2a2d3a", borderRadius: "6px", padding: "5px 8px", fontSize: "12px" }}
                            >
                              {candidatesFor(r.process_step).map(m => (
                                <option key={m.id} value={m.id}>{m.id.replace(/_/g, " ")}</option>
                              ))}
                            </select>
                            <input
                              placeholder="fix applied (optional)"
                              value={draftFix}
                              onChange={e => setDraftFix(e.target.value)}
                              style={{ background: "#1a1d27", color: "#eee", border: "1px solid #2a2d3a", borderRadius: "6px", padding: "5px 8px", fontSize: "12px", flex: 1, minWidth: "180px" }}
                            />
                            <button
                              disabled={submitting || !draftMechanism}
                              onClick={() => submitVerify(r.event_id)}
                              style={{
                                background: "#51cf6622", border: "1px solid #51cf6655", color: "#51cf66",
                                padding: "5px 12px", borderRadius: "6px", fontSize: "11px", cursor: "pointer", fontWeight: 600,
                                opacity: submitting ? 0.6 : 1,
                              }}
                            >
                              {submitting ? "Saving…" : "Confirm"}
                            </button>
                            {verifyError && <span style={{ color: "#ff6b6b", fontSize: "11px" }}>{verifyError}</span>}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
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
