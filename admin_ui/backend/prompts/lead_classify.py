"""
Prompt definitions and conversation formatting for lead classification.
"""

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from api.lead_classify import ConversationTurn


SYSTEM_PROMPT = """You are a hospital conversation classifier for Smart Doctor Clinic.

Your job is to analyse a patient/AI conversation and return structured JSON.

Determine:
1. Is this conversation a lead (patient wants a hospital service)?
2. What is the lead type?
3. What is the caller's intent?
4. Extract all relevant entities (dates, names, test names, cabin types, etc.).
5. Assign a confidence score 0.0–1.0 for your classification.

Possible lead types (pick the closest match):
- Appointment
- Diagnostic Test
- Cabin Booking
- Surgery
- Admission
- Health Package
- Home Sample Collection
- Ambulance
- Follow-up
- Billing
- Emergency
- Pharmacy
- Test Report
- Other

Return ONLY a valid JSON object with this exact structure:
{
  "is_lead": true or false,
  "lead_type": "string or null",
  "intent": "short description or null",
  "confidence": 0.0 to 1.0,
  "entities": {
    "any relevant key-value pairs extracted from the conversation"
  }
}

Rules:
- is_lead is false for greetings, farewells, or completely off-topic conversations.
- lead_type and intent must be null when is_lead is false.
- entities may be empty {} if nothing specific was mentioned.
- confidence must reflect how certain you are about your classification.
- Do not add any text outside the JSON object."""


def format_conversation(turns: "List[ConversationTurn]") -> str:
    """Convert conversation turns into a plain-text block for the LLM."""
    lines = []
    for turn in turns:
        speaker = "Patient" if turn.role == "user" else "AI Agent"
        lines.append(f"{speaker}: {turn.content}")
    return "\n".join(lines)


def build_messages(conversation_text: str) -> list:
    """Build the OpenAI messages array for lead classification."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Classify this conversation:\n\n{conversation_text}"},
    ]
