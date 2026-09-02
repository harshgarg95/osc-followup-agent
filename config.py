"""Central configuration for OSC FollowUp.

Loads environment variables (locally from a .env file, on Streamlit Cloud from
the Secrets manager which are injected as env vars) and exposes the model name
and collection names used throughout the app.

Model selection is RESOLVED AT RUNTIME against Groq's live catalogue. Groq
retires models on a rolling basis -- llama-3.1-70b, then llama-3.3-70b and
llama-3.1-8b-instant have all been delisted -- which used to hard-crash this app
with an HTTP 404 on the very first supervisor call. We now ask /v1/models what
actually exists and pick from a preference list.
"""

import os

from dotenv import load_dotenv

# Load .env when present (no-op on Streamlit Cloud, where secrets are env vars).
load_dotenv()

# --- Credentials -----------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ASTRA_DB_TOKEN = os.getenv("ASTRA_DB_TOKEN")
ASTRA_DB_ENDPOINT = os.getenv("ASTRA_DB_ENDPOINT")

# --- Model resolution ------------------------------------------------------
PREFERRED_PRIMARY = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]

PREFERRED_FALLBACK = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
]

_NON_CHAT = ("whisper", "orpheus", "prompt-guard", "tts", "embed", "safeguard")

_STATIC_PRIMARY_DEFAULT = "openai/gpt-oss-120b"
_STATIC_FALLBACK_DEFAULT = "openai/gpt-oss-20b"

_model_cache = None


def available_chat_models(force: bool = False) -> list:
    """Return the chat-capable model ids Groq currently serves.

    Network failures are non-fatal: we return [] and callers fall back to the
    static defaults, so the app degrades instead of crashing at import time.
    """
    global _model_cache
    if _model_cache is not None and not force:
        return _model_cache
    ids = []
    try:
        import groq

        client = groq.Groq(api_key=GROQ_API_KEY)
        for m in client.models.list().data:
            mid = getattr(m, "id", "")
            if not mid or any(p in mid.lower() for p in _NON_CHAT):
                continue
            ids.append(mid)
    except Exception:
        ids = []
    _model_cache = sorted(ids)
    return _model_cache


def _pick(preferences: list, catalogue: list, exclude: str = "") -> str:
    for name in preferences:
        if name in catalogue and name != exclude:
            return name
    for name in catalogue:
        if name != exclude:
            return name
    return ""


def resolve_models() -> tuple:
    """Resolve (primary, fallback) against the live catalogue.

    An explicit GROQ_MODEL / GROQ_FALLBACK_MODEL env var always wins.
    """
    catalogue = available_chat_models()

    # An explicit override wins, but ONLY if Groq still serves it. A stale pin in
    # .env (e.g. a since-retired llama-3.3-70b-versatile) must not resurrect the
    # 404 this whole mechanism exists to prevent.
    primary = os.getenv("GROQ_MODEL", "")
    if primary and catalogue and primary not in catalogue:
        primary = ""
    if not primary:
        primary = _pick(PREFERRED_PRIMARY, catalogue) or _STATIC_PRIMARY_DEFAULT

    fallback = os.getenv("GROQ_FALLBACK_MODEL")
    if fallback and catalogue and fallback not in catalogue:
        fallback = None
    if fallback is None:
        fallback = _pick(PREFERRED_FALLBACK, catalogue, exclude=primary)
        if not fallback:
            fallback = "" if primary == _STATIC_FALLBACK_DEFAULT else _STATIC_FALLBACK_DEFAULT
    return primary, fallback


GROQ_MODEL, GROQ_FALLBACK_MODEL = resolve_models()

# --- Rate limiting ---------------------------------------------------------
# Groq's free tier caps tokens-per-minute (8k TPM at time of writing). This app
# makes up to 4 LLM calls per lead, so a batch run will trip that ceiling. These
# control the client-side pacing and retry behaviour in agents.py.
MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("OSC_MIN_CALL_INTERVAL", "1.5"))
MAX_RATE_LIMIT_RETRIES = int(os.getenv("OSC_MAX_RETRIES", "5"))

# --- AstraDB collections ---------------------------------------------------
PROSPECTS_COLLECTION = "osc_prospects"
FOLLOWUP_COLLECTION = "osc_followups"


def missing_credentials():
    """Return a list of credential names that are not set (for friendly UI warnings)."""
    missing = []
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not ASTRA_DB_TOKEN:
        missing.append("ASTRA_DB_TOKEN")
    if not ASTRA_DB_ENDPOINT:
        missing.append("ASTRA_DB_ENDPOINT")
    return missing
