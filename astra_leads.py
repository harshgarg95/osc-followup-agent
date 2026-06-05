"""AstraDB data access for OSC FollowUp.

Reads leads from the existing `osc_prospects` collection and persists generated
follow-up records (with approval status) to a new `osc_followups` collection.

All functions degrade gracefully: connection/read errors are caught and surfaced
as empty results or raised with a clear message, so the Streamlit UI never hard
crashes on a transient DB hiccup.
"""

import uuid
from datetime import datetime, timezone

from astrapy import DataAPIClient

from config import (
    ASTRA_DB_ENDPOINT,
    ASTRA_DB_TOKEN,
    FOLLOWUP_COLLECTION,
    PROSPECTS_COLLECTION,
)

# Common field-name variants we map onto our canonical lead schema. The exact
# shape of osc_prospects can vary, so we look across several likely keys.
_NAME_KEYS = ("name", "business_name", "company", "title", "prospect_name")
_TYPE_KEYS = ("type", "business_type", "category", "segment", "industry")
_AREA_KEYS = ("area", "location", "city", "region", "address")
_CONTACT_KEYS = ("contact", "phone", "mobile", "email", "contact_number")
_ABOUT_KEYS = ("about", "description", "notes", "summary", "details")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    """Return a connected AstraDB Database handle."""
    if not ASTRA_DB_TOKEN or not ASTRA_DB_ENDPOINT:
        raise RuntimeError(
            "AstraDB credentials missing. Set ASTRA_DB_TOKEN and ASTRA_DB_ENDPOINT."
        )
    client = DataAPIClient(ASTRA_DB_TOKEN)
    return client.get_database(ASTRA_DB_ENDPOINT)


def _first(doc: dict, keys) -> str:
    for key in keys:
        value = doc.get(key)
        if value:
            return str(value)
    return ""


def _normalise_lead(doc: dict) -> dict:
    """Map a raw prospect document onto the canonical lead dict."""
    return {
        "name": _first(doc, _NAME_KEYS) or "Unknown",
        "type": _first(doc, _TYPE_KEYS),
        "area": _first(doc, _AREA_KEYS),
        "contact": _first(doc, _CONTACT_KEYS),
        "about": _first(doc, _ABOUT_KEYS),
    }


def get_prospects(limit: int = 20):
    """Read up to `limit` leads from osc_prospects. Returns [] on any error/empty."""
    try:
        db = _db()
        collection = db.get_collection(PROSPECTS_COLLECTION)
        leads = []
        for doc in collection.find({}, limit=limit):
            leads.append(_normalise_lead(doc))
        return leads
    except Exception as exc:  # noqa: BLE001 - surface gracefully to the UI
        print(f"[astra_leads] get_prospects error: {exc}")
        return []


def _ensure_followups(db):
    """Return the followups collection, creating it (non-vector) if missing."""
    try:
        existing = db.list_collection_names()
    except Exception:
        existing = []
    if FOLLOWUP_COLLECTION not in existing:
        # A plain (non-vector) collection — these are records, not embeddings.
        db.create_collection(FOLLOWUP_COLLECTION)
    return db.get_collection(FOLLOWUP_COLLECTION)


def save_followup(lead: dict, final_state: dict) -> str:
    """Persist a follow-up record and return its id."""
    db = _db()
    collection = _ensure_followups(db)
    record = {
        # Own string _id so approve/reject filters match cleanly (astrapy 2.x
        # may otherwise return UUID objects that don't match string filters).
        "_id": str(uuid.uuid4()),
        "lead": lead,
        "name": lead.get("name"),
        "classification": final_state.get("classification"),
        "classification_reason": final_state.get("classification_reason"),
        "qualification": final_state.get("qualification"),
        "draft_message": final_state.get("draft_message"),
        "review_result": final_state.get("review_result"),
        "review_passed": final_state.get("review_passed"),
        "status": final_state.get("status"),
        "agent_log": final_state.get("agent_log"),
        "created_at": _now_iso(),
    }
    collection.insert_one(record)
    return record["_id"]


def get_followups(status: str = None):
    """Read follow-up records, optionally filtered by status. Newest first."""
    try:
        db = _db()
        collection = _ensure_followups(db)
        query = {"status": status} if status else {}
        docs = []
        for doc in collection.find(query):
            doc["_id"] = str(doc.get("_id"))
            docs.append(doc)
        docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return docs
    except Exception as exc:  # noqa: BLE001
        print(f"[astra_leads] get_followups error: {exc}")
        return []


def update_followup_status(followup_id: str, new_status: str) -> bool:
    """Approve / reject a queued draft by updating its status. Returns success."""
    try:
        db = _db()
        collection = _ensure_followups(db)
        collection.update_one(
            {"_id": followup_id},
            {"$set": {"status": new_status, "updated_at": _now_iso()}},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[astra_leads] update_followup_status error: {exc}")
        return False
