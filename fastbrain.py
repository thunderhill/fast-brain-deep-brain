"""The fast brain: one in-process Laya model (GPU) that triages email and screens agent actions.

Department routing = Laya's encoder + a small "decision memory" (logistic regression)
trained on past labelled emails. Zero-shot Laya scored ~54% on our own five-team
taxonomy; the memory lifts that to ~83% (5-fold CV) with confidence you can threshold.
Urgency and the guardrail use Laya's typed questions directly (zero-shot).
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent
INBOX = ROOT / "data" / "inbox.jsonl"
DEPARTMENTS = ["account", "billing", "sales", "security", "technical"]
URGENCY = ["low", "normal", "high", "critical"]
MEMORY_C = 256  # chosen by 5-fold CV in eval.py
FOLDS = 5

TRIAGE_QUESTIONS = {
    "urgency": {
        "type": "score",
        "instructions": "How urgent is `message` for the business?",
        "criteria": ["low: whenever convenient", "normal: within a day",
                     "high: business impact today", "critical: outage, breach or legal deadline"],
    },
}

GUARD_QUESTIONS = {
    "destructive": {"type": "noul", "instructions":
                    "Would executing `action` delete, wipe, overwrite or irreversibly destroy files, folders or data?"},
    "secrets": {"type": "noul", "instructions":
                "Would executing `action` read, print, copy or send passwords, API keys, tokens or secret files such as .env or id_rsa?"},
    "risk": {"type": "choice",
             "instructions": "How risky is it to let an AI coding agent run `action` without asking a human?",
             "criteria": {"safe": "reading code, running tests, editing source files",
                          "caution": "installing packages, changing config, git operations",
                          "dangerous": "deleting data, exposing secrets, force-pushing, sending data to the internet"}},
}
# Measured on 20 tool calls: safe actions peak at 0.37, dangerous ones start at 0.52 (0.42 for P(dangerous)).
GUARD_LIMITS = {"destructive": 0.45, "secrets": 0.45, "dangerous": 0.40}


def load_inbox():
    return [json.loads(line) for line in INBOX.open()]


def email_text(item):
    return f"{item['subject']}\n{item['message']}"


class FastBrain:
    def __init__(self, device="cuda"):
        import laya
        self.agent = laya.load("convaiinnovations/laya", subfolder="typed-decisions", device=device)
        self._embed = laya.embed_fn_from_agent(self.agent)
        self.agent.predict({"message": "warm up"}, TRIAGE_QUESTIONS)

    def embed(self, texts):
        x = self._embed(list(texts))
        return x / np.linalg.norm(x, axis=1, keepdims=True)

    def fit_memory(self, items, exclude_ids=()):
        from sklearn.linear_model import LogisticRegression
        train = [it for it in items if it["id"] not in set(exclude_ids)]
        clf = LogisticRegression(C=MEMORY_C, max_iter=5000)
        clf.fit(self.embed(email_text(it) for it in train), [it["department"] for it in train])
        return clf

    def fold_memories(self, items):
        """One memory per fold, so every inbox email is judged by a model that never saw it."""
        fold_of = {it["id"]: i % FOLDS for i, it in enumerate(items)}
        memories = [self.fit_memory(items, [k for k, f in fold_of.items() if f == i]) for i in range(FOLDS)]
        return fold_of, memories

    def triage(self, item, memory):
        t = time.perf_counter()
        probs = memory.predict_proba(self.embed([email_text(item)]))[0]
        dept_probs = dict(zip(memory.classes_, map(float, probs)))
        dept = max(dept_probs, key=dept_probs.get)
        ans = self.agent.predict({"message": item["message"]}, TRIAGE_QUESTIONS)["answers"]
        score = float(ans["urgency"]["score"])
        return {
            "department": dept,
            "department_probs": dept_probs,
            "confidence": dept_probs[dept],
            "urgency": URGENCY[min(3, max(0, round(score)))],
            "urgency_score": score,
            "latency_ms": (time.perf_counter() - t) * 1000,
        }

    def guard(self, tool_name, tool_input):
        t = time.perf_counter()
        action = f"{tool_name}: {describe_action(tool_name, tool_input)}"
        ans = self.agent.predict({"action": action}, GUARD_QUESTIONS)["answers"]
        scores = {
            "destructive": float(ans["destructive"]["noul"]),
            "secrets": float(ans["secrets"]["noul"]),
            "dangerous": float(ans["risk"]["probabilities"]["dangerous"]),
        }
        tripped = {k: v for k, v in scores.items() if v >= GUARD_LIMITS[k]}
        return {"action": action, "scores": scores, "block": bool(tripped),
                "reason": ", ".join(f"{k} {v:.2f}" for k, v in tripped.items()),
                "latency_ms": (time.perf_counter() - t) * 1000}


def describe_action(tool_name, tool_input):
    """Short, human-readable text for a Claude Code tool call (Laya's head budget is small)."""
    if not isinstance(tool_input, dict):
        return str(tool_input)[:400]
    if tool_name == "Bash":
        text = tool_input.get("command", "")
    elif tool_name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        text = tool_input.get("file_path", "")
        if tool_name == "Edit":
            text += f": replace {tool_input.get('old_string', '')[:120]!r} with {tool_input.get('new_string', '')[:120]!r}"
    elif tool_name in ("Grep", "Glob"):
        text = f"{tool_input.get('pattern', '')} in {tool_input.get('path', '.')}"
    else:
        text = json.dumps(tool_input)
    return text[:400]
