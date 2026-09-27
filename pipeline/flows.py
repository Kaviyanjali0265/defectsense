import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import litellm
from pydantic import BaseModel, field_validator

from core.limits import has_alarm, label_all_readings
from core.models import DefectReport
from core.models import MechanismEnum as ModelMechanismEnum
from core.settings import settings
from core.vectorstore import DEFECT_HISTORY_COLLECTION, search
from pipeline.prompts import build_diagnosis_prompt

# ── Provider switch: "ollama" (default, local) or "groq" (cloud, OpenAI-compatible) ──
# Kept as module-level names (not settings.x everywhere) since other files import
# these directly — core/settings.py is the single source of truth behind them now.
LLM_PROVIDER = settings.llm_provider
GROQ_API_KEY = settings.groq_api_key
LLM_MODEL    = settings.llm_model

CONFIDENCE_THRESHOLD = 0.7

# ── Langfuse tracing (optional, off by default) ────────────────────────────────
# Uses Langfuse's own SDK directly (the @observe() decorator on _call_llm below),
# NOT litellm's built-in "langfuse" callback — that callback's ingestion protocol
# is incompatible with Langfuse accounts on their newer platform (verified: it
# either crashes on langfuse>=3 or silently fails to deliver traces on langfuse 2.x,
# confirmed empirically via Langfuse's own API showing zero ingested traces either
# way). Going through Langfuse's own client for its own platform removes that
# middleman entirely. The SDK reads these same env var names itself; pydantic-
# settings reads .env into the Settings object only, it does NOT export those
# values into os.environ itself (verified directly, not assumed), so they're
# bridged across here. Enabled only when both keys are present — every other
# environment (CI, a fresh clone, another dev's machine) runs with tracing off.
if settings.langfuse_public_key and settings.langfuse_secret_key:
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"]       = settings.langfuse_host
    LANGFUSE_ENABLED = True
else:
    LANGFUSE_ENABLED = False


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


# ── Input guardrail — operator_note prompt-injection check ────────────────────
#
# operator_note is free text a human types, interpolated directly into the diagnosis
# prompt (see pipeline/prompts.py). A note containing instruction-like phrasing could
# be read by the model as a command rather than data. Phrases are deliberately narrow
# and instruction-shaped (not just words like "ignore" or "previous" that show up
# naturally in legitimate maintenance notes, e.g. "ignore the previous reading, sensor
# was recalibrated") to keep false positives low on real operator notes.

_INJECTION_PHRASES = (
    "ignore previous instructions", "ignore all previous instructions",
    "ignore the above instructions", "disregard the above", "disregard previous instructions",
    "disregard all prior instructions", "new instructions:", "system prompt",
    "you are now", "act as", "forget everything", "your instructions are",
    "override your instructions", "do not follow", "instead, say",
)


def _note_looks_like_injection(note: str | None) -> bool:
    """Cheap heuristic scan of operator_note for prompt-injection-style phrasing,
    run before the note is interpolated into the diagnosis prompt at all — same
    repair-not-reject philosophy as the rest of this pipeline: a flagged note gets
    replaced with a safe placeholder (see classify_defect) rather than the whole
    event being rejected, and the report is routed to needs_review either way."""
    if not note:
        return False
    text = note.lower()
    return any(phrase in text for phrase in _INJECTION_PHRASES)


# ── Input guardrail — operator_note PII check ──────────────────────────────────
#
# Separate concern from injection: not "can this note manipulate the model" but
# "does this note contain personal data that shouldn't leave this machine" — matters
# most when LLM_PROVIDER=groq, since the note is then sent to a third-party API.
# Regex is a reasonable fit here (unlike injection, which is closer to an intent/
# semantics problem) — emails and phone numbers have recognizable, stable shapes.

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_SSN_PATTERN   = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _note_contains_pii(note: str | None) -> bool:
    """True if operator_note appears to contain an email, phone number, or SSN-
    shaped string. Regex-based on purpose — PII has recognizable shapes, no ML
    model needed. Deliberately requires phone-number separators (dashes/dots/
    spaces) rather than matching any bare 10-digit run, to avoid false-flagging
    sensor readings or machine IDs that happen to be long numbers."""
    if not note:
        return False
    return bool(_EMAIL_PATTERN.search(note) or _PHONE_PATTERN.search(note) or _SSN_PATTERN.search(note))


# ── Provider call via LiteLLM — one gateway, both providers ───────────────────
#
# Ollama: response_format's json_schema envelope is unwrapped by litellm's own
# Ollama transformation (llms/ollama/chat/transformation.py) straight into Ollama's
# native grammar-constrained `format` param — verified by reading that source file
# directly, not assumed: same token-level enforcement guarantee as the old direct
# ollama.chat(format=schema) call, not just "the model was asked nicely."
#
# Groq: still tool-calling — Groq's API doesn't support response_format=json_schema
# the way OpenAI's does, so a schema-typed function call is the reliable mechanism
# there (same approach as before, just issued through litellm instead of a raw
# openai-client call).
#
# max_tokens is the one param name used for both — litellm maps it to each
# provider's native name internally (Ollama's num_predict, Groq's max_tokens as-is).

def _model_string() -> str:
    return f"groq/{LLM_MODEL}" if LLM_PROVIDER == "groq" else f"ollama/{LLM_MODEL}"


def _observe_llm_call(fn):
    """Wraps a function with Langfuse's own @observe() decorator, only when
    Langfuse is actually configured — a plain passthrough otherwise, so this adds
    zero behavior (and never even imports langfuse) when tracing is off. Captures
    both success and failure: @observe() records the trace either way, then lets
    the original exception (e.g. DiagnosisParseError) continue propagating exactly
    as it did before — nothing about existing error handling changes."""
    if not LANGFUSE_ENABLED:
        return fn
    from langfuse import observe
    return observe(as_type="generation", name="llm_diagnosis_call")(fn)


@_observe_llm_call
def _call_llm(prompt: str, schema: dict) -> tuple[str, int, int]:
    try:
        if LLM_PROVIDER == "groq":
            if not GROQ_API_KEY:
                raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is not set")
            tool = {
                "type": "function",
                "function": {
                    "name": "submit_diagnosis",
                    "description": "Submit the mechanism diagnosis for this sensor anomaly.",
                    "parameters": schema,
                },
            }
            response = litellm.completion(
                model=_model_string(),
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "submit_diagnosis"}},
                temperature=0,
                # Reasoning models (e.g. qwen3.8) burn tokens on internal chain-of-thought
                # before ever calling the tool — 400 (tuned for the non-reasoning local
                # model) cuts them off mid-thought. Groq is fast, so a bigger cap is cheap.
                max_tokens=4000,
                api_key=GROQ_API_KEY,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                raise DiagnosisParseError(
                    "Groq returned no tool call (likely ran out of tokens mid-reasoning)",
                    raw=msg.content or "",
                )
            raw = msg.tool_calls[0].function.arguments
        else:
            response = litellm.completion(
                model=_model_string(),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": {"name": "diagnosis", "schema": schema}},
                temperature=0,
                max_tokens=400,
            )
            raw = response.choices[0].message.content.strip()
    except DiagnosisParseError:
        raise
    except Exception as exc:
        raise DiagnosisParseError(f"{LLM_PROVIDER} API error: {exc}", raw="") from exc

    prompt_tok = response.usage.prompt_tokens if response.usage else len(prompt) // 4
    eval_tok   = response.usage.completion_tokens if response.usage else 0
    return raw, prompt_tok, eval_tok


# ── Core diagnosis function (shared by pipeline and smoke test) ───────────────

def run_diagnosis(
    event: dict,
    labeled: dict,
    verified_history: list[dict],
) -> tuple["DiagnosisOutput", list[str], int, int]:
    """Returns (diagnosis, shuffled_order, prompt_tokens, output_tokens). Raises on failure."""
    prompt, shuffled_order = build_diagnosis_prompt(event, labeled, verified_history)
    schema = _build_schema(shuffled_order)

    raw, prompt_tok, eval_tok = _call_llm(prompt, schema)

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

    # Input guardrails: sanitize operator_note BEFORE it ever reaches the prompt
    # builder. Original note is kept on the event for the report/human review;
    # the LLM only ever sees the sanitized version. Two independent checks — a note
    # can be flagged for either, both, or neither.
    raw_note = event.get("operator_note")
    note_injection_flagged = _note_looks_like_injection(raw_note)
    note_pii_flagged       = _note_contains_pii(raw_note)
    if note_injection_flagged or note_pii_flagged:
        reasons = []
        if note_injection_flagged:
            reasons.append("possible prompt injection")
        if note_pii_flagged:
            reasons.append("possible PII")
        logger.info(f"operator_note flagged ({', '.join(reasons)}) for {event['wafer_id']}: {raw_note!r}")
        event = {**event, "operator_note": f"[note redacted: {', '.join(reasons)}]"}

    query = (
        f"{step} anomaly: "
        + ", ".join(f"{s} {r['label']}" for s, r in labeled.items() if r["label"] != "normal")
    )
    history_raw = search(DEFECT_HISTORY_COLLECTION, query, n_results=2, where={"step": step})
    verified_history = [h["metadata"] for h in history_raw]

    diagnosis, shuffled_order, prompt_tok, eval_tok = run_diagnosis(event, labeled, verified_history)

    sig_ok    = _signature_consistent(diagnosis.mechanism, labeled)
    note_conflict = _note_contradicts_pick(diagnosis.mechanism, diagnosis.reasoning, diagnosis.explanation)
    logger.info(
        f"Diagnosed '{diagnosis.mechanism}' conf={diagnosis.confidence:.0%} "
        f"sig={sig_ok} note_conflict={note_conflict} note_injection={note_injection_flagged} "
        f"note_pii={note_pii_flagged} ptok={prompt_tok} etok={eval_tok}"
    )
    return {
        **event,
        "operator_note":        raw_note,  # restore original for the report/human review
        "mechanism":            diagnosis.mechanism,
        "confidence":           diagnosis.confidence,
        "alternative_mechanism": diagnosis.alternative_mechanism,
        "explanation":          diagnosis.explanation,
        "reasoning":            diagnosis.reasoning,
        "signature_consistent": sig_ok,
        "note_conflict":        note_conflict,
        "note_injection_flagged": note_injection_flagged,
        "note_pii_flagged":     note_pii_flagged,
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

    sig_ok          = traced.get("signature_consistent", False)
    note_conflict   = traced.get("note_conflict", False)
    note_injection  = traced.get("note_injection_flagged", False)
    note_pii        = traced.get("note_pii_flagged", False)

    if note_injection and note_pii:
        status, review_reason = "needs_review", "operator_note flagged for possible prompt injection and PII"
    elif note_injection:
        status, review_reason = "needs_review", "operator_note flagged as possible prompt injection"
    elif note_pii:
        status, review_reason = "needs_review", "operator_note flagged as possible PII"
    elif mechanism == "unrecognized_pattern":
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
        operator_note=         traced.get("operator_note"),
        note_injection_flagged= traced.get("note_injection_flagged", False),
        note_pii_flagged=      traced.get("note_pii_flagged", False),
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
