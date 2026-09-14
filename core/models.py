import uuid
from enum import Enum

from pydantic import BaseModel, Field


class ProcessStep(str, Enum):
    lithography = "lithography"
    etching = "etching"
    deposition = "deposition"
    cmp = "cmp"
    diffusion = "diffusion"
    inspection = "inspection"
    metrology = "metrology"


class SensorType(str, Enum):
    temperature = "temperature"
    pressure = "pressure"
    vibration = "vibration"
    particle_count = "particle_count"
    flow_rate = "flow_rate"


class SensorEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wafer_id: str
    process_step: ProcessStep
    sensor: SensorType
    value: float
    threshold: float
    unit: str
    status: str  # "normal" or "anomaly"
    timestamp: str


class IngestResponse(BaseModel):
    accepted: bool
    event_id: str
    message: str


class DefectReport(BaseModel):
    event_id: str
    wafer_id: str
    defect_type: str | None = None
    root_cause_step: str | None = None
    confidence: float | None = None
    explanation: str | None = None
    status: str = "pending"
