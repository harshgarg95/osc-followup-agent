"""Shared LangGraph state for the OSC FollowUp multi-agent graph."""

from typing import TypedDict


class LeadState(TypedDict):
    lead: dict                 # name, type, area, contact, about
    classification: str        # "hot" | "nurture" | "unqualified"
    classification_reason: str
    qualification: str         # BANT-style assessment (empty if not hot)
    draft_message: str         # the outreach draft
    review_result: str         # reviewer feedback
    review_passed: bool
    status: str                # "pending_approval" | "escalated" | "no_action"
    agent_log: list            # list of {agent, action, output} for visibility
