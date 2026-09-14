const SEVERITY_COLOR = {
  thermal_excursion: "#ff6b6b",
  pressure_deviation: "#ffa94d",
  contamination: "#cc5de8",
  mechanical_fault: "#f06595",
  flow_anomaly: "#4dabf7",
  unknown: "#868e96",
};

export default function DefectTable({ reports }) {
  if (reports.length === 0) {
    return (
      <div style={{ background: "#1a1d27", borderRadius: "8px", padding: "40px", textAlign: "center", color: "#555" }}>
        No defect reports yet. Run the generator to start streaming events.
      </div>
    );
  }

  return (
    <div style={{ background: "#1a1d27", borderRadius: "8px", overflow: "hidden" }}>
      <h3 style={{ margin: "0", padding: "16px 20px", color: "#aaa", fontSize: "14px", textTransform: "uppercase", letterSpacing: "1px", borderBottom: "1px solid #2a2d3a" }}>
        Live Defect Feed
      </h3>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
          <thead>
            <tr style={{ background: "#13151f" }}>
              {["Wafer ID", "Defect Type", "Root Cause Step", "Confidence", "Explanation", "Status"].map(h => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#666", fontWeight: "600", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {reports.map((r, i) => {
              const color = SEVERITY_COLOR[r.defect_type] || "#ccc";
              return (
                <tr key={r.event_id || i} style={{ borderTop: "1px solid #2a2d3a" }}>
                  <td style={{ padding: "10px 16px", color: "#00d4ff", fontFamily: "monospace" }}>{r.wafer_id}</td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ background: `${color}22`, color, padding: "2px 8px", borderRadius: "12px", fontSize: "11px", textTransform: "capitalize" }}>
                      {(r.defect_type || "unknown").replace(/_/g, " ")}
                    </span>
                  </td>
                  <td style={{ padding: "10px 16px", color: "#ccc", textTransform: "capitalize" }}>{r.root_cause_step || "—"}</td>
                  <td style={{ padding: "10px 16px", color: r.confidence >= 0.8 ? "#51cf66" : "#ffa94d" }}>
                    {r.confidence ? `${(r.confidence * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td style={{ padding: "10px 16px", color: "#888", maxWidth: "320px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.explanation || "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ background: "#51cf6622", color: "#51cf66", padding: "2px 8px", borderRadius: "12px", fontSize: "11px" }}>
                      {r.status || "triaged"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
