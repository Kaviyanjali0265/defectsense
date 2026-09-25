# DefectSense Eval Suite

Phase-2 formal evaluation of the diagnosis pipeline. This is distinct from
`scripts/smoke_diagnosis.py`, which generates a fresh random batch of events
every run — good for quick iteration, useless for tracking whether a prompt
or model change actually helped, since the sample changes under you each time.

This suite runs against a **fixed, versioned dataset** (`dataset.json`, 40
events, seeded generation — see `build_dataset.py`) so two runs — before/after
a prompt tweak, or `llama3.2:3b` vs. another model — are comparing the exact
same 40 cases.

## Dataset composition (40 events)

| Slice | Count | Purpose |
|---|---|---|
| `unambiguous` | 18 | One clean, textbook case per mechanism (all 18, excl. `unrecognized_pattern`) — the baseline the model should get right |
| `note_dependent` | 4 | 2 genuinely-ambiguous pairs (identical sensor readings, only the operator note disambiguates which component is at fault) |
| `note_neutral` | 2 | Readings alone are already unambiguous; the note just confirms — tests the note doesn't *break* an easy case |
| `unrecognized` | 8 | One `unrecognized_pattern` case per process step — sensor readings that don't match any known mechanism |
| `normal` | 8 | One no-anomaly event per process step — free (rule-based `has_alarm()` skip, no LLM call), confirms the detector doesn't false-alarm |

32 of the 40 events call the LLM (~35-40s each ⇒ roughly 20 minutes total on
`llama3.2:3b`); the 8 `normal` events cost nothing.

This is a small-to-medium eval by design, not a comprehensive one — with a
3B-parameter model this is a learning project, so the point is to honestly
characterize behavior (where it's reliable, where it isn't, whether the
guardrails catch its mistakes), not to chase a large N for its own sake.

## Running it

```
cd defectsense
python evals/run_eval.py
```

Uses whatever `LLM_MODEL` env var is set (defaults to `llama3.2:3b`, matching
the rest of the app). To compare a different model on the same fixed set:

```
LLM_MODEL=qwen2.5:3b python evals/run_eval.py
```

Each run prints a full report to the terminal and writes
`evals/results_<model>_<timestamp>.json` with the raw per-event results
alongside the computed metrics, so past runs are never overwritten.

Diagnosis is run with an **empty** verified-history (same choice
`smoke_diagnosis.py` makes) so results don't drift as `defect_history`
accumulates between runs — the eval measures the model+prompt in isolation,
not the retrieval-augmentation on top of it.

## Metrics computed

- **Overall / fault accuracy** — exact mechanism match against ground truth.
- **Accuracy by category and by process step** — where the model is
  actually weak vs. strong.
- **Confusion matrix** — which mechanisms get confused for which (fault
  events only).
- **Confidence calibration** — accuracy bucketed by the model's stated
  confidence (0.5–0.6, 0.6–0.7, …). This directly tests whether confidence
  means anything for a small model, or whether it's close to noise.
- **Guardrail effectiveness** — of the diagnoses that were actually wrong,
  what fraction did the signature-consistency + self-contradiction
  guardrails catch (flagged `needs_review`) vs. let through as `triaged`.
  Also reports the guardrails' false-positive rate (correct diagnoses
  wrongly flagged).
- **Note-dependent subset accuracy** — performance specifically on the 4
  cases where getting it right requires actually using the operator note.
- **Unrecognized-pattern precision/recall** — both directions: does it
  recognize truly novel patterns, and does it avoid crying "unrecognized"
  on things it should know.
- **Normal true-negative rate** — does the rule-based detector correctly
  leave normal events alone (this part is deterministic, so should be 100%;
  a miss here would be a bug in `has_alarm`/`label_all_readings`, not the LLM).
- **Last-position bias** — carried over from the smoke-test comparisons:
  does the model just pick whichever candidate mechanism happened to be
  shuffled last in the prompt, independent of the actual readings.

## Regenerating the dataset

`dataset.json` is generated once by `build_dataset.py`, which reuses the
real fault-injection functions from `ingest/generator.py` (not a
reimplementation) with a fixed seed (`SEED = 42`), so it can't silently
drift from what the live event generator actually produces. Only re-run it
if the mechanism taxonomy or sensor limits change — regenerating changes
which 40 events are in the set, so treat that as a new dataset version and
don't compare its results directly against results from the old one.
