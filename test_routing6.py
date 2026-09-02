"""Routing-accuracy test: six labeled leads through the FollowUp graph.

Complements test_local.py (which checks the routing contract on 3 canonical
leads) by measuring classification accuracy on a wider labeled set. Runs the
leads back-to-back with NO client-side pacing in the harness, so it also
exercises the rate-limit handling in agents.py.
"""
import json
import time

from graph import run_followup

CASES = [
    {"expected": "hot", "lead": {
        "name": "Kalyan Modular Kitchens", "type": "Modular Kitchen Manufacturer",
        "area": "Kondapur, Hyderabad", "contact": "",
        "about": "Modular kitchen and wardrobe manufacturer with a 12,000 sq ft workshop. "
                 "Currently executing 9 flat interiors for a new gated community and buying "
                 "plywood carcass material and decorative laminates every month."}},
    {"expected": "hot", "lead": {
        "name": "Vertex Fitout Solutions", "type": "Interior Fit-out Contractor",
        "area": "Gachibowli, Hyderabad", "contact": "",
        "about": "Commercial fit-out contractor mid-way through a 40,000 sq ft office interior "
                 "handover in December. Actively sourcing WPC panels and acrylic sheets and "
                 "unhappy with their current supplier's lead times."}},
    {"expected": "nurture", "lead": {
        "name": "Bhoomi Architects", "type": "Architecture Firm",
        "area": "Banjara Hills, Hyderabad", "contact": "",
        "about": "Boutique architecture practice focused on concept and schematic design. "
                 "They specify materials but the contractor procures. No live project at "
                 "material-selection stage right now."}},
    {"expected": "nurture", "lead": {
        "name": "Sai Nirman Developers", "type": "Real Estate Developer",
        "area": "Kompally, Hyderabad", "contact": "",
        "about": "Residential developer that has just acquired land for a 120-unit apartment "
                 "project. Construction expected to begin next financial year; interiors are "
                 "at least 18 months away."}},
    {"expected": "unqualified", "lead": {
        "name": "Trinity IT Staffing", "type": "IT Recruitment Agency",
        "area": "Madhapur, Hyderabad", "contact": "",
        "about": "Technology staffing and recruitment consultancy placing software engineers "
                 "with product companies. Operates from a leased office."}},
    {"expected": "unqualified", "lead": {
        "name": "SmileWell Dental Clinic", "type": "Dental Clinic",
        "area": "Ameerpet, Hyderabad", "contact": "",
        "about": "Two-chair dental practice offering orthodontics and implants. No construction, "
                 "interior or manufacturing activity."}},
]

EXPECTED_AGENTS = {
    "hot": ["supervisor", "qualifier", "drafter", "reviewer"],
    "nurture": ["supervisor", "drafter", "reviewer"],
    "unqualified": ["supervisor"],
}


def main() -> int:
    rows, correct, path_ok = [], 0, 0
    t_start = time.time()
    for c in CASES:
        t0 = time.time()
        final = run_followup(c["lead"])
        dt = round(time.time() - t0, 1)

        got = final.get("classification", "")
        agents = [s["agent"] for s in final.get("agent_log", [])]
        hit = got == c["expected"]
        pok = agents == EXPECTED_AGENTS.get(got, [])
        correct += hit
        path_ok += pok

        rows.append({"name": c["lead"]["name"], "expected": c["expected"], "got": got,
                     "match": hit, "agents": agents, "path_ok": pok,
                     "status": final.get("status"), "runtime": dt,
                     "reason": final.get("classification_reason", "")[:160]})
        print(f"{'OK  ' if hit else 'MISS'} {c['lead']['name'][:30]:32} "
              f"exp={c['expected']:12} got={got:12} status={final.get('status'):16} {dt}s")
        print(f"      agents={agents} pathOK={pok}")
        print(f"      reason: {rows[-1]['reason']}\n")

    n = len(CASES)
    print("=" * 74)
    print(f"CLASSIFICATION ACCURACY : {correct}/{n} = {100 * correct / n:.0f}%")
    print(f"ROUTING PATH CORRECT    : {path_ok}/{n} = {100 * path_ok / n:.0f}%")
    print(f"TOTAL WALL TIME         : {time.time() - t_start:.1f}s "
          f"(no harness pacing; agents.py handles rate limits)")
    with open("routing6_results.json", "w") as fh:
        json.dump(rows, fh, indent=2)
    return 0 if correct == n and path_ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
