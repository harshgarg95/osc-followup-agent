"""LangGraph wiring for the OSC FollowUp multi-agent system.

Topology:

    supervisor ──(hot)──────► qualifier ──► drafter ──► reviewer ──► END
        │  (nurture)─────────────────────────► drafter ──► reviewer ──► END
        └──(unqualified)────────────────────────────────────────────► END

After the graph runs, run_followup() sets the final status:
    - unqualified                      -> "no_action"
    - review passed                    -> "pending_approval"
    - hot/nurture but review failed    -> "escalated"
"""

from langgraph.graph import END, StateGraph

from agents import drafter_node, qualifier_node, reviewer_node, supervisor_node
from state import LeadState


def _route_from_supervisor(state: LeadState) -> str:
    """Conditional router keyed on the supervisor's classification."""
    classification = state.get("classification")
    if classification == "hot":
        return "qualifier"
    if classification == "nurture":
        return "drafter"
    return "unqualified"  # unqualified -> straight to END


def build_graph():
    """Construct and compile the StateGraph (synchronous, for reliability)."""
    graph = StateGraph(LeadState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("qualifier", qualifier_node)
    graph.add_node("drafter", drafter_node)
    graph.add_node("reviewer", reviewer_node)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "qualifier": "qualifier",   # hot
            "drafter": "drafter",       # nurture
            "unqualified": END,         # unqualified
        },
    )
    graph.add_edge("qualifier", "drafter")
    graph.add_edge("drafter", "reviewer")
    graph.add_edge("reviewer", END)

    return graph.compile()


# Compile once at import time and reuse.
_COMPILED = build_graph()


def _initial_state(lead: dict) -> LeadState:
    return LeadState(
        lead=lead,
        classification="",
        classification_reason="",
        qualification="",
        draft_message="",
        review_result="",
        review_passed=False,
        status="",
        agent_log=[],
    )


def run_followup(lead: dict) -> LeadState:
    """Run a single lead through the full graph and return the final state."""
    final = _COMPILED.invoke(_initial_state(lead))

    # Decide the queue status from the outcome.
    if final.get("classification") == "unqualified":
        final["status"] = "no_action"
    elif final.get("review_passed"):
        final["status"] = "pending_approval"
    else:
        # A hot or nurture draft that failed QA needs a human to look at it.
        final["status"] = "escalated"

    return final
