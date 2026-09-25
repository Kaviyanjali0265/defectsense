"""Prompt builder for the diagnosis step."""
import random

from core.limits import SENSOR_LIMITS
from core.mechanisms import MECHANISMS, candidates_for_step, get_distinguishing_check


def _candidate_block(shuffled_candidates: list[str]) -> str:
    lines = []
    for mid in shuffled_candidates:
        if mid == "unrecognized_pattern":
            lines.append("- unrecognized_pattern: none of the above match")
            continue
        m = MECHANISMS[mid]
        sig = ", ".join(f"{s} {lbl}" for s, lbl in m["signature"].items())
        lines.append(f"- {mid}: {sig}")
    return "\n".join(lines)


def _readings_block(labeled_readings: dict) -> str:
    lines = []
    for sensor, info in labeled_readings.items():
        unit  = SENSOR_LIMITS[sensor]["unit"]
        label = info["label"]
        val   = info["value"]
        alarm = " ***" if label in ("HIGH", "LOW") else ""
        lines.append(f"  {sensor:16}: {val} {unit}  [{label}]{alarm}")
    return "\n".join(lines)


def _distinguishing_block(shuffled_candidates: list[str]) -> str:
    seen, lines = set(), []
    real = [c for c in shuffled_candidates if c != "unrecognized_pattern"]
    for i, m1 in enumerate(real):
        for m2 in real[i+1:]:
            key = frozenset({m1, m2})
            check = get_distinguishing_check(m1, m2)
            if check and key not in seen:
                seen.add(key)
                lines.append(f"  {m1} vs {m2}: {check}")
    return "\n".join(lines)


def build_diagnosis_prompt(
    event: dict,
    labeled_readings: dict,
    verified_history: list[dict],
    shuffled_candidates: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Returns (prompt_str, shuffled_candidates_order)."""
    step    = event["process_step"]
    machine = event.get("machine_id", "unknown")
    note    = event.get("operator_note") or "none"

    if shuffled_candidates is None:
        candidates = candidates_for_step(step)
        shuffled_candidates = candidates[:]
        random.shuffle(shuffled_candidates)

    history_lines = ""
    if verified_history:
        cases = [
            f"  - {h.get('mechanism')} (fix: {h.get('fix_applied','?')})"
            for h in verified_history[:2]
        ]
        history_lines = "\nVerified past cases:\n" + "\n".join(cases) + "\n"

    dist = _distinguishing_block(shuffled_candidates)
    dist_block = f"\nDistinguishing checks:\n{dist}\n" if dist else ""

    prompt = f"""Semiconductor process engineer diagnosing a sensor anomaly.

Step: {step}  Machine: {machine}  Note: {note}

If the note states a component was recently serviced, replaced, recalibrated, or confirmed healthy,
treat that component as RULED OUT — even if its sensor signature matches the readings below.
When two candidates match the readings equally well, the note is the deciding evidence, not the readings.

Readings:
{_readings_block(labeled_readings)}

Candidates (check each against the readings):
{_candidate_block(shuffled_candidates)}
{dist_block}{history_lines}
EXAMPLE 1 — cmp, mechanism is second in list:
Candidates: polishing_pad_wear, head_bearing_wear, slurry_line_blockage, unrecognized_pattern
Readings: vibration HIGH (0.91 mm/s), particles normal (3 ppm)
{{"reasoning":"Vibration HIGH matches head_bearing_wear. Particles normal rules out polishing_pad_wear (needs HIGH). slurry_line_blockage needs flow LOW (absent).","mechanism":"head_bearing_wear","confidence":0.85,"alternative_mechanism":null,"explanation":"Vibration HIGH with normal particles matches head_bearing_wear."}}

EXAMPLE 2 — deposition, unrecognized:
Candidates: gas_line_restriction, coolant_restriction, chamber_seal_leak, unrecognized_pattern
Readings: vibration HIGH (0.92 mm/s), all others normal
{{"reasoning":"Vibration HIGH but no deposition mechanism lists vibration. gas_line_restriction needs flow LOW (absent); coolant_restriction needs temperature HIGH (absent); chamber_seal_leak needs pressure HIGH (absent).","mechanism":"unrecognized_pattern","confidence":0.75,"alternative_mechanism":null,"explanation":"Vibration HIGH matches no deposition mechanism."}}

Check every candidate's required HIGH/LOW signals against the readings above — do not pick
whichever candidate merely looks closest or most familiar. unrecognized_pattern is a common,
correct, and expected answer whenever no candidate's required signals are fully present; it
is not a fallback to avoid. A HIGH/LOW reading on a sensor that no candidate above lists in
its signature is a strong signal the correct answer is unrecognized_pattern.
If the note rules out your top candidate, pick the next candidate whose signals are present instead.
Reply ONLY with JSON — no markdown:
{{"reasoning":"...","mechanism":"...","confidence":0.50-0.95,"alternative_mechanism":null,"explanation":"one sentence"}}"""

    return prompt, shuffled_candidates
