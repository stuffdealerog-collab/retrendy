#!/usr/bin/env python3
"""SessionStart hook: prepare the state directory, export CS_HOME for Bash
commands, and load the brand + taste profile into context when they are filled.

Empty templates load nothing but one status line: the studio then works in
neutral mode and must not invent an identity.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_common as cs  # noqa: E402


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    home = cs.ensure_home(cs.resolve_home(cwd=data.get("cwd")))
    cfg = cs.load_config(home)

    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with open(env_file, "a", encoding="utf-8") as fh:
            fh.write(f"export CS_HOME={shlex.quote(str(home))}\n")
            if data.get("session_id"):
                fh.write(f"export CS_SESSION={shlex.quote(str(data['session_id']))}\n")

    ident = cs.identity_context(home, cfg)
    packs = ", ".join(f"{d['slug']} ({d['status']})" for d in cs.list_domains())
    if ident["neutral"]:
        text = (f"[creative-studio] neutral mode: no brand or taste profile configured, so do not invent one. "
                f"Domain packs: {packs}. State: {home}")
    else:
        limit = int(cfg.get("session_context", {}).get("max_chars", 6000))
        parts = [f"[creative-studio] identity loaded from {home}. Apply it to creative work in this session "
                 f"(it overrides generic defaults, never the user's explicit brief). Domain packs: {packs}."]
        if ident["brand"]:
            parts.append(f"## Active brand: {ident['brand_name']}\n{ident['brand']}")
        if ident["taste"]:
            parts.append(f"## Taste profile (user-written)\n{ident['taste']}")
        if ident["taste_journal"]:
            parts.append(f"## Taste learned from past choices\n{ident['taste_journal']}")
        text = "\n\n".join(parts)
        if len(text) > limit:
            text = text[: limit - 80].rstrip() + f"\n…[truncated; full files in {home}]"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break session start
        cs.warn(f"session_context failed: {type(exc).__name__}: {exc}")
        sys.exit(0)
