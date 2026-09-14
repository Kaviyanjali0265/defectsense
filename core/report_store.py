"""Report store backed by Redis — shared between worker and API processes."""
import json
from core.redis_client import get_client

REPORTS_KEY = "defect-reports"
MAX_REPORTS = 100


def save(report):
    client = get_client()
    client.lpush(REPORTS_KEY, json.dumps(report.model_dump()))
    client.ltrim(REPORTS_KEY, 0, MAX_REPORTS - 1)


def get_all() -> list[dict]:
    client = get_client()
    raw = client.lrange(REPORTS_KEY, 0, -1)
    return [json.loads(r) for r in raw]


def get_stats() -> dict:
    reports = get_all()
    by_type: dict[str, int] = {}
    for r in reports:
        t = r.get("defect_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return {"total_reports": len(reports), "by_defect_type": by_type}
