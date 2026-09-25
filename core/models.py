import uuid
from enum import Enum

from pydantic import BaseModel, Field


class ProcessStep(str, Enum):
    deposition  = "deposition"
    cmp         = "cmp"
    lithography = "lithography"
    etching     = "etching"
    wet_clean   = "wet_clean"
    diffusion   = "diffusion"
    inspection  = "inspection"
    metrology   = "metrology"


class SensorReadings(BaseModel):
    temperature:    float
    pressure:       float
    vibration:      float
    particle_count: float
    flow_rate:      float


class SensorEvent(BaseModel):
    event_id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    wafer_id:      str
    machine_id:    str
    process_step:  ProcessStep
    timestamp:     str
    readings:      SensorReadings
    operator_note: str | None = None


class IngestResponse(BaseModel):
    accepted:  bool
    event_id:  str
    message:   str


class MechanismEnum(str, Enum):
    chamber_seal_leak          = "chamber_seal_leak"
    coolant_restriction        = "coolant_restriction"
    gas_line_restriction       = "gas_line_restriction"
    polishing_pad_wear         = "polishing_pad_wear"
    head_bearing_wear          = "head_bearing_wear"
    slurry_line_blockage       = "slurry_line_blockage"
    airlock_breach             = "airlock_breach"
    stage_isolation_failure    = "stage_isolation_failure"
    exhaust_valve_blockage     = "exhaust_valve_blockage"
    mfc_drift                  = "mfc_drift"
    electrode_erosion          = "electrode_erosion"
    chemical_bath_contamination = "chemical_bath_contamination"
    rinse_flow_failure         = "rinse_flow_failure"
    heater_degradation         = "heater_degradation"
    purge_gas_failure          = "purge_gas_failure"
    stage_motor_bearing_wear   = "stage_motor_bearing_wear"
    upstream_contamination     = "upstream_contamination"
    enclosure_temperature_drift = "enclosure_temperature_drift"
    unrecognized_pattern       = "unrecognized_pattern"


class DefectReport(BaseModel):
    event_id:               str
    wafer_id:               str
    machine_id:             str
    process_step:           str
    timestamp:              str
    labeled_readings:       dict = Field(default_factory=dict)
    mechanism:              str | None = None
    category:               str | None = None
    root_cause_step:        str | None = None
    confidence:             float | None = None
    alternative_mechanism:  str | None = None
    distinguishing_check:   str | None = None
    explanation:            str | None = None
    repair_steps:           list[str] = Field(default_factory=list)
    downstream_steps:       list[dict] = Field(default_factory=list)
    possible_origin_steps:  list[str] = Field(default_factory=list)
    seen_before:            list[dict] = Field(default_factory=list)
    recurrence_count:       int = 0
    status:                 str = "pending"
    review_reason:          str | None = None
    verified_mechanism:     str | None = None
    fix_applied:            str | None = None
    verified_at:            str | None = None
