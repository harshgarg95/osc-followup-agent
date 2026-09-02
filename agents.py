"""The four agent node functions for the OSC FollowUp graph.

Each node takes the LeadState, performs one focused job using a Groq LLM, appends
a structured entry to state["agent_log"] for visibility, and returns the updated
state. The supervisor classifies and routes; the three workers (qualifier,
drafter, reviewer) handle the downstream pipeline.
"""

import json
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

import config
from config import GROQ_MODEL
from state import LeadState

# Business context shared by every agent so messaging stays on-brand.
OSC_CONTEXT = (
    "Om Sales Corporation (OSC) is a Hyderabad-based distributor of building and "
    "interior materials: plywood, laminates, WPC boards, and acrylic surfaces. "
    "OSC sells primarily B2B to interior designers, contractors, furniture "
    "manufacturers, modular kitchen studios, and architects."
)


def _llm(temperature: float = 0.3, model: str = None) -> ChatGroq:
    """Build a ChatGroq client. The API key is read from the GROQ_API_KEY env var."""
    return ChatGroq(model=model or config.GROQ_MODEL, temperature=temperature)


# --------------------------------------------------------------------------- #
# Model resilience + rate-limit pacing
# --------------------------------------------------------------------------- #
_last_call_at = 0.0


def _models() -> list:
    """Primary, then fallback, then any other model Groq currently serves."""
    models = [config.GROQ_MODEL]
    if config.GROQ_FALLBACK_MODEL and config.GROQ_FALLBACK_MODEL not in models:
        models.append(config.GROQ_FALLBACK_MODEL)
    try:
        for extra in config.available_chat_models():
            if extra not in models:
                models.append(extra)
    except Exception:
        pass
    return models


def _is_rate_limit(exc: Exception) -> bool:
    return "rate_limit" in str(exc).lower() or type(exc).__name__ == "RateLimitError"


def _is_model_unavailable(exc: Exception) -> bool:
    """True for a retired/inaccessible model (Groq returns HTTP 404)."""
    if type(exc).__name__ in ("NotFoundError", "BadRequestError"):
        return True
    text = str(exc).lower()
    return any(m in text for m in (
        "model_not_found", "does not exist", "decommissioned",
        "has been deprecated", "error code: 404", "model_decommissioned",
    ))


def _is_api_error(exc: Exception) -> bool:
    """Generic transport/server-side failure worth retrying on another model."""
    if type(exc).__name__ in (
        "APIError", "APIStatusError", "APIConnectionError", "APITimeoutError",
        "InternalServerError", "ServiceUnavailableError",
    ):
        return True
    text = str(exc).lower()
    return any(m in text for m in ("error code: 5", "timeout", "connection error"))


def _retry_after(exc: Exception) -> float:
    """Seconds Groq asks us to wait, parsed from the 429 body; default 20s."""
    m = re.search(r"try again in ([\d.]+)\s*(ms|s)\b", str(exc), re.I)
    if m:
        val = float(m.group(1))
        return val / 1000.0 if m.group(2).lower() == "ms" else val
    return 20.0


def _pace() -> None:
    """Space calls out so a batch does not slam the free-tier TPM ceiling."""
    global _last_call_at
    gap = config.MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call_at)
    if gap > 0:
        time.sleep(gap)
    _last_call_at = time.time()


def _invoke(messages, temperature: float = 0.3):
    """Invoke Groq with pacing, rate-limit backoff and multi-model failover.

    Previously each node called ``_invoke(...)`` directly, so a retired
    model (404) or a free-tier rate limit (429) killed the whole graph mid-run.
    """
    attempts = []
    for model in _models():
        for attempt in range(config.MAX_RATE_LIMIT_RETRIES):
            try:
                _pace()
                return _llm(temperature=temperature, model=model).invoke(messages)
            except Exception as exc:
                if _is_rate_limit(exc):
                    wait = min(_retry_after(exc) + 1.0, 60.0)
                    if attempt < config.MAX_RATE_LIMIT_RETRIES - 1:
                        time.sleep(wait)
                        continue
                    attempts.append(f"{model}: rate-limited after "
                                    f"{config.MAX_RATE_LIMIT_RETRIES} attempts")
                    break
                if _is_model_unavailable(exc) or _is_api_error(exc):
                    attempts.append(f"{model}: {type(exc).__name__} {str(exc)[:90]}")
                    break
                raise
    raise RuntimeError(
        "Every Groq model candidate failed. Tried:\n  - "
        + "\n  - ".join(attempts or ["(no models resolved)"])
    )


def _log(state: LeadState, agent: str, action: str, output: str) -> None:
    """Append a structured, human-readable step to the agent log."""
    state.setdefault("agent_log", []).append(
        {"agent": agent, "action": action, "output": output}
    )


def _extract_json(text: str):
    """Best-effort extraction of a JSON object from an LLM response."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


def _lead_block(lead: dict) -> str:
    return (
        f"Name: {lead.get('name', 'Unknown')}\n"
        f"Type/business: {lead.get('type', 'Unknown')}\n"
        f"Area: {lead.get('area', 'Unknown')}\n"
        f"About: {lead.get('about', '(no description)')}"
    )


# ---------------------------------------------------------------------------
# 1. Supervisor — classify + route
# ---------------------------------------------------------------------------
def _parse_classification(text: str):
    data = _extract_json(text)
    if isinstance(data, dict):
        c = str(data.get("classification", "")).strip().lower()
        reason = str(data.get("reason", "")).strip()
        if c in ("hot", "nurture", "unqualified"):
            return c, reason or "No reason provided."
    # Fallback: scan keywords if the model didn't return clean JSON.
    low = (text or "").lower()
    for candidate in ("unqualified", "hot", "nurture"):
        if candidate in low:
            return candidate, (text or "").strip()[:300]
    return "nurture", "Defaulted to nurture (could not parse supervisor output)."


def supervisor_node(state: LeadState) -> LeadState:
    """Classify the lead into hot / nurture / unqualified and record the reason."""
    lead = state["lead"]
    system = SystemMessage(
        content=(
            f"You are the SUPERVISOR agent for OSC. {OSC_CONTEXT}\n\n"
            "Classify each incoming lead into exactly one bucket:\n"
            "- hot: strong fit and a likely near-term buyer of OSC materials "
            "(e.g. interior designers, active contractors on live projects, "
            "furniture/modular-kitchen makers).\n"
            "- nurture: plausible future fit but no immediate buying signal "
            "(e.g. general contractors, architects exploring, small builders).\n"
            "- unqualified: poor fit or unrelated business (e.g. restaurants, "
            "IT services, anything with no use for plywood/laminates/WPC/acrylic).\n\n"
            'Respond ONLY with compact JSON: '
            '{"classification": "hot|nurture|unqualified", "reason": "<one sentence>"}'
        )
    )
    human = HumanMessage(content=_lead_block(lead))
    response = _invoke([system, human])
    classification, reason = _parse_classification(response.content)

    state["classification"] = classification
    state["classification_reason"] = reason
    _log(
        state,
        "supervisor",
        "classify_lead",
        f"Classified as {classification.upper()} — {reason}",
    )
    return state


# ---------------------------------------------------------------------------
# 2. Qualifier — BANT (hot leads only)
# ---------------------------------------------------------------------------
def qualifier_node(state: LeadState) -> LeadState:
    """Produce a BANT-style qualification for a hot lead."""
    lead = state["lead"]
    system = SystemMessage(
        content=(
            f"You are the QUALIFIER agent for OSC. {OSC_CONTEXT}\n\n"
            "The supervisor flagged this lead as HOT. Produce a concise BANT-style "
            "qualification. Give one line each for:\n"
            "- Budget: signals they can purchase materials at project scale.\n"
            "- Authority: are they a likely decision-maker / buyer?\n"
            "- Need: specific OSC products they likely need "
            "(plywood, laminates, WPC, acrylic surfaces).\n"
            "- Timeline: how soon they might buy.\n"
            "Infer reasonably from the lead info; write 'Unknown' where there is no "
            "signal. Keep it tight (max ~4 short lines). Do not invent specific "
            "numbers."
        )
    )
    human = HumanMessage(
        content=(
            f"{_lead_block(lead)}\n\n"
            f"Supervisor reason: {state.get('classification_reason', '')}"
        )
    )
    response = _invoke([system, human])
    qualification = response.content.strip()

    state["qualification"] = qualification
    _log(state, "qualifier", "bant_assessment", qualification)
    return state


# ---------------------------------------------------------------------------
# 3. Drafter — outreach message
# ---------------------------------------------------------------------------
def drafter_node(state: LeadState) -> LeadState:
    """Draft a personalised follow-up message tailored to the lead."""
    lead = state["lead"]
    classification = state.get("classification", "nurture")

    if classification == "hot":
        guidance = (
            "This is a HOT lead. Reference the qualification below and propose a "
            "concrete next step (a quick call or sharing a product/price catalogue). "
            "Tie OSC products to their likely project needs."
        )
        context = f"Qualification:\n{state.get('qualification', '')}"
    else:
        guidance = (
            "This is a NURTURE lead. Write a warm, value-based touch — introduce OSC "
            "and how its materials could help their work, with a soft, no-pressure "
            "invitation to stay in touch. Do not hard-sell."
        )
        context = f"Supervisor reason: {state.get('classification_reason', '')}"

    system = SystemMessage(
        content=(
            f"You are the OUTREACH DRAFTER agent for OSC. {OSC_CONTEXT}\n\n"
            f"{guidance}\n\n"
            "Write a short, personalised follow-up message (WhatsApp/email friendly, "
            "120-160 words). Address the lead by name. Introduce the relevant OSC "
            "products (plywood, laminates, WPC, acrylic surfaces) tailored to their "
            "likely needs. Professional and friendly, never pushy. Do NOT promise "
            "specific prices, discounts, or delivery dates. Sign off as 'Team OSC, "
            "Om Sales Corporation'. Output only the message text."
        )
    )
    human = HumanMessage(content=f"{_lead_block(lead)}\n\n{context}")
    response = _invoke([system, human])
    draft = response.content.strip()

    state["draft_message"] = draft
    _log(state, "drafter", "draft_outreach", draft)
    return state


# ---------------------------------------------------------------------------
# 4. Reviewer — QA gate
# ---------------------------------------------------------------------------
def _parse_review(text: str):
    data = _extract_json(text)
    if isinstance(data, dict):
        passed = data.get("passed")
        if isinstance(passed, str):
            passed = passed.strip().lower() in ("true", "yes", "pass", "passed", "ok")
        feedback = str(data.get("feedback", "")).strip()
        return bool(passed), feedback or "No feedback provided."
    low = (text or "").lower()
    passed = ("pass" in low or "approved" in low) and "fail" not in low
    return passed, (text or "").strip()[:500]


def reviewer_node(state: LeadState) -> LeadState:
    """Review the draft for tone, accuracy, and personalisation."""
    system = SystemMessage(
        content=(
            f"You are the REVIEWER agent for OSC. {OSC_CONTEXT}\n\n"
            "Review the outreach draft against three criteria:\n"
            "1. Tone — professional and friendly, NOT pushy or salesy.\n"
            "2. Accuracy — no overpromising on pricing, discounts, or delivery.\n"
            "3. Personalisation — clearly tailored to this specific lead.\n\n"
            "Fail the draft if it is pushy, makes specific price/delivery promises, "
            "or is generic. Otherwise pass it.\n"
            'Respond ONLY with compact JSON: '
            '{"passed": true|false, "feedback": "<what works and any required fixes>"}'
        )
    )
    human = HumanMessage(
        content=(
            f"Lead:\n{_lead_block(state['lead'])}\n\n"
            f"Draft message:\n{state.get('draft_message', '')}"
        )
    )
    response = _invoke([system, human])
    passed, feedback = _parse_review(response.content)

    state["review_result"] = feedback
    state["review_passed"] = passed
    _log(
        state,
        "reviewer",
        "qa_review",
        f"{'PASS' if passed else 'FAIL'} — {feedback}",
    )
    return state
