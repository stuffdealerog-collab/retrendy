#!/usr/bin/env python3
"""Run orchestration CLI for creative-studio (stdlib only). Usually called as
`cstudio <command>` (bin/ is on PATH inside Claude Code sessions).

  init          create a run from a brief (JSON on stdin), draw operator cards
  context       compile runs/<id>/context.md for the generators
  pool          merge cs:concepts artifacts into pool.json (+ baseline.json)
  review-input  render novelty survivors for cliche-hunter
  survivors     apply cliche-hunter verdicts -> survivors.json, critique-input.md
  validate      check critic evidence quotes, compute rubric totals
  pairs         schedule the blind pairwise tournament -> pairs.md
  rank          combine rubric + tournament, pick diverse finalists -> finalists.md
  report        final markdown report for the user
  status        what exists for a run and what comes next
  draw          draw cards for an extra (refill) branch
  recent        memory digest of earlier concepts in a domain
  snapshots     recent trend snapshots (for degraded trend mode)
  bank-add      append an entry to the local cliché bank
  runs          list runs
  domains       list domain packs
  identity      brand / taste status; --init-brand NAME, --use-brand NAME|none
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import secrets
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_common as cs  # noqa: E402
import log_generation as lg  # noqa: E402

CRITERIA = ("novelty", "surprise", "usefulness", "brief_fit", "craft")
CARD_RE = re.compile(r"^###\s+([A-Z]+\d+)\s+(.+?)\s*$")


# ---------------------------------------------------------------------- utils

def home_and_cfg(args) -> tuple[Path, dict]:
    home = cs.ensure_home(Path(args.home).expanduser() if getattr(args, "home", None) else cs.resolve_home())
    return home, cs.load_config(home)


def need_run(home: Path, run_id: str | None) -> tuple[str, Path]:
    run_id = run_id or cs.latest_run_id(home)
    if not run_id or not cs.run_dir(home, run_id).is_dir():
        raise SystemExit(f"run not found: {run_id!r} (home: {home})")
    return run_id, cs.run_dir(home, run_id)


def out(obj) -> None:
    print(cs.dump(obj) if not isinstance(obj, str) else obj)


def as_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [s.strip() for s in re.split(r"[;\n]", str(value)) if s.strip()]


def render_concept(c: dict, extra: str = "") -> str:
    meta = " · ".join(str(x) for x in (c.get("branch") and f"branch {c['branch']}", c.get("strategy"), c.get("operator"),
                                        c.get("p") is not None and f"p={c.get('p')}") if x)
    parts = [f"### {c['id']} — {c.get('title', '')}", f"_{meta}_" if meta else "", f"**Logline:** {c.get('logline', '')}",
             "", c.get("concept") or c.get("text", "")]
    if c.get("sample"):
        parts += ["", "```text", c["sample"].strip(), "```"]
    if extra:
        parts += ["", extra]
    return "\n".join(p for p in parts if p is not None) + "\n"


# ---------------------------------------------------------------------- decks

def load_deck(name: str) -> list[dict]:
    path = cs.OPERATORS_DIR / f"{name}.md"
    if not path.exists():
        return []
    cards, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = CARD_RE.match(line)
        if m:
            cur = {"deck": name, "id": m.group(1), "title": m.group(2), "text": ""}
            cards.append(cur)
        elif line.startswith("## ") or line.startswith("# "):
            cur = None
        elif cur is not None:
            cur["text"] += line + "\n"
    for c in cards:
        c["text"] = c["text"].strip()
    return cards


def draw_cards(spec: dict, rng: random.Random, exclude_words: list[str]) -> list[dict]:
    drawn = []
    for deck, n in spec.items():
        cards = load_deck(deck)
        if deck == "foreign-domains" and exclude_words:
            low = [w.lower() for w in exclude_words]
            cards = [c for c in cards if not any(w in (c["title"] + " " + c["text"]).lower() for w in low)]
        drawn += rng.sample(cards, min(n, len(cards)))
    return drawn


# ------------------------------------------------------------------- commands

def cmd_init(args) -> None:
    home, cfg = home_and_cfg(args)
    raw = sys.stdin.read() if args.brief in (None, "-") else Path(args.brief).read_text(encoding="utf-8")
    try:
        brief = json.loads(raw)
    except json.JSONDecodeError:
        brief = {"raw": raw.strip(), "goal": raw.strip()}
    pack = cs.domain_pack(brief.get("domain") or "generic")
    brief.update(domain=pack["slug"], constraints=as_list(brief.get("constraints")), taboos=as_list(brief.get("taboos")))
    brief.setdefault("audience", "")
    brief.setdefault("language", "auto")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"r_{stamp}_{secrets.token_hex(2)}"
    rdir = cs.run_dir(home, run_id)
    (rdir / "artifacts").mkdir(parents=True, exist_ok=True)
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    exclude = as_list(pack["meta"].get("outsider_exclude"))
    branches = []
    for b in cfg["branches"]:
        branches.append({**{k: b[k] for k in ("id", "agent", "strategy", "label")}, "cards": draw_cards(b.get("draw", {}), rng, exclude)})
    pipe = cfg["pipeline"]
    brief["created"] = cs.now_iso()
    cs.write_json(rdir / "brief.json", brief)
    cs.write_json(rdir / "draw.json", {"seed": seed, "branches": branches})
    cs.write_json(rdir / "state.json", {"run_id": run_id, "created": brief["created"], "session": os.environ.get("CS_SESSION")})
    (cs.runs_dir(home) / "LATEST").write_text(run_id, encoding="utf-8")
    ident = cs.identity_context(home, cfg)
    digest = memory_digest(home, pack["slug"], run_id, pipe["memory_digest_size"])
    out({
        "run_id": run_id, "run_dir": str(rdir), "home": str(home),
        "domain": {"slug": pack["slug"], "pack": pack["status"], "files": pack["files"]},
        "mode": "neutral" if ident["neutral"] else "identity",
        "brand": ident["brand_name"], "taste_profile": bool(ident["taste"]), "taste_journal": bool(ident["taste_journal"]),
        "memory_digest_items": len(digest), "seed": seed,
        "branches": [{"id": b["id"], "agent": b["agent"], "strategy": b["strategy"], "label": b["label"],
                      "cards": [f"{c['id']} {c['title']}" for c in b["cards"]]} for b in branches],
        "pipeline": pipe,
        "next": "spawn trend-analyst + cliche-hunter(baseline) in parallel, then `cstudio context`",
    })


def memory_digest(home: Path, domain: str, run_id: str | None, n: int) -> list[str]:
    rows = [r for r in cs.read_jsonl(home / cs.LOG_NAME)
            if r.get("domain") == domain and r.get("run_id") != run_id and r.get("status") != "filtered"]
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return [f"- [{r.get('status')}] {r.get('title')}: {r.get('logline') or (r.get('text') or '')[:140]}" for r in rows[:n]]


def cmd_context(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    brief = cs.read_json(rdir / "brief.json", {})
    pack = cs.domain_pack(brief["domain"])
    ident = cs.identity_context(home, cfg)
    trends = [a for a in lg._artifacts(rdir, "trends")]
    baseline = baseline_items(rdir)
    digest = memory_digest(home, pack["slug"], run_id, cfg["pipeline"]["memory_digest_size"])
    md = [f"# Run context {run_id}", "", "## Brief", f"- domain: {pack['slug']} (pack: {pack['status']})",
          f"- goal: {brief.get('goal', '')}", f"- audience: {brief.get('audience') or 'not specified: assume a broad adult audience and say so'}",
          f"- constraints: {'; '.join(brief.get('constraints', [])) or 'none'}", f"- taboos: {'; '.join(brief.get('taboos', [])) or 'none'}",
          f"- language: {brief.get('language', 'auto')}"]
    if brief.get("raw"):
        md += ["", "Original brief text:", f"> {brief['raw']}"]
    md += ["", "## Identity"]
    if ident["neutral"]:
        md += ["Neutral studio mode: no brand and no taste profile are configured. Do not invent a brand voice, "
               "persona or audience preferences; judge ideas only against the brief."]
    else:
        if ident["brand"]:
            md += [f"### Brand: {ident['brand_name']}", ident["brand"]]
        if ident["taste"]:
            md += ["### Taste profile (written by the user)", ident["taste"]]
        if ident["taste_journal"]:
            md += ["### Learned from past choices", ident["taste_journal"]]
    md += ["", "## Trends and insights"]
    if trends:
        t = trends[-1]
        md += [f"Mode: **{t.get('mode', 'unknown')}**; sources: {', '.join(map(str, t.get('sources', []))) or 'n/a'}"]
        for s in t.get("signals", [])[:12]:
            md.append(f"- signal: {s.get('signal')} ({s.get('source', '?')}; {s.get('evidence', '')})".strip())
        for i, ins in enumerate(t.get("insights", []), 1):
            md.append(f"- insight I{i}: trend «{ins.get('trend')}» → need «{ins.get('need')}» → white space «{ins.get('white_space')}» "
                      f"→ counter-trend «{ins.get('counter_trend')}»")
    else:
        md += ["No trend artifact for this run: generate from the brief alone (evergreen mode)."]
    md += ["", "## Predictable answers: do NOT build concepts on these",
           "(pre-mortem by cliche-hunter + the domain's cliché bank; the novelty filter rejects anything within cos 0.8 of them)"]
    md += [f"- {x}" for x in baseline] or ["- (none yet)"]
    if pack["files"].get("cliche-bank"):
        md += [f"- …and every entry of {pack['files']['cliche-bank']}"]
    md += ["", "## Already generated in earlier runs: do NOT repeat or paraphrase"]
    md += digest or ["- (nothing yet: this is the first run in this domain)"]
    path = rdir / "context.md"
    cs.atomic_write(path, "\n".join(md) + "\n")
    out({"context": str(path), "chars": path.stat().st_size, "trend_mode": trends[-1].get("mode") if trends else "evergreen",
         "baseline_items": len(baseline), "memory_digest_items": len(digest), "neutral": ident["neutral"]})


def baseline_items(rdir: Path) -> list[str]:
    items = []
    for art in lg._artifacts(rdir, "baseline"):
        items += [x.get("text") if isinstance(x, dict) else x for x in art.get("items", [])]
    for art in lg._artifacts(rdir, "concepts"):
        items += [x.get("text") if isinstance(x, dict) else x for x in art.get("head", [])]
    seen, uniq = set(), []
    for x in items:
        if x and cs.norm_text(x) not in seen:
            seen.add(cs.norm_text(x))
            uniq.append(x)
    return uniq


def cmd_pool(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    brief = cs.read_json(rdir / "brief.json", {})
    pool, by_branch = {}, Counter()
    for art in lg._artifacts(rdir, "concepts"):
        for row in lg.concept_records(run_id, art, brief):
            if row["id"] not in pool:
                pool[row["id"]] = {"id": row["id"], "branch": row["branch"], "strategy": row["strategy"], "agent": row["agent"],
                                   "title": row["title"], "logline": row["logline"], "concept": row["text"], "sample": row["sample"],
                                   "operator": row["operator"], "p": row["p"], "predictable": row["predictable"],
                                   "escalation": row["escalation"]}
                by_branch[row["branch"] or "?"] += 1
    cs.write_json(rdir / "pool.json", list(pool.values()))
    base = baseline_items(rdir)
    cs.write_json(rdir / "baseline.json", {"items": base})
    expected = [b["id"] for b in (cs.read_json(rdir / "draw.json", {}) or {}).get("branches", [])]
    out({"pool": len(pool), "by_branch": dict(by_branch), "missing_branches": [b for b in expected if b not in by_branch],
         "baseline_items": len(base), "next": "cstudio novelty --run " + run_id})


def cmd_review_input(args) -> None:
    home, _ = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    nov = cs.read_json(rdir / "novelty.json")
    if not nov:
        raise SystemExit("novelty.json missing: run `cstudio novelty --run <id>` first")
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    md = [f"# Novelty survivors for review ({run_id})",
          f"Backend: {nov['backend']} ({nov['model']}){' — DEGRADED lexical mode' if nov.get('degraded') else ''}. "
          f"Kept {nov['counts']['kept']} of {nov['counts']['pool']}.", ""]
    for k in nov["kept"]:
        near = k.get("nearest") or {}
        notes = [f"embedding novelty {k['novelty_embed']}"]
        if near:
            notes.append(f"nearest: {near.get('source')} {near.get('ref_id')} «{near.get('text', '')[:80]}» cos {near.get('sim')}")
        if k.get("soft_flag"):
            notes.append("SOFT FLAG: close to a reference, check carefully")
        for w in k.get("line_warnings", []):
            notes.append(f"line warning: {w}")
        md.append(render_concept(pool[k["id"]], "> " + "\n> ".join(notes)))
    path = rdir / "review-input.md"
    cs.atomic_write(path, "\n".join(md))
    out({"review_input": str(path), "kept": len(nov["kept"]), "soft_flagged": nov["counts"]["soft_flagged"]})


def cmd_survivors(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    nov = cs.read_json(rdir / "novelty.json", {})
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    flags, proposals = {}, []
    for art in lg._artifacts(rdir, "review"):
        for f in art.get("flags", []):
            flags[f.get("id")] = f
        proposals += art.get("bank_proposals", [])
    kept, dropped = [], []
    for k in nov.get("kept", []):
        f = flags.get(k["id"]) or {}
        if f.get("verdict") == "cliche":
            dropped.append({"id": k["id"], "title": k["title"], "reason": f"{f.get('pattern', '')}: {f.get('reason', '')}".strip(": ")})
        else:
            kept.append(k["id"])
    cs.write_json(rdir / "survivors.json", {"kept": kept, "dropped": dropped, "bank_proposals": proposals})
    md = [f"# Concepts to critique ({run_id})", ""]
    for cid in kept:
        k = next(x for x in nov["kept"] if x["id"] == cid)
        note = f"> embedding novelty {k['novelty_embed']}"
        if flags.get(cid, {}).get("verdict") == "borderline":
            note += f"\n> cliche-hunter: borderline — {flags[cid].get('reason', '')}"
        md.append(render_concept(pool[cid], note))
    cs.atomic_write(rdir / "critique-input.md", "\n".join(md))
    if proposals:
        cs.atomic_write(rdir / "bank-proposals.md", "\n".join(f"- [{p.get('category', '?')}] {p.get('text')}" for p in proposals) + "\n")
    need = cfg["pipeline"]["min_survivors"]
    refill = len(kept) < need
    if refill:
        notes = ["# Why concepts were rejected in this run (avoid these failure modes)", ""]
        notes += [f"- «{f['title']}»: {f['reason']}" for f in nov.get("filtered", [])[:15]]
        notes += [f"- «{d['title']}»: cliche-hunter: {d['reason']}" for d in dropped[:10]]
        cs.atomic_write(rdir / "refill-notes.md", "\n".join(notes) + "\n")
    out({"survivors": len(kept), "dropped_by_cliche_hunter": len(dropped), "bank_proposals": len(proposals),
         "critique_input": str(rdir / "critique-input.md"), "refill_needed": refill, "min_survivors": need})


def _norm_quote(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»“”„\"'`’‘*_]", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:!?—-")


def evidence_ok(evidence: str, haystack: str) -> bool:
    frags = [f for f in (_norm_quote(x) for x in re.split(r"\.\.\.|…|\[…\]", evidence or "")) if len(f) >= 3]
    hay = _norm_quote(haystack)
    return bool(frags) and all(f in hay for f in frags)


def cmd_validate(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    rub = cfg["rubric"]
    lo, hi = rub["scale"]
    norm = lambda s: (max(lo, min(hi, float(s))) - lo) / (hi - lo)  # noqa: E731
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    nov = {k["id"]: k for k in (cs.read_json(rdir / "novelty.json", {}) or {}).get("kept", [])}
    survivors = set((cs.read_json(rdir / "survivors.json", {}) or {}).get("kept", []))
    scores = {}
    for art in lg._artifacts(rdir, "scores"):
        for s in art.get("scores", []):
            scores[s.get("id")] = s
    audience = {}
    for art in lg._artifacts(rdir, "audience"):
        for r in art.get("reactions", []):
            audience[r.get("id")] = r
    result, issues = {}, []
    for cid, s in scores.items():
        if cid not in pool:
            issues.append(f"{cid}: unknown concept id")
            continue
        c = pool[cid]
        hay = " ".join(str(c.get(k) or "") for k in ("title", "logline", "concept", "sample"))
        criteria, unsupported = {}, []
        for crit in CRITERIA:
            entry = s.get(crit) or {}
            val = entry.get("score") if isinstance(entry, dict) else entry
            if not isinstance(val, (int, float)):
                issues.append(f"{cid}: missing score for {crit}")
                val = lo
            ev = entry.get("evidence", "") if isinstance(entry, dict) else ""
            if not evidence_ok(ev, hay):
                unsupported.append(crit)
                val = max(lo, val - rub["unsupported_evidence_penalty"])
            criteria[crit] = val
        ne = (nov.get(cid) or {}).get("novelty_embed")
        nov_part = norm(criteria["novelty"])
        if isinstance(ne, (int, float)):
            nov_part = (1 - rub["embedding_novelty_blend"]) * nov_part + rub["embedding_novelty_blend"] * max(0.0, min(1.0, (ne - 0.2) / 0.4))
        w = rub["weights"]
        total = (w["novelty"] * nov_part + sum(w[c] * norm(criteria[c]) for c in CRITERIA if c != "novelty")) / sum(w.values())
        aud = audience.get(cid)
        if aud and isinstance(aud.get("resonance"), (int, float)):
            total = (1 - rub["audience_weight"]) * total + rub["audience_weight"] * norm(aud["resonance"])
        taboo = bool(s.get("taboo_violation"))
        result[cid] = {"criteria": criteria, "unsupported_evidence": unsupported, "total": round(0.0 if taboo else total, 4),
                       "taboo_violation": taboo, "taboo_note": s.get("taboo_note", ""), "audience": (aud or {}).get("resonance"),
                       "strongest": s.get("strongest"), "weakest": s.get("weakest")}
        if unsupported:
            issues.append(f"{cid}: evidence not found verbatim for {', '.join(unsupported)} (-{rub['unsupported_evidence_penalty']} each)")
    missing = sorted(survivors - set(result))
    cs.write_json(rdir / "scores.validated.json", {"scores": result, "issues": issues, "unscored": missing})
    ranked = sorted(result.items(), key=lambda kv: -kv[1]["total"])
    out({"scored": len(result), "unscored_survivors": missing, "evidence_issues": len([i for i in issues if "evidence" in i]),
         "issues": issues[:20], "top": [{"id": k, "title": pool[k]["title"], "total": v["total"]} for k, v in ranked[:8]]})


def cmd_pairs(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    val = (cs.read_json(rdir / "scores.validated.json", {}) or {}).get("scores", {})
    if not val:
        raise SystemExit("scores.validated.json missing: run `cstudio validate` first")
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    k = args.k or cfg["pipeline"]["tournament_size"]
    top = [cid for cid, v in sorted(val.items(), key=lambda kv: -kv[1]["total"]) if not v["taboo_violation"]][:k]
    rng = random.Random(f"{run_id}-pairs")
    pairs, as_a = [], Counter()
    combos = [(a, b) for i, a in enumerate(top) for b in top[i + 1:]]
    rng.shuffle(combos)
    for a, b in combos:  # balance first position to fight position bias
        if as_a[a] > as_a[b] or (as_a[a] == as_a[b] and rng.random() < 0.5):
            a, b = b, a
        as_a[a] += 1
        pairs.append({"pair": f"P{len(pairs) + 1:02d}", "A": a, "B": b})
    cs.write_json(rdir / "pairs.json", {"contestants": top, "pairs": pairs})
    md = [f"# Blind pairwise tournament ({run_id})", "",
          "For each pair decide which concept is the stronger answer to the brief overall. Scores are hidden on purpose.", ""]
    for p in pairs:
        md += [f"## {p['pair']}", "", "**A**", "", render_concept({**pool[p["A"]], "id": "A", "branch": None, "strategy": None, "operator": None, "p": None}),
               "**B**", "", render_concept({**pool[p["B"]], "id": "B", "branch": None, "strategy": None, "operator": None, "p": None}), "---"]
    cs.atomic_write(rdir / "pairs.md", "\n".join(md) + "\n")
    out({"contestants": len(top), "pairs": len(pairs), "pairs_md": str(rdir / "pairs.md")})


def cmd_rank(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    val = (cs.read_json(rdir / "scores.validated.json", {}) or {}).get("scores", {})
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    sched = cs.read_json(rdir / "pairs.json", {}) or {"pairs": [], "contestants": []}
    by_pair = {p["pair"]: p for p in sched["pairs"]}
    wins, games = defaultdict(float), Counter()
    for art in lg._artifacts(rdir, "judgments"):
        for j in art.get("judgments", []):
            p = by_pair.get(j.get("pair"))
            if not p:
                continue
            w = str(j.get("winner", "")).strip().upper()
            games[p["A"]] += 1
            games[p["B"]] += 1
            if w == "A":
                wins[p["A"]] += 1
            elif w == "B":
                wins[p["B"]] += 1
            else:
                wins[p["A"]] += 0.5
                wins[p["B"]] += 0.5
    tw = cfg["rubric"]["tournament_weight"]
    ranked = []
    for cid, v in val.items():
        wr = wins[cid] / games[cid] if games[cid] else None
        final = v["total"] if wr is None else (1 - tw) * v["total"] + tw * wr
        ranked.append({"id": cid, "title": pool.get(cid, {}).get("title"), "branch": pool.get(cid, {}).get("branch"),
                       "strategy": pool.get(cid, {}).get("strategy"), "rubric": v["total"],
                       "winrate": None if wr is None else round(wr, 3), "final": round(final, 4),
                       "in_tournament": cid in sched["contestants"]})
    ranked.sort(key=lambda r: (not r["in_tournament"], -r["final"]))
    # Diversity-aware pick (MMR on strategy): don't hand the user three variations of one move.
    lam, n = cfg["pipeline"]["finalist_diversity_lambda"], args.n or cfg["pipeline"]["finalists"]
    pool_c = [r for r in ranked if r["in_tournament"] and not val[r["id"]]["taboo_violation"]] or ranked
    chosen = []
    while pool_c and len(chosen) < n:
        best = max(pool_c, key=lambda r: lam * r["final"] - (1 - lam) * max(
            [1.0 if r["strategy"] == c["strategy"] else 0.0 for c in chosen] or [0.0]))
        chosen.append(best)
        pool_c.remove(best)
    finalists = [{"label": f"F{i}", **r} for i, r in enumerate(chosen, 1)]
    fin_ids = {f["id"] for f in finalists}
    for r in ranked:
        if r["id"] not in fin_ids:
            r["cut_reason"] = (f"tournament win rate {r['winrate']}, final {r['final']}" if r["in_tournament"]
                               else f"rubric {r['rubric']} below the tournament cut")
    cs.write_json(rdir / "ranking.json", {"ranked": ranked, "finalists": finalists})
    md = [f"# Finalists ({run_id})", ""]
    for f in finalists:
        v = val[f["id"]]
        md.append(render_concept(pool[f["id"]], f"> {f['label']}: rubric {f['rubric']}, win rate {f['winrate']}, "
                                                 f"criteria {v['criteria']}; strongest: {v.get('strongest')}; weakest: {v.get('weakest')}"))
    cs.atomic_write(rdir / "finalists.md", "\n".join(md))
    out({"finalists": [{k: f[k] for k in ("label", "id", "title", "strategy", "rubric", "winrate", "final")} for f in finalists],
         "finalists_md": str(rdir / "finalists.md")})


def cmd_report(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    brief = cs.read_json(rdir / "brief.json", {})
    pool = {c["id"]: c for c in cs.read_json(rdir / "pool.json", [])}
    nov = cs.read_json(rdir / "novelty.json", {}) or {}
    surv = cs.read_json(rdir / "survivors.json", {}) or {}
    val = (cs.read_json(rdir / "scores.validated.json", {}) or {}).get("scores", {})
    ranking = cs.read_json(rdir / "ranking.json", {}) or {}
    trends = lg._artifacts(rdir, "trends")
    versions = {}
    for art in lg._artifacts(rdir, "versions"):
        for f in art.get("finalists", []):
            versions[f.get("id") or f.get("label")] = f
    ident = cs.identity_context(home, cfg)
    md = [f"## creative-studio · run `{run_id}`", "",
          f"**Brief:** {brief.get('goal', '')} · domain `{brief.get('domain')}` · audience: {brief.get('audience') or '—'}",
          f"**Mode:** {'neutral (no brand / taste profile)' if ident['neutral'] else 'identity: brand ' + str(ident['brand_name'] or '—') + ', taste profile loaded'}"
          f" · trends: {(trends[-1].get('mode') if trends else 'evergreen')} · novelty backend: {nov.get('backend', '—')}"
          f"{' (DEGRADED lexical)' if nov.get('degraded') else ''}", "",
          "### Funnel",
          f"generated **{len(pool)}** → after novelty filter **{nov.get('counts', {}).get('kept', '—')}** "
          f"({', '.join(f'{k}: {v}' for k, v in nov.get('counts', {}).get('by_reason', {}).items()) or 'none filtered'}) → "
          f"after cliche-hunter **{len(surv.get('kept', [])) or '—'}** → scored **{len(val)}** → tournament "
          f"**{len((cs.read_json(rdir / 'pairs.json', {}) or {}).get('contestants', []))}** → finalists **{len(ranking.get('finalists', []))}**", ""]
    filtered = sorted(nov.get("filtered", []), key=lambda f: -(f.get("match") or {}).get("sim", 0))
    if filtered:
        md += ["### What the filters threw out (top by similarity)"]
        md += [f"- «{f['title']}» → {f['reason']}" for f in filtered[:6]]
        md += [f"- «{d['title']}» → cliche-hunter: {d['reason']}" for d in surv.get("dropped", [])[:3]]
        md.append("")
    md += ["### Finalists", "", "| | Concept | Strategy | Rubric | Win rate | Embedding novelty |", "|---|---|---|---|---|---|"]
    for f in ranking.get("finalists", []):
        ne = next((k["novelty_embed"] for k in nov.get("kept", []) if k["id"] == f["id"]), "—")
        md.append(f"| {f['label']} | {f['title']} | {f['strategy']} | {f['rubric']} | {f['winrate']} | {ne} |")
    md.append("")
    for f in ranking.get("finalists", []):
        c = pool[f["id"]]
        md += [f"#### {f['label']} · {c['title']}", f"_{c.get('logline', '')}_", ""]
        v = versions.get(f["id"]) or versions.get(f["label"])
        if not v:
            md += [c.get("concept", ""), ""]
            continue
        for key, label in (("safe", "Safe"), ("bold", "Bold"), ("director", "Director's cut")):
            ver = (v.get("versions") or {}).get(key)
            if not ver:
                continue
            md.append(f"**{label}: {ver.get('title', '')}**")
            for field in ("hook", "verse", "text"):
                if ver.get(field):
                    md += ["```text", ver[field].strip(), "```"]
            if ver.get("note"):
                md.append(f"_{ver['note']}_")
            md.append("")
    report = "\n".join(md)
    cs.atomic_write(rdir / "report.md", report + "\n")
    out(report)


def cmd_status(args) -> None:
    home, _ = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    arts = Counter(p.name.split("__")[0] for p in (rdir / "artifacts").glob("*.json"))
    files = {name: (rdir / name).exists() for name in ("context.md", "pool.json", "novelty.json", "survivors.json",
                                                        "scores.validated.json", "pairs.json", "ranking.json", "report.md", "selection.json")}
    steps = [("trends", arts["trends"]), ("baseline", arts["baseline"]), ("context.md", files["context.md"]),
             ("concepts", arts["concepts"]), ("pool.json", files["pool.json"]), ("novelty.json", files["novelty.json"]),
             ("review", arts["review"]), ("survivors.json", files["survivors.json"]), ("scores", arts["scores"]),
             ("scores.validated.json", files["scores.validated.json"]), ("pairs.json", files["pairs.json"]),
             ("judgments", arts["judgments"]), ("ranking.json", files["ranking.json"]), ("versions", arts["versions"]),
             ("report.md", files["report.md"]), ("selection", files["selection.json"])]
    nxt = next((name for name, ok in steps if not ok), "done")
    out({"run_id": run_id, "artifacts": dict(arts), "files": files, "next_missing": nxt,
         "state": cs.read_json(rdir / "state.json", {})})


def cmd_draw(args) -> None:
    home, cfg = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    like = next((b for b in cfg["branches"] if b["id"] == args.like), cfg["branches"][0])
    pack = cs.domain_pack((cs.read_json(rdir / "brief.json", {}) or {}).get("domain"))
    rng = random.Random(secrets.randbits(32))
    cards = draw_cards(like.get("draw", {}), rng, as_list(pack["meta"].get("outsider_exclude")))
    draw = cs.read_json(rdir / "draw.json", {"branches": []})
    branch = {"id": args.branch, "agent": like["agent"], "strategy": like["strategy"] + "-refill", "label": like["label"] + " (refill)", "cards": cards}
    draw["branches"] = [b for b in draw["branches"] if b["id"] != args.branch] + [branch]
    cs.write_json(rdir / "draw.json", draw)
    out({k: branch[k] for k in ("id", "agent", "strategy", "label")} | {"cards": [f"{c['id']} {c['title']}" for c in cards]})


def cmd_cards(args) -> None:
    home, _ = home_and_cfg(args)
    run_id, rdir = need_run(home, args.run)
    draw = cs.read_json(rdir / "draw.json", {"branches": []})
    for b in draw["branches"]:
        if b["id"] == args.branch:
            out("\n\n".join(f"### {c['id']} {c['title']}\n{c['text']}" for c in b["cards"]))
            return
    raise SystemExit(f"branch {args.branch} not in draw.json")


def cmd_recent(args) -> None:
    home, cfg = home_and_cfg(args)
    out("\n".join(memory_digest(home, args.domain, None, args.n)) or "(no earlier concepts)")


def cmd_snapshots(args) -> None:
    home, cfg = home_and_cfg(args)
    max_age = args.max_age_days or cfg["pipeline"]["trend_snapshot_max_age_days"]
    cutoff = (dt.date.today() - dt.timedelta(days=max_age)).isoformat()
    rows = []
    for p in sorted((home / "trend-snapshots").glob("*.json"), reverse=True):
        day = p.name[:10]
        if day < cutoff:
            continue
        data = cs.read_json(p, {}) or {}
        if args.domain and data.get("domain") not in (args.domain, None):
            continue
        rows.append({"path": str(p), "date": day, "domain": data.get("domain"), "mode": data.get("mode"),
                     "signals": len(data.get("signals", [])), "insights": len(data.get("insights", []))})
    out({"max_age_days": max_age, "snapshots": rows})


def cmd_bank_add(args) -> None:
    home, _ = home_and_cfg(args)
    pack = cs.domain_pack(args.domain)
    path = home / "cliche-bank" / f"{pack['slug']}.md"
    prefix = args.prefix
    if not prefix:
        plugin_bank = Path(pack["files"].get("cliche-bank", "")) if pack["files"].get("cliche-bank") else None
        m = re.search(r"\*\*([A-Z][A-Z0-9]*)-\d+\*\*", plugin_bank.read_text(encoding="utf-8")) if plugin_bank else None
        prefix = (m.group(1) if m else pack["slug"][:3].upper().replace("-", "")) + "L"
    text = path.read_text(encoding="utf-8") if path.exists() else (
        f"# Local cliché bank: {pack['slug']}\n\nAdded by you or accepted from cliche-hunter proposals. Same format as the plugin bank.\n")
    nums = [int(n) for n in re.findall(rf"\*\*{prefix}-(\d+)\*\*", text)]
    added = []
    for entry in args.text:
        nxt = (max(nums) + 1) if nums else 1
        nums.append(nxt)
        tag = "{rhyme} " if args.rhyme else ""
        line = f"- **{prefix}-{nxt:03d}** {tag}{entry.strip()}"
        if args.category and f"## {args.category}" not in text:
            text = text.rstrip() + f"\n\n## {args.category}\n"
        if args.category:
            head, _, tail = text.partition(f"## {args.category}\n")
            text = head + f"## {args.category}\n" + line + "\n" + tail
        else:
            text = text.rstrip() + "\n" + line + "\n"
        added.append(line)
    cs.atomic_write(path, text)
    out({"bank": str(path), "added": added})


def cmd_identity(args) -> None:
    home, cfg = home_and_cfg(args)
    brand_dir = home / "brand"
    template = cs.PLUGIN_ROOT / "skills" / "brand-memory" / "brand" / "_template.md"
    if args.init_brand:
        slug = re.sub(r"[^a-z0-9-]+", "-", args.init_brand.lower()).strip("-")
        target = brand_dir / f"{slug}.md"
        if target.exists():
            raise SystemExit(f"{target} already exists; edit it instead")
        cs.atomic_write(target, template.read_text(encoding="utf-8").replace("name: brand-name", f"name: {slug}"))
    if args.use_brand:
        user_cfg_path = home / "config.json"
        user_cfg = cs.read_json(user_cfg_path, {}) or {}
        user_cfg["active_brand"] = None if args.use_brand.lower() == "none" else args.use_brand
        cs.write_json(user_cfg_path, user_cfg)
        cfg = cs.load_config(home)
    ident = cs.identity_context(home, cfg)
    taste_path = home / "taste-profile.md"
    journal = taste_path.read_text(encoding="utf-8").count("\n- 20") if taste_path.exists() else 0
    brands = [{"name": p.stem, "filled": bool(cs.human_content(p.read_text(encoding="utf-8"))), "path": str(p)}
              for p in sorted(brand_dir.glob("*.md"))]
    out({"home": str(home), "mode": "neutral" if ident["neutral"] else "identity", "active_brand": ident["brand_name"],
         "configured_brand": cfg.get("active_brand") or os.environ.get("CREATIVE_STUDIO_BRAND"), "brands": brands,
         "taste_profile": str(taste_path), "taste_filled": bool(ident["taste"]), "journaled_choices": journal,
         "brand_template": str(template)})


def cmd_domains(args) -> None:
    out([{"domain": d["slug"], "pack": d["status"], "files": sorted(d["files"])} for d in cs.list_domains()])


def cmd_runs(args) -> None:
    home, _ = home_and_cfg(args)
    rows = []
    for d in sorted(cs.runs_dir(home).glob("r_*"), reverse=True)[: args.n]:
        b = cs.read_json(d / "brief.json", {}) or {}
        st = cs.read_json(d / "state.json", {}) or {}
        rows.append({"run_id": d.name, "domain": b.get("domain"), "goal": (b.get("goal") or "")[:80],
                     "statuses": st.get("status_counts"), "selected": (d / "selection.json").exists()})
    out(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cstudio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="state directory override")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--brief", help="file with brief JSON (default: stdin)"); p.add_argument("--seed", type=int)
    for name in ("context", "pool", "review-input", "survivors", "validate", "report", "status"):
        sub.add_parser(name).add_argument("--run")
    p = sub.add_parser("pairs"); p.add_argument("--run"); p.add_argument("--k", type=int)
    p = sub.add_parser("rank"); p.add_argument("--run"); p.add_argument("--n", type=int)
    p = sub.add_parser("draw"); p.add_argument("--run"); p.add_argument("--branch", default="R1"); p.add_argument("--like", default="A")
    p = sub.add_parser("cards"); p.add_argument("--run"); p.add_argument("--branch", required=True)
    p = sub.add_parser("recent"); p.add_argument("--domain", required=True); p.add_argument("--n", type=int, default=40)
    p = sub.add_parser("snapshots"); p.add_argument("--domain"); p.add_argument("--max-age-days", type=int)
    p = sub.add_parser("bank-add"); p.add_argument("--domain", required=True); p.add_argument("--text", action="append", required=True)
    p.add_argument("--category"); p.add_argument("--prefix"); p.add_argument("--rhyme", action="store_true")
    p = sub.add_parser("runs"); p.add_argument("--n", type=int, default=10)
    sub.add_parser("domains")
    p = sub.add_parser("identity"); p.add_argument("--init-brand"); p.add_argument("--use-brand")
    args = ap.parse_args(argv)
    handlers = {"init": cmd_init, "context": cmd_context, "pool": cmd_pool, "review-input": cmd_review_input,
                "survivors": cmd_survivors, "validate": cmd_validate, "pairs": cmd_pairs, "rank": cmd_rank,
                "report": cmd_report, "status": cmd_status, "draw": cmd_draw, "cards": cmd_cards, "recent": cmd_recent,
                "snapshots": cmd_snapshots, "bank-add": cmd_bank_add, "runs": cmd_runs, "domains": cmd_domains, "identity": cmd_identity}
    handlers[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
