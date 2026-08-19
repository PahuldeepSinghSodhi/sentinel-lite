"""Anomaly Explainer -- LLM-powered explanation of detected anomalies.

This module takes raw anomaly data (type, severity, affected rows, details)
and uses the local Ollama LLM to generate a human-readable explanation of:
  1. What the anomaly means in plain business English
  2. Potential risks (fraud, billing error, policy violation, etc.)
  3. Recommended next steps

The key design principle: the anomaly *detection* is fully rule-based and
transparent (no black-box ML). The LLM is only used for *explanation* --
translating statistical findings into actionable business language.

Usage:
    from app.anomaly.explainer import explain_anomaly
    explanation = explain_anomaly(anomaly_dict)
"""
from app.llm.ollama_client import get_ollama_client


# -- Prompt Template ---------------------------------------------------
# This template is carefully structured to produce concise, actionable
# explanations. We give the LLM the raw anomaly data and ask it to
# play the role of a financial auditor.

EXPLANATION_PROMPT = """You are a senior financial auditor reviewing procurement data for a company. 
An automated system has flagged the following anomaly. Your job is to explain it clearly.

ANOMALY TYPE: {anomaly_type}
SEVERITY: {severity}
DESCRIPTION: {description}
DETAILS: {details}
AFFECTED ROW INDICES: {row_indices}

Please provide a brief explanation in this exact format:

**What was found:** (1-2 sentences explaining the issue in plain business English)

**Why this matters:** (1-2 sentences on the potential business risk -- fraud, overbilling, human error, policy violation, etc.)

**Recommended action:** (1-2 sentences on what the procurement team should do next)

Keep your response concise and professional. Do not repeat the raw data -- interpret it.
"""


def explain_anomaly(anomaly: dict) -> dict:
    """Generate a human-readable explanation for a single anomaly.

    Args:
        anomaly: A dict from detect_anomalies() with keys:
            type, severity, description, details, row_indices.

    Returns:
        A dict with:
            - explanation: str (the LLM-generated text)
            - anomaly_type: str
            - status: "success" or "error"
    """
    anomaly_type = anomaly.get("type", "unknown")
    severity = anomaly.get("severity", "unknown")
    description = anomaly.get("description", "No description provided.")
    details = anomaly.get("details", {})
    row_indices = anomaly.get("row_indices", [])

    prompt = EXPLANATION_PROMPT.format(
        anomaly_type=anomaly_type,
        severity=severity,
        description=description,
        details=_format_details(details),
        row_indices=row_indices,
    )

    try:
        llm = get_ollama_client()
        explanation = llm.generate(prompt, temperature=0.4, max_output_tokens=512)
        return {
            "explanation": explanation.strip(),
            "anomaly_type": anomaly_type,
            "status": "success",
        }
    except Exception as e:
        return {
            "explanation": f"Could not generate explanation: {e}",
            "anomaly_type": anomaly_type,
            "status": "error",
        }


def _format_details(details: dict) -> str:
    """Format the details dict into a readable string for the prompt."""
    if not details:
        return "No additional details."
    lines = []
    for key, value in details.items():
        # Convert nested dicts/lists to readable strings
        if isinstance(value, dict):
            inner = ", ".join(f"{k}: {v}" for k, v in value.items())
            lines.append(f"  {key}: {inner}")
        elif isinstance(value, list):
            lines.append(f"  {key}: {value}")
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)
