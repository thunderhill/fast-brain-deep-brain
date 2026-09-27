#!/usr/bin/env python3
"""Claude Code PreToolUse hook: ask the local fast brain whether a tool call is safe before it runs.

Reads the hook payload on stdin, posts it to the control room (/api/guard), and denies the call
when Laya flags it. LAYA_GUARD_MODE=log only records what it would block (use for rehearsals).
If the control room is down it fails open with a warning; the deterministic deny rules in
.claude/settings.json still apply.
"""
import json
import os
import sys
import urllib.request

GUARD_URL = os.environ.get("LAYA_GUARD_URL", "http://127.0.0.1:8765/api/guard")
MODE = os.environ.get("LAYA_GUARD_MODE", "enforce")


def main():
    payload = json.load(sys.stdin)
    body = json.dumps({"tool_name": payload.get("tool_name", ""), "tool_input": payload.get("tool_input", {}),
                       "mode": MODE}).encode()
    try:
        req = urllib.request.Request(GUARD_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            verdict = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"laya-guard unavailable ({e}); falling back to static permission rules", file=sys.stderr)
        return 0
    if verdict["block"] and MODE == "enforce":
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Laya guardrail blocked this action ({verdict['reason']}). "
                                        "Do not retry it; explain the risk to the user and propose a safer alternative.",
        }}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
