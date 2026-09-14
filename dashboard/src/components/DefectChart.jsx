const DEFECT_COLORS = {
  thermal_excursion: "#ff6b6b",
  pressure_deviation: "#ffa94d",
  contamination: "#cc5de8",
  mechanical_fault: "#f06595",
  flow_anomaly: "#4dabf7",
  unknown: "#868e96",
};

export default function DefectChart({ byType }) {
  const entries = Object.entries(byType);
  if (entries.length === 0) {
    return (
      <div style={{ background: "#1a1d27", borderRadius: "8px", padding: "20px", marginBottom: "24px", color: "#555" }}>
        No data yet — waiting for defects...
      </div>
    );
  }

  const max = Math.max(...entries.map(([, v]) => v));

  return (
    <div style={{ background: "#1a1d27", borderRadius: "8px", padding: "20px", marginBottom: "24px" }}>
      <h3 style={{ margin: "0 0 16px", color: "#aaa", fontSize: "14px", textTransform: "uppercase", letterSpacing: "1px" }}>
        Defect Type Breakdown
      </h3>
      {entries.map(([type, count]) => {
        const color = DEFECT_COLORS[type] || "#ccc";
        const pct = max > 0 ? (count / max) * 100 : 0;
        return (
          <div key={type} style={{ marginBottom: "10px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", marginBottom: "4px" }}>
              <span style={{ textTransform: "capitalize", color: "#ccc" }}>{type.replace(/_/g, " ")}</span>
              <span style={{ color }}>{count}</span>
            </div>
            <div style={{ background: "#2a2d3a", borderRadius: "4px", height: "8px" }}>
              <div style={{ background: color, width: `${pct}%`, height: "8px", borderRadius: "4px", transition: "width 0.4s ease" }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
