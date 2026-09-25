import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, field_validator

from core import report_store
from core.mechanisms import MECHANISMS
from core.models import IngestResponse, MechanismEnum, SensorEvent
from core.redis_client import push_event
from core.vectorstore import fetch_seen_before

router = APIRouter()


# ── Ingest ────────────────────────────────────────────────────────────────────

def _push_to_stream(event: SensorEvent):
    push_event(event.model_dump())


@router.post("/ingest/event", response_model=IngestResponse)
async def ingest_event(event: SensorEvent, background_tasks: BackgroundTasks):
    background_tasks.add_task(_push_to_stream, event)
    return IngestResponse(
        accepted=True,
        event_id=event.event_id,
        message="Event queued for processing",
    )


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports")
async def get_reports(status: str | None = None):
    return {"reports": report_store.get_all(status=status)}


@router.get("/reports/stats")
async def get_stats():
    return report_store.get_stats()


@router.get("/reports/{event_id}")
async def get_report(event_id: str):
    report = report_store.get_by_id(event_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {event_id} not found")
    return report


# ── Mechanisms ────────────────────────────────────────────────────────────────

@router.get("/mechanisms")
async def get_mechanisms():
    """Full taxonomy — used by the dashboard's verify UI (and anything else that
    needs the valid set of mechanism ids without hardcoding it client-side)."""
    return {
        "mechanisms": [
            {
                "id":        mid,
                "category":  data["category"],
                "step":      data["step"],  # None → applies to any step
                "signature": data["signature"],
            }
            for mid, data in MECHANISMS.items()
        ]
    }


# ── Verify ────────────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    verified_mechanism: str
    fix_applied:        str | None = None

    @field_validator("verified_mechanism")
    @classmethod
    def valid_mechanism(cls, v):
        valid = [e.value for e in MechanismEnum]
        if v not in valid:
            raise ValueError(f"unknown mechanism '{v}'. Must be one of: {', '.join(valid)}")
        return v


@router.post("/reports/{event_id}/verify")
async def verify_report(event_id: str, body: VerifyRequest):
    report = report_store.get_by_id(event_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {event_id} not found")

    if report.get("verified_at"):
        raise HTTPException(status_code=409, detail="Report already verified")

    step      = report["process_step"]
    mechanism = body.verified_mechanism

    # recurrence_count: how many past verified cases same step + mechanism
    recurrence = report_store.count_verified_same_mechanism(step, mechanism)

    # seen_before: fetch matching past cases from defect_history (shared with the pipeline)
    seen_before = fetch_seen_before(step, mechanism)

    updated = report_store.update(
        event_id,
        verified_mechanism= mechanism,
        fix_applied=        body.fix_applied,
        verified_at=        datetime.now(timezone.utc).isoformat(),
        recurrence_count=   recurrence,
        seen_before=        seen_before,
        status=             "verified",
    )

    # Write to defect_history so future diagnoses can use it
    _write_to_history(updated)

    return {"verified": True, "event_id": event_id, "recurrence_count": recurrence}


def _write_to_history(report: dict) -> None:
    try:
        from core.vectorstore import upsert
        mechanism = report.get("verified_mechanism") or report.get("mechanism", "unknown")
        step      = report.get("process_step", "unknown")
        machine   = report.get("machine_id", "unknown")
        fix       = report.get("fix_applied") or "not recorded"
        labeled   = report.get("labeled_readings", {})
        alarms    = ", ".join(
            f"{s} {info['label']}"
            for s, info in labeled.items()
            if info.get("label") in ("HIGH", "LOW")
        ) or "none"

        text = (
            f"Verified defect at {step} on {machine}: "
            f"mechanism={mechanism}, alarms=[{alarms}], fix={fix}."
        )
        upsert(
            collection_name="defect_history",
            doc_id=f"hist-{report['event_id']}",
            text=text,
            metadata={
                "event_id":  report["event_id"],
                "mechanism": mechanism,
                "step":      step,
                "machine":   machine,
                "fix_applied": fix,
                "timestamp": report.get("verified_at", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 — best-effort write, any failure just logs
        print(f"[history_write_error] {exc}")


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok"}
