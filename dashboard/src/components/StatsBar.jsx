const DEFECT_COLORS = {
  thermal_excursion: "#ff6b6b",
  pressure_deviation: "#ffa94d",
  contamination: "#cc5de8",
  mechanical_fault: "#f06595",
  flow_anomaly: "#4dabf7",
  unknown: "#868e96",
};

export default function StatsBar({ stats }) {
  const { total_reports, by_defect_type } = stats;

  return (
    <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", marginBottom: "24px" }}>
      <StatCard label="Total Defects Triaged" value={total_reports} color="#00d4ff" />
      {Object.entries(by_defect_type).map(([type, count]) => (
        <StatCard key={type} label={type.replace("_", " ")} value={count} color={DEFECT_COLORS[type] || "#ccc"} />
      ))}
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div style={{
      background: "#1a1d27",
      border: `1px solid ${color}44`,
      borderRadius: "8px",
      padding: "16px 20px",
      minWidth: "140px",
    }}>
      <div style={{ fontSize: "28px", fontWeight: "bold", color }}>{value}</div>
      <div style={{ fontSize: "12px", color: "#888", textTransform: "capitalize", marginTop: "4px" }}>{label}</div>
    </div>
  );
}
