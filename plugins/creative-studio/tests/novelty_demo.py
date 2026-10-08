#!/usr/bin/env python3
"""Run the novelty filter on the test fixtures and print outcome vs expectation.

    python3 tests/novelty_demo.py              # needs fastembed (or: uv run --with fastembed tests/novelty_demo.py)
    python3 tests/novelty_demo.py --backend lexical   # degraded mode, for comparison
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--home", help="state dir with a cached model (default: a temp dir, downloads the model)")
    args = ap.parse_args()
    home = args.home or tempfile.mkdtemp(prefix="cs-demo-")
    cmd = [sys.executable, str(ROOT / "scripts" / "novelty_check.py"), "--home", home, "--backend", args.backend,
           "--domain", "lyrics", "--pool", str(FIX / "novelty_pool.json"), "--baseline", str(FIX / "baseline.json"),
           "--history-file", str(FIX / "history.jsonl")]
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    pool = {c["id"]: c for c in json.loads((FIX / "novelty_pool.json").read_text(encoding="utf-8"))["concepts"]}
    rows = []
    for k in out["kept"]:
        near = k.get("nearest") or {}
        rows.append((k["id"], "soft" if k["soft_flag"] else "kept", near.get("ref_id"), near.get("sim"),
                     "; ".join(f"{w['ref_id']}" for w in k["line_warnings"]) or ""))
    for f in out["filtered"]:
        rows.append((f["id"], f["reason_code"], f["match"]["ref_id"], f["match"]["sim"], f["reason"][:90]))
    print(f"backend: {out['backend']} ({out['model']}), degraded={out['degraded']}, thresholds={out['thresholds']}")
    print(f"references: {out['references']}, counts: {out['counts']}\n")
    print(f"{'concept':<14} {'outcome':<15} {'ok':<3} {'match':<14} {'cos':<6} note")
    good = 0
    for cid, outcome, ref, sim, note in sorted(rows, key=lambda r: list(pool).index(r[0])):
        ok = outcome in pool[cid]["accept"]
        good += ok
        print(f"{cid:<14} {outcome:<15} {'✓' if ok else '✗':<3} {str(ref):<14} {str(sim):<6} {note}")
    print(f"\n{good}/{len(pool)} outcomes acceptable (see 'accept' in tests/fixtures/novelty_pool.json)")
    return 0 if good == len(pool) else 1


if __name__ == "__main__":
    sys.exit(main())
