"""Central configuration for OSC FollowUp.

Loads environment variables (locally from a .env file, on Streamlit Cloud from
the Secrets manager which are injected as env vars) and exposes the model name
and collection names used throughout the app.
"""

import os

from dotenv import load_dotenv

# Load .env when present (no-op on Streamlit Cloud, where secrets are env vars).
load_dotenv()

# --- Credentials -----------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ASTRA_DB_TOKEN = os.getenv("ASTRA_DB_TOKEN")
ASTRA_DB_ENDPOINT = os.getenv("ASTRA_DB_ENDPOINT")

# --- Model -----------------------------------------------------------------
# NOTE: the original spec requested "llama-3.1-70b-versatile", but that model
# was decommissioned by Groq. We default to the current supported 70B model and
# allow an env override so this keeps working as Groq's catalog evolves.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- AstraDB collections ---------------------------------------------------
# Existing collection of leads/prospects (read-only for this app).
PROSPECTS_COLLECTION = "osc_prospects"

# New collection that stores generated follow-up records + approval status.
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
