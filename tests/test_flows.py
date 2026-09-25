"""Pure-logic tests for the diagnosis guardrails — no LLM, no Redis, no Ollama."""
from pipeline.flows import _note_contradicts_pick, _signature_consistent


def test_note_contradicts_pick_ignores_correctly_rejected_alternative():
    """The exact pattern EXAMPLE 1 in prompts.py teaches as good reasoning must NOT
    trip the guardrail: 'rules out' referring to a candidate the model did NOT pick.
    """
    reasoning = (
        "Vibration HIGH matches head_bearing_wear. Particles normal rules out "
        "polishing_pad_wear (needs HIGH). slurry_line_blockage needs flow LOW (absent)."
    )
    explanation = "Vibration HIGH with normal particles matches head_bearing_wear."
    assert _note_contradicts_pick("head_bearing_wear", reasoning, explanation) is False


def test_note_contradicts_pick_flags_genuine_self_contradiction():
    """A contradiction phrase describing the model's OWN chosen mechanism should flag."""
    reasoning = (
        "head_bearing_wear was recently serviced yesterday, but vibration is still "
        "HIGH so I'll go with it anyway."
    )
    explanation = "Picking head_bearing_wear despite the note."
    assert _note_contradicts_pick("head_bearing_wear", reasoning, explanation) is True


def test_note_contradicts_pick_never_flags_unrecognized_pattern():
    reasoning = "This mechanism was recently replaced and rules it out entirely."
    assert _note_contradicts_pick("unrecognized_pattern", reasoning, "") is False


def test_note_contradicts_pick_no_contradiction_phrase():
    reasoning = "Vibration HIGH matches head_bearing_wear, all other readings normal."
    assert _note_contradicts_pick("head_bearing_wear", reasoning, "") is False


def test_signature_consistent_matches_expected_signature():
    labeled = {
        "vibration": {"label": "HIGH"},
        "particle_count": {"label": "normal"},
    }
    assert _signature_consistent("head_bearing_wear", labeled) is True


def test_signature_consistent_rejects_mismatch():
    labeled = {
        "vibration": {"label": "normal"},
        "particle_count": {"label": "HIGH"},
    }
    assert _signature_consistent("head_bearing_wear", labeled) is False
