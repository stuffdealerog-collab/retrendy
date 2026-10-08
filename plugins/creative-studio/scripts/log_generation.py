#!/usr/bin/env python3
"""Generation log + taste-profile writer for creative-studio (stdlib only).

Hook entry points (stdin = hook JSON):
  log_generation.py hook-subagent-stop   SubagentStop: store ```cs:*``` blocks, log concepts
  log_generation.py hook-stop            Stop: store blocks (selection), reconcile statuses

Manual commands (same code paths, for fallbacks and inspection):
  log_generation.py ingest [--run R] [--agent NAME] < text-with-cs-blocks
  log_generation.py reconcile --run R
  log_generation.py select --run R --choice F2 --version bold --reason "..."
  log_generation.py tail [--n 20] [--domain D] [--status S]
  log_generation.py stats

generation-log.jsonl: one JSON object per concept, upserted by id:
  id, ts, run_id, domain, brief, title, logline, text, sample, strategy,
  operator, branch, agent, p, scores{...}, status, reason, version
  status: candidate -> filtered | rejected | finalist -> selected | rejected
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_common as cs  # noqa: E402

KINDS = {"concepts", "baseline", "trends", "review", "scores", "audience", "judgments", "versions", "selection"}


# --------------------------------------------------------------------- ingest

def brief_summary(brief: dict) -> str:
    parts = [brief.get("goal") or brief.get("raw") or ""]
    for key in ("audience", "constraints", "taboos"):
        value = brief.get(key)
        if value:
            parts.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
    return " | ".join(p for p in parts if p)[:400]


def store_blocks(home: Path, blocks: list[tuple[str, object]], agent: str = "", fallback_run: str | None = None) -> dict:
    """Persist cs:* blocks as run artifacts; concepts also go to the log as candidates.
    Idempotent: the artifact name contains a hash of its content."""
    summary: dict = {"stored": [], "logged": 0, "skipped": []}
    agent_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", agent or "main").strip("-") or "main"
    for kind, data in blocks:
        if kind not in KINDS or not isinstance(data, dict):
            summary["skipped"].append(kind)
            continue
        run_id = data.get("run_id") or fallback_run or cs.latest_run_id(home)
        if not run_id or not cs.run_dir(home, run_id).is_dir():
            summary["skipped"].append(f"{kind}: unknown run {run_id}")
            continue
        rdir = cs.run_dir(home, run_id)
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
        data = {**data, "run_id": run_id, "_agent": agent or data.get("_agent") or "main"}
        cs.write_json(rdir / "artifacts" / f"{kind}__{agent_slug}__{digest}.json", data)
        summary["stored"].append(f"{run_id}/{kind}")
        if kind == "concepts":
            summary["logged"] += log_concepts(home, run_id, data)
        elif kind == "selection":
            cs.write_json(rdir / "selection.json", data)
        elif kind == "trends":
            save_trend_snapshot(home, run_id, data)
    return summary


def concept_records(run_id: str, data: dict, brief: dict) -> list[dict]:
    rows = []
    for c in data.get("concepts") or []:
        if not isinstance(c, dict) or not (c.get("title") or c.get("concept")):
            continue
        body = c.get("concept") or c.get("text") or ""
        rows.append({
            "id": cs.concept_id(run_id, c.get("title", ""), body),
            "run_id": run_id,
            "domain": brief.get("domain") or "generic",
            "brief": brief_summary(brief),
            "title": c.get("title", ""),
            "logline": c.get("logline", ""),
            "text": body,
            "sample": c.get("sample", ""),
            "strategy": c.get("strategy") or data.get("strategy"),
            "operator": c.get("operator"),
            "branch": data.get("branch"),
            "agent": data.get("_agent"),
            "p": c.get("p"),
            "predictable": c.get("predictable"),
            "escalation": c.get("escalation"),
        })
    return rows


def log_concepts(home: Path, run_id: str, data: dict) -> int:
    brief = cs.read_json(cs.run_dir(home, run_id) / "brief.json", {}) or {}
    rows = concept_records(run_id, data, brief)
    for row in rows:
        row["status"] = "candidate"
        row["ts"] = cs.now_iso()
    return cs.upsert_log(home, rows)


def save_trend_snapshot(home: Path, run_id: str, data: dict) -> None:
    brief = cs.read_json(cs.run_dir(home, run_id) / "brief.json", {}) or {}
    day = cs.now_iso()[:10]
    name = f"{day}_{brief.get('domain', 'generic')}_{run_id}.json"
    cs.write_json(home / "trend-snapshots" / name, {"saved": cs.now_iso(), "domain": brief.get("domain"),
                                                     "brief": brief_summary(brief), **data})


# ------------------------------------------------------------------ reconcile

def _artifacts(rdir: Path, kind: str) -> list[dict]:
    return [cs.read_json(p, {}) or {} for p in sorted((rdir / "artifacts").glob(f"{kind}__*.json"))]


def reconcile(home: Path, run_id: str) -> dict:
    """Derive every concept's status/reason/scores from the run files and upsert the log."""
    rdir = cs.run_dir(home, run_id)
    brief = cs.read_json(rdir / "brief.json", {}) or {}
    pool = {c["id"]: c for c in (cs.read_json(rdir / "pool.json", []) or [])}
    for art in _artifacts(rdir, "concepts"):  # concepts not yet pooled still get logged
        for row in concept_records(run_id, art, brief):
            pool.setdefault(row["id"], {**row, "concept": row["text"]})
    updates: dict[str, dict] = {cid: {"id": cid, "run_id": run_id, "status": "candidate"} for cid in pool}

    novelty = cs.read_json(rdir / "novelty.json", {}) or {}
    for f in novelty.get("filtered", []):
        if f["id"] in updates:
            updates[f["id"]].update(status="filtered", reason=f"novelty/{f['reason_code']}: {f['reason']}")
    for k in novelty.get("kept", []):
        if k["id"] in updates:
            updates[k["id"]].setdefault("scores", {})["novelty_embed"] = k["novelty_embed"]

    survivors = cs.read_json(rdir / "survivors.json", {}) or {}
    for d in survivors.get("dropped", []):
        if d["id"] in updates:
            updates[d["id"]].update(status="filtered", reason=f"cliche-hunter: {d.get('reason', '')}")

    validated = cs.read_json(rdir / "scores.validated.json", {}) or {}
    for cid, sc in (validated.get("scores") or {}).items():
        if cid in updates:
            updates[cid].setdefault("scores", {}).update(sc.get("criteria", {}))
            updates[cid]["scores"]["rubric_total"] = sc.get("total")
            if sc.get("taboo_violation"):
                updates[cid].update(status="rejected", reason=f"taboo: {sc.get('taboo_note', '')}")

    ranking = cs.read_json(rdir / "ranking.json", {}) or {}
    finalists = {f["id"]: f for f in ranking.get("finalists", [])}
    if ranking:
        for row in ranking.get("ranked", []):
            cid = row["id"]
            if cid not in updates:
                continue
            sc = updates[cid].setdefault("scores", {})
            if row.get("winrate") is not None:
                sc["tournament_winrate"] = row["winrate"]
            sc["final"] = row.get("final")
            if cid in finalists:
                updates[cid].update(status="finalist", reason=f"finalist {finalists[cid]['label']}")
            elif updates[cid]["status"] == "candidate":
                updates[cid].update(status="rejected", reason=row.get("cut_reason") or "below the finalist cut")
        for u in updates.values():  # survived the filters but the critic never scored it
            if u["status"] == "candidate":
                u.update(status="rejected", reason="not scored by the critic")

    selection = cs.read_json(rdir / "selection.json", {}) or {}
    chosen_id = resolve_choice(selection, ranking)
    if selection:
        for cid, fin in finalists.items():
            if cid == chosen_id:
                updates[cid].update(status="selected", reason=f"user: {selection.get('reason', '')}".strip(),
                                    version=selection.get("version"))
            else:
                why = (selection.get("rejected") or {}).get(fin["label"]) or ""
                tail = f"user chose {selection.get('choice')}" if chosen_id else "user rejected all finalists"
                updates[cid].update(status="rejected", reason=f"{tail}" + (f": {why}" if why else f": {selection.get('reason', '')}"))
    changed = cs.upsert_log(home, list(updates.values()))
    counts = Counter(u["status"] for u in updates.values())
    state = cs.read_json(rdir / "state.json", {}) or {}
    state.update(reconciled_at=cs.now_iso(), status_counts=dict(counts))
    cs.write_json(rdir / "state.json", state)
    if selection and not selection.get("applied_at"):
        apply_taste(home, run_id, selection, chosen_id, finalists, pool)
        selection["applied_at"] = cs.now_iso()
        cs.write_json(rdir / "selection.json", selection)
    return {"run_id": run_id, "changed": changed, "statuses": dict(counts)}


def resolve_choice(selection: dict, ranking: dict) -> str | None:
    if not selection:
        return None
    if selection.get("id"):
        return selection["id"]
    label = str(selection.get("choice") or "").strip().upper()
    for fin in ranking.get("finalists", []):
        if fin["label"].upper() == label:
            return fin["id"]
    return None


# ---------------------------------------------------------------------- taste

JOURNAL = "<!-- cs:journal -->"
SIG_START, SIG_END = "<!-- cs:signals:start -->", "<!-- cs:signals:end -->"


def apply_taste(home: Path, run_id: str, selection: dict, chosen_id: str | None, finalists: dict, pool: dict) -> None:
    path = home / "taste-profile.md"
    if not path.exists():
        cs.ensure_home(home)
    text = path.read_text(encoding="utf-8") if path.exists() else f"# Taste profile\n\n<!-- cs:auto -->\n{JOURNAL}\n\n{SIG_START}\n{SIG_END}\n"
    if f"run {run_id}" in text:
        return  # already journaled
    brief = cs.read_json(cs.run_dir(home, run_id) / "brief.json", {}) or {}
    day = cs.now_iso()[:10]
    if chosen_id:
        fin = finalists.get(chosen_id, {})
        c = pool.get(chosen_id, {})
        head = (f"- {day} · {brief.get('domain', 'generic')} · run {run_id} · chose **{fin.get('label', '?')} "
                f"«{c.get('title', '?')}»** (version: {selection.get('version') or '—'}; "
                f"strategy: {c.get('strategy') or '—'}; operator: {c.get('operator') or '—'})")
    else:
        head = f"- {day} · {brief.get('domain', 'generic')} · run {run_id} · **rejected all finalists**"
    lines = [head, f"  - why: «{selection.get('reason', '').strip()}»"]
    for label, why in (selection.get("rejected") or {}).items():
        lines.append(f"  - not {label}: «{why}»")
    lines.append(f"  - brief: {brief_summary(brief)[:200]}")
    entry = "\n".join(lines)
    if JOURNAL not in text:
        text = text.rstrip() + f"\n\n<!-- cs:auto -->\n## Choice journal (auto)\n{JOURNAL}\n"
    text = text.replace(JOURNAL, f"{JOURNAL}\n{entry}", 1)
    text = replace_signals(text, derive_signals(home))
    cs.atomic_write(path, text)


def derive_signals(home: Path) -> str:
    rows = cs.read_jsonl(home / cs.LOG_NAME)
    chosen = [r for r in rows if r.get("status") == "selected"]
    if not chosen:
        return "_no choices yet_"
    shown = [r for r in rows if r.get("status") == "selected" or str(r.get("reason", "")).startswith("user ")]
    versions = Counter(r.get("version") or "—" for r in chosen)
    strategies = Counter(r.get("strategy") or "—" for r in chosen)
    nov = [r["scores"]["novelty_embed"] for r in chosen if isinstance((r.get("scores") or {}).get("novelty_embed"), (int, float))]
    out = [f"- choices so far: {len(chosen)} (out of {len(shown)} finalists shown)",
           "- preferred version: " + ", ".join(f"{k} ×{v}" for k, v in versions.most_common()),
           "- strategies behind chosen ideas: " + ", ".join(f"{k} ×{v}" for k, v in strategies.most_common(4))]
    if nov:
        out.append(f"- mean embedding novelty of chosen ideas: {sum(nov) / len(nov):.2f} (1 = far from every cliché and past idea)")
    reasons = [r.get("reason", "").removeprefix("user:").strip() for r in chosen[-5:]]
    out.append("- recent reasons: " + " / ".join(f"«{x[:120]}»" for x in reasons if x))
    return "\n".join(out)


def replace_signals(text: str, body: str) -> str:
    if SIG_START in text and SIG_END in text:
        pre, rest = text.split(SIG_START, 1)
        _, post = rest.split(SIG_END, 1)
        return f"{pre}{SIG_START}\n{body}\n{SIG_END}{post}"
    return text.rstrip() + f"\n\n## Derived signals (auto)\n{SIG_START}\n{body}\n{SIG_END}\n"


# ---------------------------------------------------------------------- hooks

def _read_hook_input() -> dict:
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def hook_subagent_stop() -> int:
    data = _read_hook_input()
    home = cs.ensure_home(cs.resolve_home(cwd=data.get("cwd")))
    texts = [data.get("last_assistant_message") or ""]
    blocks = [b for t in texts for b in cs.extract_blocks(t)]
    if not blocks:  # e.g. the report was delivered through a handback tool call
        blocks = [b for t in cs.texts_from_transcript(data.get("agent_transcript_path")) for b in cs.extract_blocks(t)]
    if blocks:
        result = store_blocks(home, blocks, agent=data.get("agent_type") or "")
        cs.warn(f"SubagentStop {data.get('agent_type')}: {result}")
    return 0


def hook_stop() -> int:
    data = _read_hook_input()
    home = cs.resolve_home(cwd=data.get("cwd"))
    if not (home / "runs").is_dir():
        return 0
    blocks = cs.extract_blocks(data.get("last_assistant_message") or "")
    runs = set()
    if blocks:
        result = store_blocks(home, blocks, agent="main")
        runs |= {s.split("/")[0] for s in result["stored"]}
    latest = cs.latest_run_id(home)
    if latest and _needs_reconcile(home, latest):
        runs.add(latest)
    for run_id in sorted(runs):
        cs.warn(f"Stop: {reconcile(home, run_id)}")
    return 0


def _needs_reconcile(home: Path, run_id: str) -> bool:
    rdir = cs.run_dir(home, run_id)
    state = rdir / "state.json"
    if not state.exists():
        return True
    stamp = state.stat().st_mtime
    return any(p.stat().st_mtime > stamp for p in rdir.rglob("*.json") if p.name != "state.json")


# ------------------------------------------------------------------------ cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook-subagent-stop")
    sub.add_parser("hook-stop")
    p = sub.add_parser("ingest"); p.add_argument("--run"); p.add_argument("--agent", default="manual")
    p.add_argument("--kind", help="treat stdin as one raw JSON block of this kind")
    p = sub.add_parser("reconcile"); p.add_argument("--run")
    p = sub.add_parser("select"); p.add_argument("--run"); p.add_argument("--choice", required=True)
    p.add_argument("--version"); p.add_argument("--reason", default=""); p.add_argument("--rejected", default="{}")
    p = sub.add_parser("tail"); p.add_argument("--n", type=int, default=20); p.add_argument("--domain"); p.add_argument("--status")
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    if args.cmd == "hook-subagent-stop":
        return hook_subagent_stop()
    if args.cmd == "hook-stop":
        return hook_stop()

    home = cs.ensure_home(Path(args.home).expanduser() if args.home else cs.resolve_home())
    if args.cmd == "ingest":
        text = sys.stdin.read()
        blocks = [(args.kind, json.loads(text))] if args.kind else cs.extract_blocks(text)
        print(cs.dump(store_blocks(home, blocks, agent=args.agent, fallback_run=args.run)))
    elif args.cmd == "reconcile":
        print(cs.dump(reconcile(home, args.run or cs.latest_run_id(home))))
    elif args.cmd == "select":
        run_id = args.run or cs.latest_run_id(home)
        sel = {"run_id": run_id, "choice": args.choice, "version": args.version, "reason": args.reason,
               "rejected": json.loads(args.rejected)}
        store_blocks(home, [("selection", sel)], agent="manual", fallback_run=run_id)
        print(cs.dump(reconcile(home, run_id)))
    elif args.cmd == "tail":
        rows = [r for r in cs.read_jsonl(home / cs.LOG_NAME)
                if (not args.domain or r.get("domain") == args.domain) and (not args.status or r.get("status") == args.status)]
        for r in rows[-args.n:]:
            print(json.dumps({k: r.get(k) for k in ("id", "ts", "run_id", "domain", "status", "strategy", "title", "reason")}, ensure_ascii=False))
    elif args.cmd == "stats":
        rows = cs.read_jsonl(home / cs.LOG_NAME)
        print(cs.dump({"home": str(home), "concepts": len(rows),
                       "runs": len({r.get("run_id") for r in rows}),
                       "by_status": dict(Counter(r.get("status") for r in rows)),
                       "by_domain": dict(Counter(r.get("domain") for r in rows))}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # hooks must never break the session
        cs.warn(f"log_generation failed: {type(exc).__name__}: {exc}")
        sys.exit(0 if len(sys.argv) > 1 and sys.argv[1].startswith("hook-") else 1)
