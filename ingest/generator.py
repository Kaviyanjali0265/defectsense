"""Simulates manufacturing sensor events — sends them to the ingest API."""
import random
import time
import httpx
from datetime import datetime, timezone

API_URL = "http://localhost:8000/ingest/event"

PROCESS_STEPS = ["lithography", "etching", "deposition", "cmp", "diffusion", "inspection", "metrology"]
SENSORS = ["temperature", "pressure", "vibration", "particle_count", "flow_rate"]

SENSOR_CONFIG = {
    "temperature":    {"unit": "°C",   "normal": (130, 140), "threshold": 140.0},
    "pressure":       {"unit": "mTorr","normal": (2.8, 3.2),  "threshold": 3.5},
    "vibration":      {"unit": "mm/s", "normal": (0.1, 0.5),  "threshold": 0.8},
    "particle_count": {"unit": "ppm",  "normal": (0, 5),      "threshold": 10.0},
    "flow_rate":      {"unit": "sccm", "normal": (95, 105),   "threshold": 110.0},
}


def generate_event(anomaly: bool = False) -> dict:
    step = random.choice(PROCESS_STEPS)
    sensor = random.choice(SENSORS)
    cfg = SENSOR_CONFIG[sensor]

    if anomaly:
        # Push value above threshold
        value = round(cfg["threshold"] * random.uniform(1.05, 1.2), 2)
        status = "anomaly"
    else:
        low, high = cfg["normal"]
        value = round(random.uniform(low, high), 2)
        status = "normal"

    return {
        "wafer_id": f"W-{random.randint(1000, 9999)}",
        "process_step": step,
        "sensor": sensor,
        "value": value,
        "threshold": cfg["threshold"],
        "unit": cfg["unit"],
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run(count: int = 40, anomaly_rate: float = 0.45, delay: float = 0.5):
    print(f"Sending {count} events (anomaly rate: {anomaly_rate * 100:.0f}%)...\n")
    for i in range(count):
        is_anomaly = random.random() < anomaly_rate
        event = generate_event(anomaly=is_anomaly)
        try:
            resp = httpx.post(API_URL, json=event, timeout=5)
            tag = "ANOMALY" if is_anomaly else "normal "
            print(f"[{tag}] {event['wafer_id']} | {event['process_step']:12} | {event['sensor']:14} | {event['value']} {event['unit']} → {resp.json()['event_id'][:8]}...")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(delay)


if __name__ == "__main__":
    run()
