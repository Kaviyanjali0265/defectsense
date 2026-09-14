"""Seeds ChromaDB with known defect patterns — run once before starting the system."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.vectorstore import upsert

DEFECT_KNOWLEDGE = [
    {
        "id": "kb-001",
        "text": "Pressure anomaly at etching stage above 10% threshold deviation. Root cause: exhaust valve partial blockage or chamber seal wear. Resolution: inspect exhaust valve, check O-ring integrity.",
        "metadata": {"sensor": "pressure", "process_step": "etching", "defect_type": "pressure_deviation"},
    },
    {
        "id": "kb-002",
        "text": "Pressure anomaly at deposition stage. Root cause: chamber O-ring degradation or gas inlet valve failure. Resolution: replace O-ring, verify valve operation.",
        "metadata": {"sensor": "pressure", "process_step": "deposition", "defect_type": "pressure_deviation"},
    },
    {
        "id": "kb-003",
        "text": "Temperature excursion at diffusion step above 8% deviation. Root cause: furnace heating element degradation. Resolution: recalibrate furnace PID controller, inspect heating elements.",
        "metadata": {"sensor": "temperature", "process_step": "diffusion", "defect_type": "thermal_excursion"},
    },
    {
        "id": "kb-004",
        "text": "Temperature excursion at deposition stage. Root cause: coolant flow restriction or thermal chuck malfunction. Resolution: check coolant lines, verify chuck temperature control.",
        "metadata": {"sensor": "temperature", "process_step": "deposition", "defect_type": "thermal_excursion"},
    },
    {
        "id": "kb-005",
        "text": "Particle contamination at lithography stage. Root cause: airlock breach allowing particles into clean environment. Resolution: inspect airlock seals, run particle baseline measurement.",
        "metadata": {"sensor": "particle_count", "process_step": "lithography", "defect_type": "contamination"},
    },
    {
        "id": "kb-006",
        "text": "Particle contamination at CMP stage. Root cause: worn polishing pad releasing abrasive particles. Resolution: replace polishing pad, flush slurry lines.",
        "metadata": {"sensor": "particle_count", "process_step": "cmp", "defect_type": "contamination"},
    },
    {
        "id": "kb-007",
        "text": "Flow rate anomaly at etching stage above 15% deviation. Root cause: mass flow controller drift or gas line partial blockage. Resolution: recalibrate MFC, purge gas lines.",
        "metadata": {"sensor": "flow_rate", "process_step": "etching", "defect_type": "flow_anomaly"},
    },
    {
        "id": "kb-008",
        "text": "Flow rate anomaly at deposition stage. Root cause: precursor gas line restriction or bubbler temperature instability. Resolution: check bubbler temperature, inspect gas lines for blockage.",
        "metadata": {"sensor": "flow_rate", "process_step": "deposition", "defect_type": "flow_anomaly"},
    },
    {
        "id": "kb-009",
        "text": "Vibration anomaly at CMP stage. Root cause: polishing head bearing wear or platen imbalance. Resolution: inspect polishing head bearings, balance platen.",
        "metadata": {"sensor": "vibration", "process_step": "cmp", "defect_type": "mechanical_fault"},
    },
    {
        "id": "kb-010",
        "text": "Vibration anomaly at inspection stage. Root cause: stage motor bearing degradation affecting scan accuracy. Resolution: replace stage motor bearings, recalibrate scan stage.",
        "metadata": {"sensor": "vibration", "process_step": "inspection", "defect_type": "mechanical_fault"},
    },
]


def seed():
    print("Seeding defect knowledge base...")
    for entry in DEFECT_KNOWLEDGE:
        upsert(
            collection_name="defect_knowledge",
            doc_id=entry["id"],
            text=entry["text"],
            metadata=entry["metadata"],
        )
        print(f"  ✓ {entry['id']} — {entry['metadata']['defect_type']} at {entry['metadata']['process_step']}")
    print(f"\nSeeded {len(DEFECT_KNOWLEDGE)} documents into ChromaDB.")


if __name__ == "__main__":
    seed()
