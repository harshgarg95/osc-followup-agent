"""OSC FollowUp — Streamlit UI for the multi-agent lead orchestration system.

Three tabs:
  1. Process Leads   — pull prospects (or enter one manually), run the graph,
                       and inspect the agent decision trail.
  2. Approval Queue  — review queued drafts and approve/reject them.
  3. Agent Activity  — summary metrics + an explanation of the architecture.

NOTHING is auto-sent. Every draft is queued for explicit human approval.
"""

import streamlit as st

import astra_leads
from config import GROQ_MODEL, missing_credentials
from graph import run_followup

st.set_page_config(
    page_title="OSC FollowUp - Multi-Agent Lead Orchestration",
    layout="wide",
)

# --- Session state ---------------------------------------------------------
if "prospects" not in st.session_state:
    st.session_state.prospects = []
if "results" not in st.session_state:
    st.session_state.results = []  # list of (lead, final_state)

# --- Header ----------------------------------------------------------------
st.title("OSC FollowUp - Multi-Agent Lead Orchestration")
st.caption(
    "A LangGraph supervisor classifies each lead and routes it to worker agents "
    "(qualifier → drafter → reviewer). Powered by Groq · "
    f"model `{GROQ_MODEL}`."
)
st.warning(
    "**Human-in-the-loop:** nothing is ever auto-sent. Every draft is queued in "
    "the Approval Queue and only a person can approve it.",
    icon="🛡️",
)

_missing = missing_credentials()
if _missing:
    st.error(
        "Missing credentials: "
        + ", ".join(_missing)
        + ". Set them in your `.env` (local) or Streamlit **Secrets** (cloud)."
    )

# --- Helpers ---------------------------------------------------------------
_BADGE = {
    "hot": ("🔥 HOT", "#d62728"),
    "nurture": ("🌱 NURTURE", "#2ca02c"),
    "unqualified": ("🚫 UNQUALIFIED", "#7f7f7f"),
}


def classification_badge(classification: str):
    label, color = _BADGE.get(
        classification, (classification.upper() if classification else "—", "#888")
    )
    st.markdown(
        f"<span style='background:{color};color:white;padding:3px 10px;"
        f"border-radius:12px;font-weight:600;font-size:0.85rem'>{label}</span>",
        unsafe_allow_html=True,
    )


def render_agent_trail(agent_log):
    """Render the supervisor → workers decision trail. This is the visibility core."""
    if not agent_log:
        st.info("No agent log recorded.")
        return
    order = {"supervisor": 1, "qualifier": 2, "drafter": 3, "reviewer": 4}
    for i, step in enumerate(agent_log, start=1):
        agent = step.get("agent", "?")
        action = step.get("action", "")
        output = step.get("output", "")
        num = order.get(agent, i)
        st.markdown(f"**Step {num} — `{agent}`** · _{action}_")
        st.write(output)
        if i < len(agent_log):
            st.markdown("&nbsp;&nbsp;&nbsp;⬇️", unsafe_allow_html=True)


def render_result(lead, final_state):
    cols = st.columns([3, 1])
    with cols[0]:
        st.subheader(lead.get("name", "Unknown"))
        st.caption(
            f"{lead.get('type', '—')} · {lead.get('area', '—')}"
        )
    with cols[1]:
        classification_badge(final_state.get("classification", ""))

    st.caption(f"Reason: {final_state.get('classification_reason', '')}")

    status = final_state.get("status", "")
    if status == "pending_approval":
        st.success("Status: queued for approval (pending_approval)")
    elif status == "escalated":
        st.error("Status: escalated (draft failed QA — needs a human)")
    else:
        st.info("Status: no action (unqualified)")

    if final_state.get("draft_message"):
        with st.expander("Drafted message"):
            st.write(final_state["draft_message"])

    with st.expander("🔎 Agent Decision Trail (supervisor → qualifier → drafter → reviewer)"):
        render_agent_trail(final_state.get("agent_log", []))


def process_lead(lead: dict):
    """Run one lead through the graph, persist it, and stash the result."""
    final_state = run_followup(lead)
    try:
        astra_leads.save_followup(lead, final_state)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Saved locally but could not write to AstraDB: {exc}")
    st.session_state.results.append((lead, final_state))
    return final_state


# --- Tabs ------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["Process Leads", "Approval Queue", "Agent Activity"])

# ===========================================================================
# TAB 1 — Process Leads
# ===========================================================================
with tab1:
    st.header("Process Leads")

    left, right = st.columns(2)

    with left:
        st.subheader("From the OSC database")
        if st.button("Load prospects from OSC database"):
            with st.spinner("Reading osc_prospects…"):
                st.session_state.prospects = astra_leads.get_prospects(limit=20)
            if not st.session_state.prospects:
                st.info(
                    "No prospects returned (collection empty or unreachable). "
                    "You can still use manual entry on the right."
                )

        if st.session_state.prospects:
            st.write(f"**{len(st.session_state.prospects)} prospects loaded:**")
            for lead in st.session_state.prospects:
                st.markdown(
                    f"- **{lead['name']}** — {lead.get('type', '—')}, "
                    f"{lead.get('area', '—')}"
                )
            if st.button("Run Follow-Up Orchestration on All", type="primary"):
                progress = st.progress(0.0)
                total = len(st.session_state.prospects)
                for idx, lead in enumerate(st.session_state.prospects, start=1):
                    with st.spinner(f"Orchestrating: {lead['name']} ({idx}/{total})"):
                        process_lead(lead)
                    progress.progress(idx / total)
                st.success(f"Processed {total} leads. See results below ⬇️")

    with right:
        st.subheader("Manual single lead")
        with st.form("manual_lead"):
            name = st.text_input("Name", placeholder="e.g. Aarav Interiors")
            ltype = st.text_input("Type", placeholder="e.g. Interior Designer")
            area = st.text_input("Area", placeholder="e.g. Jubilee Hills, Hyderabad")
            about = st.text_area(
                "About",
                placeholder="What do they do? Any project signals?",
            )
            submitted = st.form_submit_button("Run on this lead", type="primary")
        if submitted:
            if not name.strip():
                st.error("Please enter at least a name.")
            else:
                lead = {
                    "name": name.strip(),
                    "type": ltype.strip(),
                    "area": area.strip(),
                    "contact": "",
                    "about": about.strip(),
                }
                with st.spinner(f"Orchestrating: {lead['name']}…"):
                    process_lead(lead)
                st.success("Done. See result below ⬇️")

    # Results feed (most recent first)
    if st.session_state.results:
        st.divider()
        head = st.columns([4, 1])
        head[0].header("Results")
        if head[1].button("Clear results"):
            st.session_state.results = []
            st.rerun()
        for lead, final_state in reversed(st.session_state.results):
            with st.container(border=True):
                render_result(lead, final_state)

# ===========================================================================
# TAB 2 — Approval Queue
# ===========================================================================
with tab2:
    st.header("Approval Queue")
    st.caption("Approve a draft to mark it ready-to-send. Nothing leaves OSC automatically.")

    pending = astra_leads.get_followups("pending_approval")
    if not pending:
        st.info("No drafts pending approval right now.")
    else:
        st.write(f"**{len(pending)} draft(s) awaiting approval:**")
    for item in pending:
        with st.container(border=True):
            top = st.columns([3, 1])
            with top[0]:
                st.subheader(item.get("name", "Unknown"))
                st.caption(item.get("classification_reason", ""))
            with top[1]:
                classification_badge(item.get("classification", ""))

            st.markdown("**Drafted message**")
            st.write(item.get("draft_message", "(empty)"))

            if item.get("review_result"):
                st.markdown("**Reviewer notes**")
                st.caption(item["review_result"])

            buttons = st.columns(2)
            fid = item["_id"]
            if buttons[0].button("✅ Approve (ready to send)", key=f"approve_{fid}"):
                if astra_leads.update_followup_status(fid, "approved"):
                    st.success("Approved — marked ready to send.")
                    st.rerun()
            if buttons[1].button("❌ Reject", key=f"reject_{fid}"):
                if astra_leads.update_followup_status(fid, "rejected"):
                    st.warning("Rejected.")
                    st.rerun()

    # Escalated section
    st.divider()
    st.subheader("⚠️ Escalated")
    st.caption("Drafts that failed QA review — need a human to revise.")
    escalated = astra_leads.get_followups("escalated")
    if not escalated:
        st.info("Nothing escalated.")
    for item in escalated:
        with st.container(border=True):
            st.markdown(f"**{item.get('name', 'Unknown')}** — {item.get('classification', '')}")
            st.caption(f"Reason: {item.get('classification_reason', '')}")
            if item.get("qualification"):
                with st.expander("Qualification"):
                    st.write(item["qualification"])
            st.markdown("**Draft**")
            st.write(item.get("draft_message", "(empty)"))
            st.markdown("**Why it failed review**")
            st.caption(item.get("review_result", ""))

# ===========================================================================
# TAB 3 — Agent Activity
# ===========================================================================
with tab3:
    st.header("Agent Activity")

    all_followups = astra_leads.get_followups()
    total = len(all_followups)
    hot = sum(1 for f in all_followups if f.get("classification") == "hot")
    nurture = sum(1 for f in all_followups if f.get("classification") == "nurture")
    unqualified = sum(1 for f in all_followups if f.get("classification") == "unqualified")
    pending_n = sum(1 for f in all_followups if f.get("status") == "pending_approval")
    approved_n = sum(1 for f in all_followups if f.get("status") == "approved")
    escalated_n = sum(1 for f in all_followups if f.get("status") == "escalated")

    row1 = st.columns(4)
    row1[0].metric("Total processed", total)
    row1[1].metric("🔥 Hot", hot)
    row1[2].metric("🌱 Nurture", nurture)
    row1[3].metric("🚫 Unqualified", unqualified)

    row2 = st.columns(3)
    row2[0].metric("Pending approval", pending_n)
    row2[1].metric("Approved", approved_n)
    row2[2].metric("Escalated", escalated_n)

    st.divider()
    st.subheader("How the 4-agent architecture works")
    st.markdown(
        """
**Supervisor (router).** Reads each lead's type, area, and description and
classifies intent into **hot**, **nurture**, or **unqualified** — then routes
accordingly.

**Routing:**
- **hot** → `qualifier` → `drafter` → `reviewer`
- **nurture** → `drafter` → `reviewer` (skips qualification)
- **unqualified** → ends immediately (no draft, status `no_action`)

**Worker agents:**
1. **Qualifier** — for hot leads only, produces a BANT-style read
   (Budget, Authority, Need, Timeline).
2. **Outreach Drafter** — writes a personalised follow-up referencing OSC's
   products (plywood, laminates, WPC, acrylic surfaces).
3. **Reviewer** — QA gate for tone, accuracy (no price/delivery overpromising),
   and personalisation. Passing drafts go to **pending_approval**; failing
   hot/nurture drafts are **escalated**.

Every step is recorded in an **agent decision trail** (visible per lead in the
Process Leads tab), so you can see exactly which agent did what.

**Human-in-the-loop:** the system never sends anything. Approved drafts are
simply marked *ready to send* for a person to dispatch.
        """
    )
