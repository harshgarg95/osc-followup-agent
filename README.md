# OSC FollowUp — Multi-Agent Lead Orchestration

A **LangGraph** multi-agent system that follows up on sales leads for **Om Sales
Corporation (OSC)** — a distributor of plywood, laminates, WPC boards, and
acrylic surfaces. A **supervisor** agent classifies each lead and routes it to
worker agents. Every outreach draft is **queued for human approval — nothing is
ever auto-sent.**

## Architecture

```
supervisor ──(hot)──────► qualifier ──► drafter ──► reviewer ──► END
    │  (nurture)─────────────────────────► drafter ──► reviewer ──► END
    └──(unqualified)────────────────────────────────────────────► END
```

| Agent | Role |
|-------|------|
| **supervisor** | Classifies the lead: `hot` / `nurture` / `unqualified`, and routes. |
| **qualifier** | (hot only) BANT-style assessment — Budget, Authority, Need, Timeline. |
| **drafter** | Writes a personalised follow-up referencing OSC products. |
| **reviewer** | QA gate — tone, accuracy (no price/delivery overpromising), personalisation. |

**Final status:** `pending_approval` (passed review) · `escalated` (failed review) ·
`no_action` (unqualified).

## Stack
- LangGraph · langchain-groq (Groq LLM) · astrapy (AstraDB) · Streamlit

## Data
- Reads leads from the AstraDB `osc_prospects` collection.
- Writes follow-up records + approval status to `osc_followups` (auto-created).

## Run locally
```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in GROQ_API_KEY, ASTRA_DB_TOKEN, ASTRA_DB_ENDPOINT
python test_local.py   # sanity-check routing on 3 sample leads
streamlit run app.py
```

## Configuration
Set via `.env` locally or Streamlit **Secrets** in the cloud:

```
GROQ_API_KEY = "..."
ASTRA_DB_TOKEN = "AstraCS:..."
ASTRA_DB_ENDPOINT = "https://....apps.astra.datastax.com"
```

> Model: defaults to `llama-3.3-70b-versatile` (the originally-specced
> `llama-3.1-70b-versatile` was decommissioned by Groq). Override with `GROQ_MODEL`.

## Human-in-the-loop
The system **never sends messages**. Approved drafts are only marked *ready to
send* for a person to dispatch from the Approval Queue.
