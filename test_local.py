"""Local routing test for the OSC FollowUp graph.

Runs three representative leads through run_followup() and prints the full agent
decision trail, classification, qualification, draft, and status for each. Then
asserts the routing contract:

  - hot         -> supervisor -> qualifier -> drafter -> reviewer  (4 agents)
  - nurture     -> supervisor -> drafter -> reviewer               (3 agents, no qualifier)
  - unqualified -> supervisor only                                 (1 agent), status no_action
"""

from graph import run_followup

SAMPLES = [
    {
        "label": "HOT",
        "lead": {
            "name": "Aarav Sharma Interiors",
            "type": "Interior Designer",
            "area": "Jubilee Hills, Hyderabad",
            "contact": "",
            "about": (
                "Boutique interior design studio currently executing three "
                "high-end residential projects. Frequently specs plywood, "
                "premium laminates and acrylic surfaces for modular work."
            ),
        },
    },
    {
        "label": "NURTURE",
        "lead": {
            "name": "Reddy & Sons Construction",
            "type": "General Contractor",
            "area": "Kukatpally, Hyderabad",
            "contact": "",
            "about": (
                "General civil contractor doing apartment construction. Occasional "
                "interior fit-out work but no active interior project right now."
            ),
        },
    },
    {
        "label": "UNQUALIFIED",
        "lead": {
            "name": "Spice Garden Restaurant",
            "type": "Restaurant",
            "area": "Gachibowli, Hyderabad",
            "contact": "",
            "about": "Family restaurant serving South Indian cuisine. No construction or interior business.",
        },
    },
]


def _print_trail(final):
    for i, step in enumerate(final.get("agent_log", []), start=1):
        print(f"  [{i}] {step['agent']:<11} | {step['action']}")
        out = step["output"].replace("\n", "\n              ")
        print(f"      -> {out}\n")


def main():
    summary = []
    for sample in SAMPLES:
        print("=" * 78)
        print(f"LEAD ({sample['label']}): {sample['lead']['name']}")
        print("=" * 78)
        final = run_followup(sample["lead"])

        print(f"Classification : {final['classification']}  "
              f"({final['classification_reason']})")
        print(f"Status         : {final['status']}")
        if final.get("qualification"):
            print(f"Qualification  :\n  {final['qualification']}")
        if final.get("draft_message"):
            print("Draft message  :")
            print("  " + final["draft_message"].replace("\n", "\n  "))
        print(f"Review passed  : {final['review_passed']}")
        if final.get("review_result"):
            print(f"Review notes   : {final['review_result']}")

        print("\nAGENT DECISION TRAIL:")
        _print_trail(final)

        agents_run = [s["agent"] for s in final.get("agent_log", [])]
        summary.append((sample["label"], final["classification"], agents_run,
                        final["status"]))

    # ---- Routing assertions ----
    print("=" * 78)
    print("ROUTING VERIFICATION")
    print("=" * 78)
    ok = True
    for label, classification, agents_run, status in summary:
        print(f"{label:<12} class={classification:<12} status={status:<16} "
              f"agents={agents_run}")
        if label == "HOT":
            ok &= agents_run == ["supervisor", "qualifier", "drafter", "reviewer"]
        elif label == "NURTURE":
            ok &= agents_run == ["supervisor", "drafter", "reviewer"]
            ok &= "qualifier" not in agents_run
        elif label == "UNQUALIFIED":
            ok &= agents_run == ["supervisor"]
            ok &= status == "no_action"

    print("-" * 78)
    print("ROUTING CONTRACT:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
