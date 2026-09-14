import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import APIRouter, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from core.models import SensorEvent, IngestResponse
from core.redis_client import push_event
from core import report_store

router = APIRouter()


def _push_to_stream(event: SensorEvent):
    push_event(event.model_dump())


@router.post("/ingest/event", response_model=IngestResponse)
async def ingest_event(event: SensorEvent, background_tasks: BackgroundTasks):
    """Accept a sensor event and push to Redis Stream asynchronously."""
    background_tasks.add_task(_push_to_stream, event)
    return IngestResponse(
        accepted=True,
        event_id=event.event_id,
        message="Event queued for processing",
    )


@router.get("/reports")
async def get_reports():
    return {"reports": report_store.get_all()}


@router.get("/reports/stats")
async def get_stats():
    return report_store.get_stats()


@router.get("/health")
async def health():
    return {"status": "ok"}
