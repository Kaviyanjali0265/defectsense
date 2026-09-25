import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ollama
from pydantic import BaseModel, field_validator

from core.limits import has_alarm, label_all_readings
from core.models import DefectReport
from core.models import MechanismEnum as ModelMechanismEnum
from core.vectorstore import search
from pipeline.prompts import build_diagnosis_prompt

LLM_MODEL            = os.getenv("LLM_MODEL", "llama3.2:3b")
CONFIDENCE_THRESHOLD = 0.7


# ── Dedicated exception for "no anomaly" — never confused with diagnosis failure ──

class NoAnomalyError(Exception):
    pass


class DiagnosisParseError(Exception):
    def __init__(self, msg: str, raw: str = ""):
        super().__init__(msg)
        self.raw = raw


# ── Pydantic output model ─────────────────────────────────────────────────────

class DiagnosisOutput(BaseModel):
    reasoning:             str = ""
    mechanism:             str
    confidence:            float
    alternative_mechanism: str | None = None
    explanation:           str

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v):
        # clamp rather than reject — model can give 0.96, etc.
        return round(max(0.5, min(0.95, float(v))), 2)

    @field_validator("mechanism")
    @classmethod
    def valid_mechanism(cls, v):
        valid = [e.value for e in ModelMechanismEnum]
        if v not in valid:
            raise ValueError(f"unknown mechanism: {v}")
        return v

    @field_validator("alternative_mechanism")
    @classmethod
    def valid_alternative(cls, v, info):
        if v is None:
            return v
        valid = [e.value for e in ModelMechanismEnum]
        if v not in valid:
            return None  # repair: unknown alternative → null
        if "mechanism" in info.data and v == info.data["mechanism"]:
            return None  # repair: same as mechanism → null
        return v


# ── Per-call JSON schema for Ollama (enforces step-scoped mechanism names) ────

def _build_schema(shuffled_order: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "reasoning":             {"type": "string"},
            "mechanism":             {"type": "string", "enum": shuffled_order},
            "confidence":            {"type": "number"},
            "alternative_mechanism": {"type": "string"},
            "explanation":           {"type": "string"},
        },
        "required": ["reasoning", "mechanism", "confidence", "explanation"],
    }


# ── Signature consistency guardrail ──────────────────────────────────────────

def _signature_consistent(mechanism: str, labeled: dict) -> bool:
    from core.mechanisms import MECHANISMS
    if mechanism == "unrecognized_pattern":
        return True
    sig = MECHANISMS.get(mechanism, {}).get("signature", {})
    for sensor, expected in sig.items():
        if expected in ("HIGH", "LOW") and labeled.get(sensor, {}).get("label") != expected:
            return False
    for sensor, info in labeled.items():
        if info["label"] in ("HIGH", "LOW") and sig.get(sensor, "normal") not in ("HIGH", "LOW"):
            return False
    return True


# ── Self-contradiction guardrail — model's own reasoning admits its pick is wrong ──

_CONTRADICTION_PHRASES = (
    "rules it out", "ruled out", "rule it out", "not the cause",
    "recently serviced", "recently replaced", "recently recalibrated",
    "serviced yesterday", "replaced yesterday", "recalibrated yesterday",
    "cleaned last shift", "replaced last week",
)


def _note_contradicts_pick(mechanism: str, reasoning: str, explanation: str) -> bool:
    """True only if a contradiction phrase appears in the same sentence as the model's
    OWN chosen mechanism — i.e. the model names evidence that undermines its own pick,
    not evidence it (correctly) used to reject a different candidate.

    Fix: the original version scanned the full reasoning+explanation text for these
    phrases anywhere at all, which false-flagged the exact pattern the prompt teaches
    as *good* reasoning (see EXAMPLE 1 in prompts.py): "particles normal rules out
    polishing_pad_wear" is correct, confident reasoning when the pick is
    head_bearing_wear — but it used to trip this guardrail purely because "rules out"
    appeared somewhere in the text, regardless of which mechanism it was about.
    """
    if mechanism == "unrecognized_pattern":
        return False
    text = f"{reasoning} {explanation}".lower()
    mech_pattern = re.escape(mechanism.lower()).replace("_", "[ _]")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        if re.search(mech_pattern, sentence) and any(phrase in sentence for phrase in _CONTRADICTION_PHRASES):
            return True
    return False


# ── Core diagnosis function (shared by pipeline and smoke test) ───────────────

def run_diagnosis(
    event: dict,
    labeled: dict,
    verified_history: list[dict],
) -> tuple["DiagnosisOutput", list[str], int, int]:
    """Returns (diagnosis, shuffled_order, prompt_tokens, output_tokens). Raises on failure."""
    prompt, shuffled_order = build_diagnosis_prompt(event, labeled, verified_history)
    schema = _build_schema(shuffled_order)

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=schema,
        options={"temperature": 0, "num_predict": 400},
    )
    raw        = response["message"]["content"].strip()
    prompt_tok = response.get("prompt_eval_count", len(prompt) // 4)
    eval_tok   = response.get("eval_count", 0)

    try:
        parsed = json.loads(raw)
        # Repair alternative_mechanism before Pydantic sees it
        alt = parsed.get("alternative_mechanism")
        if not alt or alt not in shuffled_order or alt == parsed.get("mechanism"):
            parsed["alternative_mechanism"] = None
        diagnosis = DiagnosisOutput.model_validate(parsed)
    except Exception as exc:
        raise DiagnosisParseError(str(exc), raw=raw) from exc

    return diagnosis, shuffled_order, prompt_tok, eval_tok


# ── Tasks ─────────────────────────────────────────────────────────────────────

def _prefect_task(fn):
    """Lazy-import Prefect @task decorator so flows.py can be imported without Prefect."""
    try:
        from prefect import task
        return task(fn)
    except ImportError:
        return fn


def _prefect_flow(fn):
    """Lazy-import Prefect @flow decorator."""
    try:
        from prefect import flow
        return flow(name="defect-triage", log_prints=True)(fn)
    except ImportError:
        return fn


@_prefect_task
def detect_anomalies(event: dict) -> dict:
    try:
        from prefect import get_run_logger
        logger = get_run_logger()
    except Exception:  # noqa: BLE001 — Prefect not installed/running, fall back to stdlib logging
        import logging
        logger = logging.getLogger(__name__)
    labeled = label_all_readings(event["readings"])

    if not has_alarm(labeled):
        logger.info(f"No alarm for {event['wafer_id']} — normal event")
        raise NoAnomalyError("normal event")

    alarms = [s for s, r in labeled.items() if r["label"] in ("HIGH", "LOW")]
    logger.info(f"Alarms: {alarms} for {event['wafer_id']}")
    return {**event, "labeled_readings": labeled}


def _get_logger():
    try:
        from prefect import get_run_logger
        return get_run_logger()
    except Exception:  # noqa: BLE001 — Prefect not installed/running, fall back to stdlib logging
        import logging
        return logging.getLogger(__name__)


@_prefect_task
def classify_defect(event: dict) -> dict:
    logger  = _get_logger()
    step    = event["process_step"]
    labeled = event["labeled_readings"]

    query = (
        f"{step} anomaly: "
        + ", ".join(f"{s} {r['label']}" for s, r in labeled.items() if r["label"] != "normal")
    )
    history_raw = search("defect_history", query, n_results=2, where={"step": step})
    verified_history = [h["metadata"] for h in history_raw]

    diagnosis, shuffled_order, prompt_tok, eval_tok = run_diagnosis(event, labeled, verified_history)

    sig_ok    = _signature_consistent(diagnosis.mechanism, labeled)
    note_conflict = _note_contradicts_pick(diagnosis.mechanism, diagnosis.reasoning, diagnosis.explanation)
    logger.info(
        f"Diagnosed '{diagnosis.mechanism}' conf={diagnosis.confidence:.0%} "
        f"sig={sig_ok} note_conflict={note_conflict} ptok={prompt_tok} etok={eval_tok}"
    )
    return {
        **event,
        "mechanism":            diagnosis.mechanism,
        "confidence":           diagnosis.confidence,
        "alternative_mechanism": diagnosis.alternative_mechanism,
        "explanation":          diagnosis.explanation,
        "reasoning":            diagnosis.reasoning,
        "signature_consistent": sig_ok,
        "note_conflict":        note_conflict,
        "candidate_order":      shuffled_order,
    }


@_prefect_task
def trace_process_chain(classified: dict) -> dict:
    from core.graph_store import get_downstream_impact
    from core.mechanisms import MECHANISMS, get_distinguishing_check

    logger = _get_logger()
    step      = classified["process_step"]
    mechanism = classified["mechanism"]
    alternative = classified.get("alternative_mechanism")

    downstream           = get_downstream_impact(step, depth=2)
    distinguishing_check = get_distinguishing_check(mechanism, alternative)

    possible_origin_steps = []
    if mechanism == "upstream_contamination":
        from core.graph_store import get_upstream_steps
        upstream_all = get_upstream_steps(step, depth=99)
        contamination_steps = {
            m["step"] for m in MECHANISMS.values()
            if m["category"] == "contamination" and m["step"] and m["step"] != step
        }
        possible_origin_steps = [u["step"] for u in upstream_all if u["step"] in contamination_steps]

    logger.info(f"Downstream: {[d['step'] for d in downstream]}")
    return {
        **classified,
        "downstream_steps":      downstream,
        "distinguishing_check":  distinguishing_check,
        "possible_origin_steps": possible_origin_steps,
        "root_cause_step":       step,
    }


@_prefect_task
def generate_report(traced: dict) -> DefectReport:
    from core.mechanisms import CATEGORY, REPAIR_STEPS
    from core.report_store import count_verified_same_mechanism
    from core.vectorstore import fetch_seen_before

    logger    = _get_logger()
    mechanism = traced["mechanism"]
    step      = traced["process_step"]
    category  = CATEGORY.get(mechanism, "unclassified")
    repair    = list(REPAIR_STEPS.get(mechanism, []))

    # Has this exact mechanism been seen (and verified) at this step before?
    if mechanism == "unrecognized_pattern":
        seen_before, recurrence_count = [], 0
    else:
        try:
            recurrence_count = count_verified_same_mechanism(step, mechanism)
        except Exception as exc:  # noqa: BLE001 — best-effort lookup, any failure defaults to 0
            logger.info(f"recurrence lookup failed: {exc}")
            recurrence_count = 0
        seen_before = fetch_seen_before(step, mechanism)

    downstream_names = [d["step"] for d in traced.get("downstream_steps", [])]
    if downstream_names:
        repair.append(
            f"Re-inspect wafers on {traced['machine_id']} since {traced['timestamp'][:10]}"
            f" — downstream: {', '.join(downstream_names)}"
        )

    sig_ok        = traced.get("signature_consistent", False)
    note_conflict = traced.get("note_conflict", False)

    if mechanism == "unrecognized_pattern":
        status, review_reason = "needs_review", "unrecognized_pattern"
    elif note_conflict:
        status, review_reason = "needs_review", "model's own reasoning contradicts its pick"
    elif not sig_ok:
        status, review_reason = "needs_review", "signature mismatch"
    elif traced["confidence"] < CONFIDENCE_THRESHOLD:
        status, review_reason = "needs_review", "low confidence"
    else:
        status, review_reason = "triaged", None

    report = DefectReport(
        event_id=              traced["event_id"],
        wafer_id=              traced["wafer_id"],
        machine_id=            traced["machine_id"],
        process_step=          traced["process_step"],
        timestamp=             traced["timestamp"],
        labeled_readings=      traced.get("labeled_readings", {}),
        mechanism=             mechanism,
        category=              category,
        root_cause_step=       traced.get("root_cause_step", traced.get("process_step")),
        confidence=            traced["confidence"],
        alternative_mechanism= traced.get("alternative_mechanism"),
        distinguishing_check=  traced.get("distinguishing_check"),
        explanation=           traced.get("explanation", ""),
        repair_steps=          repair,
        downstream_steps=      traced.get("downstream_steps", []),
        possible_origin_steps= traced.get("possible_origin_steps", []),
        seen_before=           seen_before,
        recurrence_count=      recurrence_count,
        status=                status,
        review_reason=         review_reason,
    )
    logger.info(f"Report: {mechanism} [{status}] for {report.wafer_id}")
    return report


# ── Flow ──────────────────────────────────────────────────────────────────────

@_prefect_flow
def defect_triage_pipeline(event: dict) -> DefectReport | None:
    try:
        detected   = detect_anomalies(event)
        classified = classify_defect(detected)
        traced     = trace_process_chain(classified)
        report     = generate_report(traced)
        _save_report(report)
        print(f"  [{report.status}] {report.wafer_id} → {report.mechanism} ({report.confidence:.0%})")
        return report

    except NoAnomalyError:
        return None  # normal event — not a defect

    except Exception as exc:  # noqa: BLE001 — catch-all so one bad event never crashes the worker
        print(f"  [diagnosis_failed] {event.get('wafer_id','?')}: {exc}")
        failed = DefectReport(
            event_id=     event.get("event_id", "unknown"),
            wafer_id=     event.get("wafer_id", "unknown"),
            machine_id=   event.get("machine_id", "unknown"),
            process_step= event.get("process_step", "unknown"),
            timestamp=    event.get("timestamp", ""),
            status=       "diagnosis_failed",
        )
        _save_report(failed)
        return failed


def _save_report(report: DefectReport) -> None:
    try:
        from core.report_store import save
        save(report)
    except Exception as exc:  # noqa: BLE001 — best-effort save, any failure just logs
        print(f"  [store_error] could not save report {report.event_id}: {exc}")
