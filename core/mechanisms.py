# Single source of truth for the mechanism taxonomy.
# Steps marked [DEMO] are simplified placeholders for mechanisms not in the original KB.

MECHANISMS = {
    # ── deposition ────────────────────────────────────────────────────────
    "chamber_seal_leak": {
        "category":     "pressure_deviation",
        "step":         "deposition",
        "signature":    {"pressure": "HIGH", "particle_count": "slightly_high"},
        "repair_steps": [
            "Replace chamber O-ring",
            "Verify valve operation",
            "Run leak-check before resuming",
        ],
    },
    "coolant_restriction": {
        "category":     "thermal_excursion",
        "step":         "deposition",
        "signature":    {"temperature": "HIGH", "pressure": "slightly_high"},
        "repair_steps": [
            "Check coolant lines for blockage",
            "Verify chuck temperature control",
            "Recalibrate thermal PID",
        ],
    },
    "gas_line_restriction": {
        "category":     "flow_anomaly",
        "step":         "deposition",
        "signature":    {"flow_rate": "LOW", "pressure": "HIGH"},
        "repair_steps": [
            "Check bubbler temperature",
            "Inspect gas lines for blockage",
            "Purge and verify flow at nominal setpoint",
        ],
    },

    # ── cmp ───────────────────────────────────────────────────────────────
    "polishing_pad_wear": {
        "category":     "contamination",
        "step":         "cmp",
        "signature":    {"particle_count": "HIGH", "vibration": "slightly_high"},
        "repair_steps": [
            "Replace polishing pad",
            "Flush slurry lines",
            "Run particle baseline before resuming",
        ],
    },
    "head_bearing_wear": {
        "category":     "mechanical_fault",
        "step":         "cmp",
        "signature":    {"vibration": "HIGH", "particle_count": "normal"},
        "repair_steps": [
            "Inspect polishing head bearings",
            "Balance platen",
            "Verify vibration within spec before resuming",
        ],
    },
    "slurry_line_blockage": {
        "category":     "flow_anomaly",
        "step":         "cmp",
        "signature":    {"flow_rate": "LOW", "temperature": "slightly_high"},
        "repair_steps": [
            "Inspect and clear slurry supply line",  # [DEMO]
            "Check slurry pump pressure",
            "Run flow calibration after clearing",
        ],
    },

    # ── lithography ───────────────────────────────────────────────────────
    "airlock_breach": {
        "category":     "contamination",
        "step":         "lithography",
        "signature":    {"particle_count": "HIGH", "pressure": "slightly_low"},
        "repair_steps": [
            "Inspect airlock seals",
            "Run particle baseline measurement",
            "Verify pressure differential before resuming",
        ],
    },
    "stage_isolation_failure": {
        "category":     "mechanical_fault",
        "step":         "lithography",
        "signature":    {"vibration": "HIGH", "particle_count": "normal"},
        "repair_steps": [
            "Inspect stage isolation mounts",  # [DEMO]
            "Check anti-vibration dampers",
            "Run stage calibration scan",
        ],
    },

    # ── etching ───────────────────────────────────────────────────────────
    "exhaust_valve_blockage": {
        "category":     "pressure_deviation",
        "step":         "etching",
        "signature":    {"pressure": "HIGH", "flow_rate": "normal"},
        "repair_steps": [
            "Inspect exhaust valve",
            "Check O-ring integrity",
            "Verify chamber pressure at setpoint",
        ],
    },
    "mfc_drift": {
        "category":     "flow_anomaly",
        "step":         "etching",
        "signature":    {"flow_rate": "HIGH", "pressure": "slightly_high"},
        "repair_steps": [
            "Recalibrate MFC",
            "Purge gas lines",
            "Verify flow at nominal setpoint",
        ],
    },
    "electrode_erosion": {
        "category":     "contamination",
        "step":         "etching",
        "signature":    {"particle_count": "HIGH", "temperature": "slightly_high"},
        "repair_steps": [
            "Inspect and replace etch electrode",  # [DEMO]
            "Clean chamber walls",
            "Run particle baseline before resuming",
        ],
    },

    # ── wet_clean ─────────────────────────────────────────────────────────
    "chemical_bath_contamination": {
        "category":     "contamination",
        "step":         "wet_clean",
        "signature":    {"particle_count": "HIGH", "temperature": "slightly_high"},
        "repair_steps": [
            "Drain and replace chemical bath",  # [DEMO]
            "Clean bath tank and recirculation lines",
            "Verify bath chemistry before resuming",
        ],
    },
    "rinse_flow_failure": {
        "category":     "flow_anomaly",
        "step":         "wet_clean",
        "signature":    {"flow_rate": "LOW", "particle_count": "slightly_high"},
        "repair_steps": [
            "Inspect DI water supply valve",  # [DEMO]
            "Check rinse nozzles for blockage",
            "Verify rinse flow rate at setpoint",
        ],
    },

    # ── diffusion ─────────────────────────────────────────────────────────
    "heater_degradation": {
        "category":     "thermal_excursion",
        "step":         "diffusion",
        "signature":    {"temperature": "HIGH"},
        "repair_steps": [
            "Recalibrate furnace PID controller",
            "Inspect heating elements",
            "Verify temperature profile across tube",
        ],
    },
    "purge_gas_failure": {
        "category":     "flow_anomaly",
        "step":         "diffusion",
        "signature":    {"flow_rate": "LOW", "temperature": "slightly_high"},
        "repair_steps": [
            "Inspect purge gas supply valve",  # [DEMO]
            "Check MFC calibration for purge line",
            "Verify purge flow before resuming",
        ],
    },

    # ── inspection ────────────────────────────────────────────────────────
    "stage_motor_bearing_wear": {
        "category":     "mechanical_fault",
        "step":         "inspection",
        "signature":    {"vibration": "HIGH"},
        "repair_steps": [
            "Replace stage motor bearings",
            "Recalibrate scan stage",
            "Run vibration check at operating speed",
        ],
    },
    "upstream_contamination": {
        "category":     "contamination",
        "step":         "inspection",
        "signature":    {"particle_count": "HIGH"},
        "repair_steps": [
            "Identify upstream source using possible_origin_steps",  # [DEMO]
            "Quarantine affected wafer lot",
            "Inspect upstream steps and clear contamination source",
        ],
    },

    # ── metrology ─────────────────────────────────────────────────────────
    "enclosure_temperature_drift": {
        "category":     "thermal_excursion",
        "step":         "metrology",
        "signature":    {"temperature": "HIGH"},
        "repair_steps": [
            "Inspect enclosure HVAC unit",  # [DEMO]
            "Verify ambient temperature setpoint",
            "Run thermal stabilisation before next measurement",
        ],
    },

    # ── catch-all ─────────────────────────────────────────────────────────
    "unrecognized_pattern": {
        "category":     "unclassified",
        "step":         None,   # applies to any step
        "signature":    {},
        "repair_steps": [],
    },
}

# Category lookup
CATEGORY = {m: v["category"] for m, v in MECHANISMS.items()}

# Repair steps lookup
REPAIR_STEPS = {m: v["repair_steps"] for m, v in MECHANISMS.items()}

# Which mechanisms belong to each step (+ unrecognized_pattern always included)
STEP_MECHANISMS: dict[str, list[str]] = {}
for _m, _v in MECHANISMS.items():
    if _v["step"] is not None:
        STEP_MECHANISMS.setdefault(_v["step"], []).append(_m)

# Distinguishing checks: keyed by frozenset({m1, m2}) → check string
DISTINGUISHING_CHECKS: dict[frozenset, str] = {
    frozenset({"chamber_seal_leak", "coolant_restriction"}):
        "Temperature HIGH → coolant_restriction; particle_count elevated → chamber_seal_leak",
    frozenset({"chamber_seal_leak", "gas_line_restriction"}):
        "Flow LOW → gas_line_restriction; particle_count elevated → chamber_seal_leak",
    frozenset({"coolant_restriction", "gas_line_restriction"}):
        "Temperature HIGH → coolant_restriction; flow LOW → gas_line_restriction",
    frozenset({"polishing_pad_wear", "head_bearing_wear"}):
        "Particle_count elevated → polishing_pad_wear; vibration HIGH with normal particles → head_bearing_wear",
    frozenset({"polishing_pad_wear", "slurry_line_blockage"}):
        "Flow LOW → slurry_line_blockage; particle_count HIGH → polishing_pad_wear",
    frozenset({"head_bearing_wear", "slurry_line_blockage"}):
        "Vibration HIGH → head_bearing_wear; flow LOW → slurry_line_blockage",
    frozenset({"airlock_breach", "stage_isolation_failure"}):
        "Particle_count HIGH → airlock_breach; vibration HIGH → stage_isolation_failure",
    frozenset({"exhaust_valve_blockage", "mfc_drift"}):
        "Flow HIGH → mfc_drift; flow normal → exhaust_valve_blockage",
    frozenset({"exhaust_valve_blockage", "electrode_erosion"}):
        "Particle_count HIGH → electrode_erosion; particles normal → exhaust_valve_blockage",
    frozenset({"mfc_drift", "electrode_erosion"}):
        "Flow HIGH → mfc_drift; particle_count HIGH → electrode_erosion",
    frozenset({"chemical_bath_contamination", "rinse_flow_failure"}):
        "Flow LOW → rinse_flow_failure; temperature elevated → chemical_bath_contamination",
    frozenset({"heater_degradation", "purge_gas_failure"}):
        "Flow LOW → purge_gas_failure; temperature HIGH with normal flow → heater_degradation",
    frozenset({"stage_motor_bearing_wear", "upstream_contamination"}):
        "Vibration HIGH → stage_motor_bearing_wear; particle_count HIGH → upstream_contamination",
}


def get_distinguishing_check(mechanism: str, alternative: str | None) -> str | None:
    if alternative is None:
        return None
    key = frozenset({mechanism, alternative})
    return DISTINGUISHING_CHECKS.get(key)


def candidates_for_step(step: str) -> list[str]:
    """Return allowed mechanism ids for a given process step + unrecognized_pattern."""
    return STEP_MECHANISMS.get(step, []) + ["unrecognized_pattern"]
