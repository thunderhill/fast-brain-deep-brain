"""Measure the fast brain honestly (every email judged by a memory that never saw it) and pick the threshold.

Usage: ~/laya-env/bin/python eval.py
Writes cache/eval.json and prints the numbers you are allowed to quote on stage.
"""
import json
import statistics

from fastbrain import ROOT, URGENCY, FastBrain, load_inbox

items = load_inbox()
brain = FastBrain()
fold_of, memories = brain.fold_memories(items)
results = [(it, brain.triage(it, memories[fold_of[it["id"]]])) for it in items]

ok = [it["department"] == d["department"] for it, d in results]
print(f"Department accuracy, out-of-fold ({len(items)} emails): {statistics.mean(ok):.3f}")
for diff in ("easy", "ambiguous"):
    sub = [o for o, (it, _) in zip(ok, results) if it["difficulty"] == diff]
    print(f"  {diff:<9} ({len(sub)}): {statistics.mean(sub):.3f}")
urg = statistics.mean(abs(URGENCY.index(it["urgency"]) - d["urgency_score"]) <= 1 for it, d in results)
print(f"Urgency within one level: {urg:.3f}")
lat = sorted(d["latency_ms"] for _, d in results[5:])
print(f"Latency per email (embed + memory + urgency): p50 {lat[len(lat) // 2]:.0f} ms, p90 {lat[int(len(lat) * .9)]:.0f} ms")

print("\nthreshold  handled-instantly  accuracy-of-those  escalated-to-Claude")
table, suggested = [], None
for th in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
    auto = [o for o, (_, d) in zip(ok, results) if d["confidence"] >= th]
    acc = statistics.mean(auto) if auto else None
    table.append({"threshold": th, "auto": len(auto) / len(items), "accuracy": acc})
    print(f"   {th:.1f}         {len(auto) / len(items):6.1%}            {acc or 0:6.1%}            {1 - len(auto) / len(items):6.1%}")
    if suggested is None and acc is not None and acc >= 0.90:
        suggested = th
print(f"\nSuggested threshold (first with >=90% accuracy on handled emails): {suggested}")
(ROOT / "cache" / "eval.json").write_text(json.dumps({"suggested_threshold": suggested or 0.7, "table": table}, indent=1))
