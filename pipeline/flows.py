import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ollama
from prefect import flow, get_run_logger, task

from core.graph_store import get_downstream_impact, get_upstream_steps
from core.models import DefectReport
from core.report_store import save as save_report
from core.vectorstore import search, upsert
from pipeline.prompts import defect_classification_prompt

LLM_MODEL = "llama3.2:1b"


@task
def validate_event(event: dict) -> dict:
    logger = get_run_logger()
    if event["status"] != "anomaly":
        raise ValueError("Not an anomaly — skip pipeline")
    logger.info(f"Anomaly confirmed: {event['wafer_id']} at {event['process_step']}")
    return event


@task(retries=2, retry_delay_seconds=2)
def classify_defect(event: dict) -> dict:
    logger = get_run_logger()
    deviation = round(((event["value"] - event["threshold"]) / event["threshold"]) * 100, 1)

    # RAG — retrieve similar defects from both collections
    query = f"{event['sensor']} anomaly at {event['process_step']} with {deviation}% deviation"
    similar_knowledge = search("defect_knowledge", query, n_results=2)
    similar_history   = search("defect_history", query, n_results=1)
    similar_all = similar_knowledge + similar_history
    similar_context = "\n".join(f"- {s['text']}" for s in similar_all)

    prompt = defect_classification_prompt(event, deviation, similar_context)

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response["message"]["content"].strip()

    # Parse JSON from LLM response
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    result = {
        **event,
        "defect_type":    parsed.get("defect_type", "unknown"),
        "suggested_cause": parsed.get("root_cause", "unknown"),
        "deviation_pct":  deviation,
        "confidence":     min(0.95, float(parsed.get("confidence", 0.6))),
        "llm_explanation": parsed.get("explanation", raw),
        "similar_defects": [s["text"] for s in similar_all],
    }
    logger.info(f"LLM classified as '{result['defect_type']}' (confidence: {result['confidence']:.0%}) — {len(similar_all)} similar retrieved")
    return result


@task
def trace_process_chain(classified: dict) -> dict:
    logger = get_run_logger()
    step = classified["process_step"]

    upstream   = get_upstream_steps(step, depth=2)
    downstream = get_downstream_impact(step, depth=2)
    likely_root_cause = upstream[0]["step"] if upstream else step

    result = {
        **classified,
        "upstream_steps":    upstream,
        "downstream_impact": downstream,
        "likely_root_cause": likely_root_cause,
    }
    logger.info(f"Upstream: {[u['step'] for u in upstream]} | Downstream impact: {[d['step'] for d in downstream]}")
    return result


@task
def generate_report(traced: dict) -> DefectReport:
    logger = get_run_logger()
    report = DefectReport(
        event_id=traced["event_id"],
        wafer_id=traced["wafer_id"],
        defect_type=traced["defect_type"],
        root_cause_step=traced.get("likely_root_cause", traced["process_step"]),
        confidence=traced["confidence"],
        explanation=traced.get("llm_explanation", traced.get("suggested_cause", "")),
        status="triaged",
    )

    # Save to defect_history so future anomalies can retrieve this as a similar case
    history_text = (
        f"{traced['wafer_id']} {traced['sensor']} anomaly at {traced['process_step']} "
        f"({traced['deviation_pct']}% deviation). Defect: {report.defect_type}. "
        f"Root cause: {report.root_cause_step}. {report.explanation}"
    )
    upsert(
        collection_name="defect_history",
        doc_id=traced["event_id"],
        text=history_text,
        metadata={
            "wafer_id": traced["wafer_id"],
            "process_step": traced["process_step"],
            "defect_type": report.defect_type,
        },
    )

    save_report(report)
    logger.info(f"Report saved for {report.wafer_id} — {report.defect_type}")
    return report


@flow(name="defect-triage", log_prints=True)
def defect_triage_pipeline(event: dict) -> DefectReport | None:
    try:
        validated  = validate_event(event)
        classified = classify_defect(validated)
        traced     = trace_process_chain(classified)
        report     = generate_report(traced)
        print("\n  TRIAGE REPORT")
        print(f"  Wafer      : {report.wafer_id}")
        print(f"  Defect     : {report.defect_type}")
        print(f"  Root cause : {report.root_cause_step}")
        print(f"  Confidence : {report.confidence:.0%}")
        print(f"  Explanation: {report.explanation}\n")
        return report
    except ValueError:
        return None
