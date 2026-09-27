"""Control room: streams the inbox through the fast brain (Laya) and escalates unsure emails to Claude.

Run:  ~/laya-env/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
Env:  CLAUDE_MODE=live|replay   (replay = cached Claude answers only, works offline)
      CLAUDE_MODEL=sonnet       CLAUDE_CONCURRENCY=5
"""
import asyncio
import json
import os
import random
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse

from fastbrain import ROOT, FastBrain, load_inbox

STATIC = Path(__file__).parent / "static"
CLAUDE_CACHE = ROOT / "cache" / "claude.json"
CLAUDE_MODE = os.environ.get("CLAUDE_MODE", "live")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")
ITEMS_PER_SECOND = 5

app = FastAPI()
brain = FastBrain()
items = load_inbox()
fold_of, memories = brain.fold_memories(items)
state = {
    "threshold": json.loads((ROOT / "cache" / "eval.json").read_text()).get("suggested_threshold", 0.7)
    if (ROOT / "cache" / "eval.json").exists() else 0.7,
    "run": None,
}
subscribers: set[asyncio.Queue] = set()
claude_cache = json.loads(CLAUDE_CACHE.read_text()) if CLAUDE_CACHE.exists() else {}
claude_slots = asyncio.Semaphore(int(os.environ.get("CLAUDE_CONCURRENCY", "5")))

CLAUDE_PROMPT = """You are the senior support lead at Northwind Cloud (invoicing + analytics SaaS).
A fast triage model was unsure how to route this email. Decide.

Teams: billing, technical, sales, account (cancellation, access, users, data export), security (breach, phishing, fraud, compliance, legal).
Urgency: low, normal, high, critical.

From: {sender}
Subject: {subject}

{message}

Reply with ONLY a JSON object, no code fences:
{{"department": "...", "urgency": "...", "why": "<one sentence on what makes this tricky and your call>", "draft_reply": "<a reply to the customer, max 70 words>"}}"""


def publish(event: dict):
    for q in list(subscribers):
        q.put_nowait(event)


async def ask_claude(item: dict) -> dict:
    if CLAUDE_MODE == "replay":
        if item["id"] in claude_cache:
            await asyncio.sleep(random.uniform(1.0, 2.5))
            return {**claude_cache[item["id"]], "source": "replay"}
        return {"error": "no cached answer (run app.prewarm first)"}
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}  # use the Pro login
    prompt = CLAUDE_PROMPT.format(sender=item["from"], subject=item["subject"], message=item["message"])
    async with claude_slots:
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt, "--output-format", "json", "--tools", "", "--model", CLAUDE_MODEL,
                "--no-session-persistence", "--strict-mcp-config",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env, cwd=ROOT / "cache")
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
            raw = out.decode()
            envelope = json.loads(raw[raw.find("{"):])
            if envelope.get("is_error"):
                raise RuntimeError(envelope.get("result"))
            text = envelope["result"]
            answer = json.loads(text[text.find("{"):text.rfind("}") + 1])
            answer["duration_s"] = round(envelope.get("duration_ms", 0) / 1000, 1)
            claude_cache[item["id"]] = answer
            CLAUDE_CACHE.write_text(json.dumps(claude_cache, indent=1))
            return {**answer, "source": "live"}
        except Exception as e:  # noqa: BLE001 -- fall back to the cache so the show goes on
            if item["id"] in claude_cache:
                return {**claude_cache[item["id"]], "source": "replay"}
            return {"error": f"Claude call failed: {str(e)[:120]}"}


async def escalate(item: dict):
    answer = await ask_claude(item)
    publish({"type": "claude", "id": item["id"], "answer": answer})


async def run_inbox():
    loop = asyncio.get_running_loop()
    publish({"type": "start", "total": len(items), "threshold": state["threshold"]})
    pending = []
    for item in items:
        decision = await loop.run_in_executor(None, brain.triage, item, memories[fold_of[item["id"]]])
        escalated = decision["confidence"] < state["threshold"]
        publish({"type": "item", "item": {k: item[k] for k in ("id", "from", "subject", "message", "department", "urgency")},
                 "decision": decision, "escalated": escalated})
        if escalated:
            pending.append(asyncio.create_task(escalate(item)))
        await asyncio.sleep(1 / ITEMS_PER_SECOND)
    publish({"type": "sorted"})
    await asyncio.gather(*pending)
    publish({"type": "done"})


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def config():
    ev = ROOT / "cache" / "eval.json"
    return {"threshold": state["threshold"], "eval": json.loads(ev.read_text()) if ev.exists() else None,
            "claude_mode": CLAUDE_MODE}


@app.post("/api/run")
async def run():
    if state["run"] and not state["run"].done():
        return {"ok": False, "reason": "already running"}
    state["run"] = asyncio.create_task(run_inbox())
    return {"ok": True}


@app.post("/api/threshold")
async def threshold(request: Request):
    state["threshold"] = float((await request.json())["value"])
    return {"threshold": state["threshold"]}


@app.post("/api/guard")
async def guard(request: Request):
    body = await request.json()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, brain.guard, body.get("tool_name", ""), body.get("tool_input", {}))
    publish({"type": "guard", "mode": body.get("mode", "enforce"), **result})
    return result


@app.get("/api/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    subscribers.add(q)

    async def stream():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream")
