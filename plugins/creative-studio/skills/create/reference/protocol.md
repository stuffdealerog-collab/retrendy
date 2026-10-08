# Agent ↔ script protocol

Every creative-studio agent ends its answer with exactly one fenced block whose
info string contains `cs:<kind>`, holding one JSON object. The SubagentStop
hook (`scripts/log_generation.py hook-subagent-stop`) extracts it from the
agent's final message (or, failing that, from its transcript), stores it as
`runs/<run_id>/artifacts/<kind>__<agent>__<hash>.json` and, for `concepts`,
upserts the concepts into `generation-log.jsonl` with status `candidate`.
The Stop hook does the same for blocks in the orchestrator's last message
(`selection`) and reconciles statuses.

Rules for every block:

- valid JSON (double quotes, no trailing commas, no comments);
- `run_id` exactly as given in the prompt;
- text in the brief's language; keys in English as below;
- one block per answer, at the very end.

## cs:trends (trend-analyst)

```json
{"run_id": "r_…", "mode": "live | cached | evergreen",
 "sources": ["google_trends_daily:US", "web_search", "snapshot:2026-10-01_lyrics_r_…"],
 "signals": [{"signal": "…", "source": "…", "evidence": "number, quote or URL", "velocity": "rising | peaking | fading", "relevance": "why it matters for this brief"}],
 "insights": [{"trend": "…", "need": "…", "white_space": "…", "counter_trend": "…", "tension": "the contradiction a concept can exploit"}],
 "notes": "gaps, degraded sources"}
```

## cs:baseline (cliche-hunter, MODE baseline)

```json
{"run_id": "r_…", "items": ["predictable answer 1", "predictable answer 2"]}
```

## cs:concepts (diverger, outsider)

```json
{"run_id": "r_…", "branch": "A", "strategy": "structural",
 "head": [{"text": "a high-probability idea you discarded", "p": 0.35}],
 "concepts": [{
   "title": "…", "logline": "…", "concept": "2-4 sentences",
   "sample": "domain sample, e.g. hook + verse lines separated by \n",
   "operator": "TRIZ-13 Inversion", "p": 0.06,
   "predictable": "what was predictable in the first draft",
   "escalation": "what you changed to make it bolder and more specific"}]}
```

`p` is the verbalized probability that a typical model would produce this
concept for this brief (0-1). `head` items become extra references for the
novelty filter.

## cs:review (cliche-hunter, MODE review)

```json
{"run_id": "r_…",
 "flags": [{"id": "c_…", "verdict": "cliche | borderline | ok", "pattern": "short name of the cliché move", "reason": "…"}],
 "bank_proposals": [{"category": "Story arcs", "text": "RU phrasing / EN phrasing"}]}
```

Only `verdict: cliche` removes a concept. List `ok` items only if you have a
note; unlisted ids count as ok.

## cs:scores (creative-director, MODE score)

```json
{"run_id": "r_…", "scores": [{
  "id": "c_…",
  "novelty":    {"score": 4, "evidence": "verbatim quote from the concept", "why": "…"},
  "surprise":   {"score": 3, "evidence": "…", "why": "…"},
  "usefulness": {"score": 4, "evidence": "…", "why": "…"},
  "brief_fit":  {"score": 5, "evidence": "…", "why": "…"},
  "craft":      {"score": 3, "evidence": "…", "why": "…"},
  "taboo_violation": false, "taboo_note": "",
  "strongest": "novelty", "weakest": "craft"}]}
```

`evidence` must be copied verbatim (any case/quotes/whitespace differences are
tolerated, `…` may join two verbatim fragments). `cstudio validate` lowers a
score by 1 when its evidence is not found.

## cs:audience (audience-proxy)

```json
{"run_id": "r_…", "reactions": [{"id": "c_…", "resonance": 4, "reaction": "first-person gut reaction", "evidence": "verbatim quote that triggered it", "would_do": "share | save | skip | hate-share"}]}
```

## cs:judgments (creative-director, MODE tournament)

```json
{"run_id": "r_…", "judgments": [{"pair": "P01", "winner": "A | B | tie", "margin": "slight | clear", "why": "one sentence"}]}
```

## cs:versions (editor)

```json
{"run_id": "r_…", "finalists": [{
  "id": "c_…", "label": "F1",
  "versions": {
    "safe":     {"title": "…", "hook": "…", "verse": "…", "note": "…"},
    "bold":     {"title": "…", "hook": "…", "verse": "…", "note": "…"},
    "director": {"title": "…", "hook": "…", "verse": "…", "note": "…"}}}]}
```

Domains without lyrics use `text` instead of `hook` + `verse`.

## cs:selection (orchestrator, after the user's answer)

```json
{"run_id": "r_…", "choice": "F2 | none", "version": "safe | bold | director | null",
 "reason": "the user's reason in their words", "rejected": {"F1": "…", "F3": "…"}}
```

## Log record (generation-log.jsonl)

```json
{"id": "c_5e1f0a9b2c", "ts": "2026-10-08T16:40:00Z", "run_id": "r_20261008_164000_ab12",
 "domain": "lyrics", "brief": "goal | audience: … | constraints: … | taboos: …",
 "title": "…", "logline": "…", "text": "…", "sample": "…",
 "strategy": "structural", "operator": "TRIZ-13 Inversion", "branch": "A", "agent": "creative-studio:diverger", "p": 0.06,
 "scores": {"novelty_embed": 0.47, "novelty": 4, "surprise": 3, "usefulness": 4, "brief_fit": 5, "craft": 3,
            "rubric_total": 0.71, "tournament_winrate": 0.8, "final": 0.75},
 "status": "candidate | filtered | rejected | finalist | selected",
 "reason": "why it got this status", "version": "bold"}
```
