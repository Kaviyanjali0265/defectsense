def defect_classification_prompt(event: dict, deviation: float, similar_context: str) -> str:
    return f"""You are a semiconductor process engineer. Classify the defect below and respond in JSON only.

Anomaly:
- Sensor: {event['sensor']}
- Process step: {event['process_step']}
- Value: {event['value']} {event['unit']} ({deviation}% above threshold)

Similar past defects:
{similar_context if similar_context else "None."}

Rules:
1. defect_type MUST be exactly one of: thermal_excursion, pressure_deviation, mechanical_fault, contamination, flow_anomaly
2. confidence MUST be a number between 0.5 and 0.95
3. root_cause MUST be a short phrase (under 10 words)
4. explanation MUST be one sentence about why this defect occurred

Respond with ONLY this JSON and nothing else:
{{"defect_type": "contamination", "root_cause": "airlock seal failure at lithography", "confidence": 0.82, "explanation": "Particle count exceeded threshold due to airlock breach allowing contaminants into the clean environment."}}

Now classify the anomaly above using the same JSON format:"""
