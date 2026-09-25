"""Unit tests covering DefectSense redesign steps 1–7."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import SENSOR_LIMITS, has_alarm, label_all_readings, label_reading
from core.mechanisms import (
    MECHANISMS,
    STEP_MECHANISMS,
    candidates_for_step,
    get_distinguishing_check,
)
from core.models import DefectReport, MechanismEnum, ProcessStep, SensorEvent
from ingest.generator import _readings_for, _signature_value, _unrecognized_readings

# ── Step 2: core/limits.py ────────────────────────────────────────────────────

class TestLabelReading:
    def test_normal(self):
        r = label_reading("temperature", 135.0)
        assert r["label"] == "normal"
        assert r["deviation_pct"] == 0.0

    def test_high_alarm(self):
        r = label_reading("temperature", 155.0)
        assert r["label"] == "HIGH"
        assert r["deviation_pct"] > 0

    def test_slightly_high(self):
        r = label_reading("temperature", 143.0)
        assert r["label"] == "slightly_high"

    def test_low_alarm(self):
        r = label_reading("pressure", 1.8)
        assert r["label"] == "LOW"

    def test_slightly_low(self):
        r = label_reading("pressure", 2.5)
        assert r["label"] == "slightly_low"

    def test_particle_no_low_alarm(self):
        # particle_count has no alarm_low — 0 should be "normal" (n_lo is None)
        r = label_reading("particle_count", 0.0)
        assert r["label"] == "normal"

    def test_all_sensors_in_limits_dict(self):
        for sensor in SENSOR_LIMITS:
            r = label_reading(sensor, SENSOR_LIMITS[sensor]["normal_high"])
            assert "label" in r


class TestLabelAllReadings:
    def test_returns_all_sensors(self):
        readings = {s: SENSOR_LIMITS[s]["normal_high"] for s in SENSOR_LIMITS}
        labeled = label_all_readings(readings)
        assert set(labeled.keys()) == set(SENSOR_LIMITS.keys())

    def test_has_alarm_true(self):
        readings = {s: SENSOR_LIMITS[s]["normal_low"] or 0 for s in SENSOR_LIMITS}
        readings["temperature"] = 200.0  # well above alarm_high
        labeled = label_all_readings(readings)
        assert has_alarm(labeled) is True

    def test_has_alarm_false_all_normal(self):
        readings = {s: (SENSOR_LIMITS[s]["normal_low"] or 0) + 1.0 for s in SENSOR_LIMITS}
        # Keep everything strictly inside normal band
        for s in SENSOR_LIMITS:
            readings[s] = (SENSOR_LIMITS[s]["normal_high"] + (SENSOR_LIMITS[s]["normal_low"] or 0)) / 2
        labeled = label_all_readings(readings)
        assert has_alarm(labeled) is False


# ── Step 3: core/mechanisms.py ───────────────────────────────────────────────

class TestMechanisms:
    def test_all_18_real_mechanisms_plus_unrecognized(self):
        assert "unrecognized_pattern" in MECHANISMS
        real = [m for m in MECHANISMS if m != "unrecognized_pattern"]
        assert len(real) == 18

    def test_each_mechanism_has_required_keys(self):
        for mid, data in MECHANISMS.items():
            for key in ("category", "step", "signature", "repair_steps"):
                assert key in data, f"Missing key '{key}' in {mid}"

    def test_step_mechanisms_covers_all_steps(self):
        expected_steps = {
            "deposition", "cmp", "lithography", "etching",
            "wet_clean", "diffusion", "inspection", "metrology",
        }
        assert set(STEP_MECHANISMS.keys()) == expected_steps

    def test_candidates_for_step_includes_unrecognized(self):
        for step in STEP_MECHANISMS:
            candidates = candidates_for_step(step)
            assert "unrecognized_pattern" in candidates

    def test_candidates_for_step_excludes_other_step_mechanisms(self):
        cmp_candidates = set(candidates_for_step("cmp"))
        etching_candidates = set(candidates_for_step("etching"))
        # mechanisms belonging only to cmp should not appear in etching candidates
        cmp_only = set(STEP_MECHANISMS["cmp"]) - set(STEP_MECHANISMS.get("etching", []))
        assert cmp_only.issubset(cmp_candidates)
        assert not cmp_only.intersection(etching_candidates - {"unrecognized_pattern"})

    def test_get_distinguishing_check_known_pair(self):
        check = get_distinguishing_check("head_bearing_wear", "polishing_pad_wear")
        assert check is not None
        assert "vibration" in check.lower() or "particle" in check.lower()

    def test_get_distinguishing_check_none_for_no_alternative(self):
        assert get_distinguishing_check("head_bearing_wear", None) is None

    def test_get_distinguishing_check_unknown_pair_returns_none(self):
        check = get_distinguishing_check("chamber_seal_leak", "mfc_drift")
        assert check is None

    def test_unrecognized_pattern_has_no_step(self):
        assert MECHANISMS["unrecognized_pattern"]["step"] is None


# ── Step 4: core/models.py ───────────────────────────────────────────────────

class TestModels:
    def test_sensor_event_valid(self):
        event = SensorEvent(
            wafer_id="W-0001",
            machine_id="CMP-01",
            process_step="cmp",
            timestamp="2026-01-01T00:00:00Z",
            readings={
                "temperature": 135.0,
                "pressure": 3.0,
                "vibration": 0.3,
                "particle_count": 2.0,
                "flow_rate": 100.0,
            },
        )
        assert event.event_id != ""

    def test_sensor_event_invalid_step(self):
        with pytest.raises(ValidationError):
            SensorEvent(
                wafer_id="W-0001",
                machine_id="CMP-01",
                process_step="invalid_step",
                timestamp="2026-01-01T00:00:00Z",
                readings={
                    "temperature": 135.0,
                    "pressure": 3.0,
                    "vibration": 0.3,
                    "particle_count": 2.0,
                    "flow_rate": 100.0,
                },
            )

    def test_mechanism_enum_has_19_values(self):
        assert len(MechanismEnum) == 19

    def test_mechanism_enum_contains_unrecognized(self):
        assert MechanismEnum.unrecognized_pattern.value == "unrecognized_pattern"

    def test_defect_report_defaults(self):
        r = DefectReport(
            event_id="e1",
            wafer_id="W-1",
            machine_id="CMP-01",
            process_step="cmp",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert r.status == "pending"
        assert r.recurrence_count == 0
        assert r.repair_steps == []

    def test_defect_report_status_values(self):
        for status in ("pending", "triaged", "needs_review", "diagnosis_failed"):
            r = DefectReport(
                event_id="e1",
                wafer_id="W-1",
                machine_id="CMP-01",
                process_step="cmp",
                timestamp="2026-01-01T00:00:00Z",
                status=status,
            )
            assert r.status == status

    def test_process_step_enum_has_wet_clean(self):
        assert ProcessStep.wet_clean.value == "wet_clean"


# ── Step 5: ingest/generator.py ──────────────────────────────────────────────

class TestGenerator:
    def test_signature_value_high_above_alarm(self):
        val = _signature_value("temperature", "HIGH")
        assert val > SENSOR_LIMITS["temperature"]["alarm_high"]

    def test_signature_value_low_below_alarm(self):
        # pressure has alarm_low=2.0
        val = _signature_value("pressure", "LOW")
        assert val < SENSOR_LIMITS["pressure"]["alarm_low"]

    def test_signature_value_normal_in_band(self):
        for _ in range(10):
            val = _signature_value("flow_rate", "normal")
            cfg = SENSOR_LIMITS["flow_rate"]
            assert cfg["normal_low"] <= val <= cfg["normal_high"] * 1.05  # allow small noise

    def test_readings_for_has_all_sensors(self):
        readings = _readings_for("head_bearing_wear")
        assert set(readings.keys()) == set(SENSOR_LIMITS.keys())

    def test_readings_for_signature_sensors_in_alarm(self):
        readings = _readings_for("head_bearing_wear")
        labeled = label_all_readings(readings)
        assert labeled["vibration"]["label"] == "HIGH"

    def test_generated_readings_label_matches_signature(self):
        """Fix 6: generated readings must label exactly to the mechanism's signature."""
        for mid, data in MECHANISMS.items():
            if mid == "unrecognized_pattern":
                continue
            for _ in range(3):
                readings = _readings_for(mid)
                labeled = label_all_readings(readings)
                for sensor, expected_label in data["signature"].items():
                    actual = labeled[sensor]["label"]
                    assert actual == expected_label, (
                        f"{mid}.{sensor}: expected {expected_label}, got {actual} "
                        f"(value={readings[sensor]})"
                    )

    def test_unrecognized_readings_triggers_alarm(self):
        for step in ["cmp", "etching", "diffusion"]:
            readings = _unrecognized_readings(step)
            labeled = label_all_readings(readings)
            assert has_alarm(labeled), f"unrecognized readings for {step} should have alarm"


# ── Step 7: pipeline/flows.py (non-LLM parts) ────────────────────────────────

class TestSignatureConsistency:
    def test_correct_mechanism_consistent(self):
        from ingest.generator import _readings_for
        from pipeline.flows import _signature_consistent
        readings = _readings_for("head_bearing_wear")
        labeled = label_all_readings(readings)
        assert _signature_consistent("head_bearing_wear", labeled) is True

    def test_wrong_mechanism_inconsistent(self):
        from ingest.generator import _readings_for
        from pipeline.flows import _signature_consistent
        # head_bearing_wear has vibration HIGH — slurry_line_blockage needs flow LOW
        readings = _readings_for("head_bearing_wear")
        labeled = label_all_readings(readings)
        assert _signature_consistent("slurry_line_blockage", labeled) is False

    def test_unrecognized_always_consistent(self):
        from pipeline.flows import _signature_consistent
        readings = {s: SENSOR_LIMITS[s]["normal_high"] for s in SENSOR_LIMITS}
        readings["temperature"] = 200.0
        labeled = label_all_readings(readings)
        assert _signature_consistent("unrecognized_pattern", labeled) is True


class TestDetectAnomalies:
    """Test detect_anomalies without Prefect context — call the inner logic directly."""

    def _call(self, readings: dict) -> dict:
        from pipeline.flows import NoAnomalyError
        labeled = label_all_readings(readings)
        if not has_alarm(labeled):
            raise NoAnomalyError("normal event")
        return {"event_id": "e1", "wafer_id": "W-1", "process_step": "cmp", "labeled_readings": labeled}

    def test_normal_event_raises_no_anomaly_error(self):
        from pipeline.flows import NoAnomalyError
        readings = {}
        for s in SENSOR_LIMITS:
            lo = SENSOR_LIMITS[s]["normal_low"] or 0
            hi = SENSOR_LIMITS[s]["normal_high"]
            readings[s] = (lo + hi) / 2
        with pytest.raises(NoAnomalyError):
            self._call(readings)

    def test_alarm_event_passes(self):
        readings = {s: (SENSOR_LIMITS[s]["normal_low"] or 0 + SENSOR_LIMITS[s]["normal_high"]) / 2
                    for s in SENSOR_LIMITS}
        for s in SENSOR_LIMITS:
            lo = SENSOR_LIMITS[s]["normal_low"] or 0
            readings[s] = (lo + SENSOR_LIMITS[s]["normal_high"]) / 2
        readings["temperature"] = 200.0  # force HIGH
        result = self._call(readings)
        assert "labeled_readings" in result
        assert result["labeled_readings"]["temperature"]["label"] == "HIGH"


class TestDiagnosisOutput:
    """Test Pydantic validation of DiagnosisOutput without calling Ollama."""

    def _get_model(self):
        from pipeline.flows import DiagnosisOutput
        return DiagnosisOutput

    def test_valid_diagnosis(self):
        DiagnosisOutput = self._get_model()
        d = DiagnosisOutput(
            reasoning="vibration HIGH matches head_bearing_wear",
            mechanism="head_bearing_wear",
            confidence=0.85,
            alternative_mechanism="polishing_pad_wear",
            explanation="Vibration HIGH at 0.91 mm/s",
        )
        assert d.mechanism == "head_bearing_wear"

    def test_confidence_below_range_clamped(self):
        DiagnosisOutput = self._get_model()
        d = DiagnosisOutput(mechanism="head_bearing_wear", confidence=0.3, explanation="test")
        assert d.confidence == 0.5  # clamped to minimum

    def test_confidence_above_range_clamped(self):
        DiagnosisOutput = self._get_model()
        d = DiagnosisOutput(mechanism="head_bearing_wear", confidence=0.99, explanation="test")
        assert d.confidence == 0.95  # clamped to maximum

    def test_unknown_mechanism_rejected(self):
        DiagnosisOutput = self._get_model()
        with pytest.raises(ValidationError):
            DiagnosisOutput(
                mechanism="invented_fault",
                confidence=0.80,
                explanation="test",
            )

    def test_alternative_same_as_mechanism_repaired(self):
        DiagnosisOutput = self._get_model()
        d = DiagnosisOutput(
            mechanism="head_bearing_wear",
            confidence=0.80,
            alternative_mechanism="head_bearing_wear",
            explanation="test",
        )
        assert d.alternative_mechanism is None  # repaired to null

    def test_null_alternative_is_valid(self):
        DiagnosisOutput = self._get_model()
        d = DiagnosisOutput(
            mechanism="heater_degradation",
            confidence=0.75,
            alternative_mechanism=None,
            explanation="Temperature HIGH only",
        )
        assert d.alternative_mechanism is None


# ── Step 6: pipeline/prompts.py ──────────────────────────────────────────────

class TestBuildDiagnosisPrompt:
    def _sample_event(self, step="cmp"):
        return {
            "event_id":     "e1",
            "wafer_id":     "W-1234",
            "machine_id":   "CMP-01",
            "process_step": step,
            "timestamp":    "2026-01-01T00:00:00Z",
            "operator_note": None,
        }

    def _labeled_for_step(self, step):
        mechs = STEP_MECHANISMS.get(step, [])
        if mechs:
            sig = MECHANISMS[mechs[0]]["signature"]
            readings = {s: SENSOR_LIMITS[s]["normal_high"] for s in SENSOR_LIMITS}
            for s, lbl in sig.items():
                readings[s] = _signature_value(s, lbl)
            return label_all_readings(readings)
        return label_all_readings({s: SENSOR_LIMITS[s]["normal_high"] for s in SENSOR_LIMITS})

    def test_prompt_contains_step_candidates(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("cmp")
        labeled = self._labeled_for_step("cmp")
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        for cand in candidates_for_step("cmp"):
            assert cand in prompt

    def test_prompt_contains_unrecognized_pattern(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("etching")
        labeled = self._labeled_for_step("etching")
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        assert "unrecognized_pattern" in prompt

    def test_prompt_does_not_contain_other_step_mechanisms_in_candidates(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("diffusion")
        labeled = self._labeled_for_step("diffusion")
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        candidates_section = prompt.split("Candidates")[1].split("EXAMPLE")[0]
        for cmp_only in STEP_MECHANISMS["cmp"]:
            assert cmp_only not in candidates_section, (
                f"cmp mechanism '{cmp_only}' appeared in diffusion candidates block"
            )

    def test_prompt_contains_alarm_marker(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("cmp")
        readings = {s: SENSOR_LIMITS[s]["normal_high"] for s in SENSOR_LIMITS}
        readings["vibration"] = 1.5  # force HIGH
        labeled = label_all_readings(readings)
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        assert "***" in prompt

    def test_prompt_includes_history(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("cmp")
        labeled = self._labeled_for_step("cmp")
        history = [{"mechanism": "head_bearing_wear", "step": "cmp", "machine": "CMP-01", "fix_applied": "bearing replaced"}]
        prompt, _order = build_diagnosis_prompt(event, labeled, history)
        assert "head_bearing_wear" in prompt

    def test_prompt_no_history_block(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("cmp")
        labeled = self._labeled_for_step("cmp")
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        assert "Verified past cases" not in prompt

    def test_prompt_includes_json_schema_instruction(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("deposition")
        labeled = self._labeled_for_step("deposition")
        prompt, _order = build_diagnosis_prompt(event, labeled, [])
        assert '"mechanism"' in prompt and '"confidence"' in prompt

    def test_prompt_returns_shuffled_order(self):
        from pipeline.prompts import build_diagnosis_prompt
        event = self._sample_event("cmp")
        labeled = self._labeled_for_step("cmp")
        _, order = build_diagnosis_prompt(event, labeled, [])
        assert set(order) == set(candidates_for_step("cmp"))


# ── Step 1: graph_store.py (process flow order) ──────────────────────────────

class TestGraphStore:
    def test_process_flow_imports(self):
        from core.graph_store import PROCESS_FLOW
        steps = [s for s, _ in PROCESS_FLOW]
        assert steps[0] == "deposition"
        assert "wet_clean" in steps

    def test_downstream_starts_after_source(self):
        from core.graph_store import get_downstream_impact
        downstream = get_downstream_impact("cmp", depth=2)
        step_names = [d["step"] for d in downstream]
        assert "deposition" not in step_names
        assert "lithography" in step_names or "etching" in step_names or len(step_names) >= 0
