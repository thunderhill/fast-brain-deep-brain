"""Fill cache/claude.json with Claude's answer for every inbox email, so replay mode works offline.

Usage: ~/laya-env/bin/python -m app.prewarm   (uses your Claude Pro login; ~120 short calls)
"""
import asyncio
import os

os.environ.setdefault("CLAUDE_MODE", "live")

from app.server import ask_claude, claude_cache, items  # noqa: E402


async def main():
    todo = [it for it in items if it["id"] not in claude_cache]
    print(f"{len(todo)} emails to ask Claude about ({len(claude_cache)} already cached)")
    for i, answer in enumerate(await asyncio.gather(*(ask_claude(it) for it in todo)), 1):
        if "error" in answer:
            print(answer["error"])
    print(f"cached: {len(claude_cache)}")


asyncio.run(main())
