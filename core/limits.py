# Sensor limits — single source of truth for detection and labeling.
# normal_low/high: expected operating band
# alarm_low/high:  beyond this → HIGH/LOW label; None where a side doesn't apply

SENSOR_LIMITS = {
    "temperature": {
        "normal_low":  130.0,
        "normal_high": 140.0,
        "alarm_low":   None,
        "alarm_high":  150.0,
        "unit":        "°C",
    },
    "pressure": {
        "normal_low":  2.8,
        "normal_high": 3.2,
        "alarm_low":   2.0,
        "alarm_high":  4.0,
        "unit":        "mTorr",
    },
    "vibration": {
        "normal_low":  0.1,
        "normal_high": 0.5,
        "alarm_low":   None,
        "alarm_high":  0.8,
        "unit":        "mm/s",
    },
    "particle_count": {
        "normal_low":  None,
        "normal_high": 5.0,
        "alarm_low":   None,
        "alarm_high":  10.0,
        "unit":        "ppm",
    },
    "flow_rate": {
        "normal_low":  95.0,
        "normal_high": 105.0,
        "alarm_low":   85.0,
        "alarm_high":  115.0,
        "unit":        "sccm",
    },
}


def label_reading(sensor: str, value: float) -> dict:
    """Label a sensor reading and compute deviation from the nearest limit."""
    cfg = SENSOR_LIMITS[sensor]
    n_lo = cfg["normal_low"]
    n_hi = cfg["normal_high"]
    a_lo = cfg["alarm_low"]
    a_hi = cfg["alarm_high"]

    # HIGH side
    if a_hi is not None and value > a_hi:
        dev = round((value - a_hi) / a_hi * 100, 1)
        return {"label": "HIGH", "value": value, "deviation_pct": dev, "direction": "high"}
    if value > n_hi:
        dev = round((value - n_hi) / n_hi * 100, 1)
        return {"label": "slightly_high", "value": value, "deviation_pct": dev, "direction": "high"}

    # LOW side
    if a_lo is not None and value < a_lo:
        dev = round((a_lo - value) / a_lo * 100, 1)
        return {"label": "LOW", "value": value, "deviation_pct": dev, "direction": "low"}
    if n_lo is not None and value < n_lo:
        dev = round((n_lo - value) / n_lo * 100, 1)
        return {"label": "slightly_low", "value": value, "deviation_pct": dev, "direction": "low"}

    return {"label": "normal", "value": value, "deviation_pct": 0.0, "direction": "none"}


def label_all_readings(readings: dict) -> dict:
    """Label all sensors in a readings dict. Returns {sensor: label_result}."""
    return {sensor: label_reading(sensor, value) for sensor, value in readings.items()}


def has_alarm(labeled: dict) -> bool:
    """True if at least one reading is HIGH or LOW."""
    return any(r["label"] in ("HIGH", "LOW") for r in labeled.values())
