# DefectSense — AI-Powered Semiconductor Defect Triage System

An event-driven system that ingests sensor data from semiconductor process equipment,
detects anomalies deterministically, and uses a local LLM to diagnose the underlying
failure *mechanism* (not just a broad category) by reasoning over multiple sensor
signals, an operator note, and past verified cases — with a confidence/consistency
guardrail deciding whether a diagnosis is safe to auto-triage or needs a human to
review it.

---

## Dashboard

![DefectSense Dashboard Overview](assets/dashboard-overview.png)
*KPI cards (triaged/needs-review/verified/model accuracy) + category breakdown.*

![DefectSense Live Defect Feed](assets/dashboard-table.png)
*Live report table — auto-approved `triaged` rows show no action needed; `needs_review`
rows show why (e.g. "signature mismatch") alongside a Verify button.*

---

## Architecture

```
Sensor Events
     │
     ▼
FastAPI (POST /ingest/event)
     │  BackgroundTask
     ▼
Redis Stream (defect-events)
     │  XREAD blocking
     ▼
Prefect Worker
     ├── detect_anomalies    → rule-based (non-LLM): label every sensor
     │                          normal / slightly_high / slightly_low / HIGH / LOW
     │                          against fixed limits; skip if nothing alarms
     ├── classify_defect     → RAG (defect_history) + Ollama LLM, schema-constrained
     │                          output, diagnoses one of 18 mechanisms + unrecognized_pattern
     ├── trace_process_chain → NetworkX graph: downstream impact always,
     │                          upstream origin search only for upstream_contamination
     └── generate_report     → repair checklist (code lookup, never LLM-generated),
                                seen_before / recurrence_count from verified history,
                                triaged vs needs_review from confidence + signature guardrail
     │
     ▼
Redis (defect:reports hash + insertion-order list, capped at MAX_REPORTS)
     │
     ▼
FastAPI (GET /reports, /reports/stats, /mechanisms, POST /reports/{id}/verify)
     │
     ▼
React Dashboard (polls every 3s)
```

An engineer verifying a report (confirm or correct the mechanism) is what writes back
into `defect_history` — the model only ever learns from human-confirmed outcomes, never
from its own unverified guesses.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI + BackgroundTasks | Async ingestion, non-blocking |
| Message Queue | Redis Streams | Persistent event log, right-sized (vs Kafka) |
| AI Pipeline | Prefect | Workflow orchestration with retries + state tracking |
| LLM | Ollama, `llama3.2:3b` | Local inference, no API cost — see *Model choice* below |
| Vector DB | ChromaDB | RAG over verified defect history |
| Process Graph | NetworkX DiGraph | Semiconductor process chain traversal |
| Frontend | React + Vite + nginx | Live dashboard, polled every 3s |
| Containerization | Docker Compose | One-command startup for all services |

---

## Semiconductor Process Chain

```
deposition → cmp → lithography → etching → wet_clean → diffusion → inspection → metrology
```

For each anomaly, the system traces:
- **Downstream impact** (BFS forward, depth 2) — always computed, shown as a repair-checklist item ("re-inspect wafers downstream of X")
- **Possible origin steps** (BFS backward) — computed *only* when the diagnosed mechanism is `upstream_contamination`; every other mechanism's root cause is the step where it was detected (a local fault doesn't need an upstream search)

---

## Defect Taxonomy

Each sensor no longer maps 1:1 to a defect type — that made the LLM a lookup table.
Instead, `category` is a 5-way rollup used for reporting, and `mechanism` is one of 18
specific failure modes (+ `unrecognized_pattern`) the LLM diagnoses by checking each
candidate's required sensor signature against the labeled readings for the event's
specific process step (2-4 candidates shown at a time, not all 18):

| Category | Example mechanisms |
|---|---|
| `pressure_deviation` | chamber_seal_leak, exhaust_valve_blockage |
| `thermal_excursion` | coolant_restriction, heater_degradation |
| `contamination` | polishing_pad_wear, chemical_bath_contamination, upstream_contamination |
| `mechanical_fault` | head_bearing_wear, stage_motor_bearing_wear |
| `flow_anomaly` | gas_line_restriction, mfc_drift, purge_gas_failure |
| `unclassified` | unrecognized_pattern — none of the step's known mechanisms match |

Full taxonomy (id, category, step, sensor signature) is served at `GET /mechanisms`
and defined once in `core/mechanisms.py`.

---

## Project Structure

```
defectsense/
├── api/
│   ├── main.py          # FastAPI app + CORS
│   └── routes.py        # /ingest/event, /reports*, /mechanisms, /reports/{id}/verify
├── core/
│   ├── models.py         # Pydantic models: SensorEvent, MechanismEnum, DefectReport
│   ├── limits.py          # Sensor limits + label_reading/label_all_readings/has_alarm
│   ├── mechanisms.py      # Mechanism taxonomy, category/repair lookups, distinguishing checks
│   ├── redis_client.py    # Redis Stream push/read
│   ├── vectorstore.py     # ChromaDB upsert/search + fetch_seen_before
│   ├── graph_store.py     # NetworkX process chain (downstream + upstream BFS)
│   └── report_store.py    # Redis-backed report store, capped at MAX_REPORTS
├── pipeline/
│   ├── flows.py          # Prefect flow: detect → classify → trace → report
│   ├── prompts.py        # Diagnosis prompt builder (shuffled candidates, worked examples)
│   └── worker.py         # Redis Stream consumer loop
├── ingest/
│   ├── generator.py      # Simulated sensor event producer + designed note-disambiguation cases
├── scripts/
│   └── smoke_diagnosis.py # Direct detect+diagnose test, no Redis/Prefect — for checking model quality
├── dashboard/            # React + Vite frontend
├── assets/               # Screenshots
├── Dockerfile            # API + Worker (Python 3.11)
├── Dockerfile.dashboard  # React build → nginx (multi-stage)
└── docker-compose.yml    # All 4 services
```

---

## Running Locally

### Prerequisites
- Python 3.11+
- Node 18+
- Redis
- [Ollama](https://ollama.com) with `llama3.2:3b` and `nomic-embed-text` pulled

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### Setup

```bash
cd defectsense
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Start Services (4 terminals)

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — API
python -m api.main

# Terminal 3 — Worker
python -m pipeline.worker

# Terminal 4 — Dashboard
cd dashboard && npm install && npm run dev
```

### Generate Events

```bash
python -m ingest.generator
```

Open `http://localhost:5173` — dashboard auto-refreshes every 3 seconds.

### Quick model-quality check (no services needed)

```bash
python scripts/smoke_diagnosis.py            # N_EVENTS=20 by default, fresh random sample each run
N_EVENTS=15 python scripts/smoke_diagnosis.py
LLM_MODEL=llama3.2:3b N_EVENTS=15 python scripts/smoke_diagnosis.py
```

### Formal eval suite (fixed 40-event dataset, ~20 min)

```bash
python evals/run_eval.py                     # accuracy, confusion matrix, calibration, guardrail stats
LLM_MODEL=qwen2.5:3b python evals/run_eval.py  # compare another model on the same fixed set
```

See `evals/README.md` for the dataset design and full metric definitions.

---

## Running with Docker

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:80 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

Then in a separate terminal:
```bash
source .venv/bin/activate
python -m ingest.generator
```

---

## Key Engineering Decisions

**Server-side, rule-based anomaly detection.** Sensor readings are labeled
(`normal` / `slightly_high` / `slightly_low` / `HIGH` / `LOW`) in plain Python against
fixed limits *before* the LLM ever sees the event — the LLM never decides whether
something is anomalous, only *why*, given readings that are already known to be
abnormal. This mirrors how a real fab tool would flag a threshold breach.

**Schema-constrained LLM output**, via Ollama's `format=<json schema>` (a dict, not the
string `"json"`), forces both syntactically valid JSON *and* a mechanism value from the
exact enum of candidates for that event's step — this, combined with a short 400-token
output cap, keeps parse failures rare (a handful of cases in eval runs, always
surfaced as `DiagnosisParseError` rather than a silent bad diagnosis).

**Reasoning-before-answer + shuffled candidate order**, to counter the well-documented
small-model failure mode of defaulting to whichever option is listed last: the schema
requires a `reasoning` field before `mechanism`, and candidate order is re-shuffled on
every call.

**A deterministic signature-consistency guardrail** (`_signature_consistent`, pure
Python, no LLM) independently checks whether the model's chosen mechanism's known
sensor signature actually matches the labeled readings. A report is only marked
`triaged` when confidence ≥ 0.7 **and** the guardrail agrees; otherwise (or always, for
`unrecognized_pattern`) it's `needs_review`. A small model's self-reported confidence
alone was found to be close to meaningless — this guardrail is what actually catches
most wrong diagnoses before they'd reach an engineer as if confident.

**Repair steps are looked up from code, never LLM-generated** — the LLM only picks the
mechanism and writes a one-sentence explanation; the repair checklist per mechanism is
a fixed table in `core/mechanisms.py`, to avoid a small model inventing procedures.

**Human-in-the-loop history.** `defect_history` (the one ChromaDB collection the live
pipeline actually queries) is written to *only* by `POST /reports/{id}/verify`, never by
the automatic pipeline — so the system's memory of "what actually happened" only grows
from human-confirmed outcomes, not from its own unverified guesses.

**Redis Streams over Kafka; Prefect over LangGraph.** Unchanged reasoning from the
original design — Redis Streams are right-sized for this event volume, and Prefect is a
workflow orchestrator (retries, state, observability) for a deterministic pipeline,
which is a different tool category than an agent state machine.

---

## Model Choice

Tested `llama3.2:3b` and `qwen2.5:3b` on the same task (schema-constrained diagnosis
over the mechanism taxonomy). Both ran at essentially the same latency (~35-40s/call on
this hardware — CPU inference, not GPU) and similar raw accuracy in small (n=10-15)
smoke tests. `llama3.2:3b` was chosen because it showed zero candidate-position bias and
zero guardrail false-positives across its runs, while `qwen2.5:3b` reintroduced some
position bias. This was a directional call based on small uncontrolled samples — the
formal eval below is what actually characterizes `llama3.2:3b`'s behavior in detail.

---

## Evaluation Suite

`evals/run_eval.py` runs a fixed, versioned 40-event dataset (`evals/dataset.json`)
against the pipeline and reports:

- Overall / fault accuracy, plus accuracy broken down by category and process step
- Confusion matrix (which mechanisms get confused for which)
- Confidence calibration (does stated confidence actually track correctness)
- Guardrail effectiveness — catch rate on wrong diagnoses, false-positive rate on
  correct ones
- Note-dependent subset accuracy — cases only solvable by reading the operator note
- `unrecognized_pattern` precision/recall
- Normal true-negative rate, last-position bias, parse failures

```bash
python evals/run_eval.py
LLM_MODEL=qwen2.5:3b python evals/run_eval.py   # compare another model on the same set
```

See `evals/README.md` for dataset composition and full metric definitions; results are
saved to `evals/results_<model>_<timestamp>.json` per run.

---

## RAG Pipeline (Retrieval-Augmented Generation)

```
Anomaly detected (rule-based)
      │
      ▼
Query ChromaDB defect_history, scoped to this process step
      │  cosine similarity search, top 2
      ▼
Verified past cases (mechanism + fix_applied) injected into the diagnosis prompt
      │
      ▼
llama3.2:3b diagnoses mechanism + confidence + explanation (schema-constrained)
      │
      ▼
Signature guardrail + confidence threshold → triaged or needs_review
      │
      ▼
Engineer verifies (confirm/correct) → writes back into defect_history
```

---

## Next Steps / Roadmap

**Near-term (backend polish):**
- Re-run the full 40-event eval now that `_note_contradicts_pick` is sentence-scoped,
  to measure the actual delta on guardrail false-positive rate

**Deliberately deferred (kept out of scope for this project):**
- ML-based anomaly detection (e.g. Isolation Forest) alongside the rule-based limits
- Wafer genealogy / commonality graph across lots
- Time-window / trend-based alerting (vs. per-event diagnosis)
- Config-driven multi-domain support (this is semiconductor-specific by design)

**Production-scale (not attempted here):**
- GitHub Actions CD to a cloud host
- GPU inference for lower per-call latency
- Prometheus + Grafana for defect-rate / latency / confidence-trend metrics
- WebSocket push instead of 3s dashboard polling

---
