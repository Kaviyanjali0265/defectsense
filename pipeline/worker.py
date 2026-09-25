"""Reads sensor events from Redis Stream and triggers the Prefect triage pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.redis_client import read_events
from pipeline.flows import defect_triage_pipeline


def run():
    print("Worker started — listening on Redis Stream...\n")
    last_id = "$"

    while True:
        entries = read_events(last_id=last_id, count=10, block_ms=1000)

        for entry in entries:
            last_id = entry["stream_id"]
            event = entry["event"]

            print(f"[event] {event['wafer_id']} | {event['process_step']} | machine={event.get('machine_id','?')}")
            defect_triage_pipeline(event)


if __name__ == "__main__":
    run()
