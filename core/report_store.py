"""Report store backed by Redis — keyed by event_id."""
import json
import os

from core.redis_client import get_client

REPORTS_HASH = "defect:reports"   # Redis hash: event_id → JSON
REPORTS_LIST = "defect:report_ids"  # Redis list: insertion order
MAX_REPORTS  = int(os.getenv("MAX_REPORTS", "200"))  # oldest evicted beyond this


def save(report) -> None:
    """Save or overwrite a DefectReport. Evicts the oldest report past MAX_REPORTS."""
    client = get_client()
    data = report.model_dump()
    client.hset(REPORTS_HASH, report.event_id, json.dumps(data))
    # keep insertion order list (no duplicates) — lpos returns 0 for the first
    # element, so the check must be "is None", not falsy, or index-0 re-saves duplicate
    if client.lpos(REPORTS_LIST, report.event_id) is None:
        client.rpush(REPORTS_LIST, report.event_id)

    while client.llen(REPORTS_LIST) > MAX_REPORTS:
        oldest = client.lpop(REPORTS_LIST)
        if oldest:
            client.hdel(REPORTS_HASH, oldest)


def get_by_id(event_id: str) -> dict | None:
    client = get_client()
    raw = client.hget(REPORTS_HASH, event_id)
    return json.loads(raw) if raw else None


def update(event_id: str, **fields) -> dict | None:
    report = get_by_id(event_id)
    if report is None:
        return None
    report.update(fields)
    get_client().hset(REPORTS_HASH, event_id, json.dumps(report))
    return report


def get_all(status: str | None = None) -> list[dict]:
    client = get_client()
    ids = client.lrange(REPORTS_LIST, 0, -1)
    reports = []
    for eid in reversed(ids):  # newest first
        raw = client.hget(REPORTS_HASH, eid)
        if raw:
            r = json.loads(raw)
            if status is None or r.get("status") == status:
                reports.append(r)
    return reports


def count_verified_same_mechanism(step: str, mechanism: str) -> int:
    """Count verified reports with the same step + mechanism — used for recurrence_count."""
    reports = get_all()
    return sum(
        1 for r in reports
        if r.get("verified_mechanism") == mechanism
        and r.get("process_step") == step
        and r.get("verified_at") is not None
    )


def get_stats() -> dict:
    reports = get_all()
    by_status: dict[str, int]    = {}
    by_mechanism: dict[str, int] = {}
    by_step: dict[str, int]      = {}

    for r in reports:
        s = r.get("status", "unknown")
        m = r.get("mechanism", "unknown")
        t = r.get("process_step", "unknown")
        by_status[s]    = by_status.get(s, 0) + 1
        by_mechanism[m] = by_mechanism.get(m, 0) + 1
        by_step[t]      = by_step.get(t, 0) + 1

    verified = [r for r in reports if r.get("verified_at")]
    correct  = sum(
        1 for r in verified
        if r.get("mechanism") == r.get("verified_mechanism")
    )

    return {
        "total":        len(reports),
        "by_status":    by_status,
        "by_mechanism": by_mechanism,
        "by_step":      by_step,
        "verified":     len(verified),
        "model_accuracy": f"{correct}/{len(verified)}" if verified else "0/0",
    }
