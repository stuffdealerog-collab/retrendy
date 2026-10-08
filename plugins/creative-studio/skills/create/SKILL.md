---
description: Run the full creative-studio pipeline on a brief (trends, insight, parallel divergent generation, novelty filter against clichés and past runs, critic with rubric and pairwise tournament, safe/bold/director's versions, user choice recorded to taste memory). Use when the user asks to come up with, brainstorm or generate original ideas or concepts (song lyrics, short videos, ad campaigns, names, or any creative brief) and wants non-obvious results, or types /create or /creative-studio:create. Also use when the user answers a creative-studio run by picking a finalist (e.g. "F2 bold, because…").
argument-hint: "[brief: domain, goal, audience, constraints, taboos]"
allowed-tools: Bash(cstudio *) Read Glob Grep
---

# creative-studio: /create

You are the **orchestrator**. You do not invent concepts and you do not judge
them: generators, the critic and the editor are separate subagents, and the
mechanics (randomness, novelty filtering, evidence checks, ranking) are scripts.
Your job is to move the run through the stages, keep the files consistent and
present the result.

Brief from the user: `$ARGUMENTS`

Plugin root: `${CLAUDE_PLUGIN_ROOT}` · Default state dir: `${CLAUDE_PLUGIN_DATA}`
The `cstudio` command is on PATH (plugin `bin/`). Every `cstudio` command prints JSON.

## Ground rules

1. **Never generate concepts yourself**, not even "a few more" to fill gaps.
   Spawn a generator.
2. **Agents talk through fenced blocks.** Every subagent ends its answer with
   a ```` ```cs:<kind> ```` JSON block. The SubagentStop hook stores it in
   the run folder and logs concepts. After each agent stage run
   `cstudio status --run <id>`; if an artifact is missing (hooks disabled,
   agent forgot the block), store it yourself with
   `cstudio log ingest --run <id> --agent <agent-name> <<'CS'` followed by the
   agent's full answer and a closing `CS` line.
3. **Spawn parallel agents in ONE message**, foreground (do not background
   them), and pass each one the run id and run dir. Agent types are
   plugin-scoped: `creative-studio:<name>`.
4. **Neutral mode.** If `init` reports `"mode": "neutral"`, there is no brand
   and no taste profile: do not invent a brand voice, persona, audience taste or
   "house style". Judge only against the brief.
5. **Degrade, don't fail.** Missing trend MCP tools → web search → cached
   snapshots → evergreen mode. Missing embedding model → lexical mode
   (`"degraded": true`). Stub or unknown domain → generic core + whatever bank
   exists. Always say in the report which mode ran.
6. **Language.** Talk to the user and write concepts in the brief's language.
   Pass `language` to every agent.

## Step 0. Selection reply?

If this message answers an earlier run (picks a finalist like "F2", a version,
or rejects all), skip to **Step 9**.

## Step 1. Brief → run

Turn the user's text into a brief JSON. Fields: `domain` (one of the packs
below; unknown → closest pack or `generic`), `goal`, `audience`,
`constraints` (list), `taboos` (list), `language`, `raw` (user's text,
verbatim). Do not ask questions unless the goal itself is missing. Fill gaps
with explicit assumptions (e.g. audience "not specified") and list them in the
report. Available packs:

`lyrics` (full pack), `short-video`, `ad-campaign`, `naming` (stubs: generic core + seed bank). `cstudio domains` prints the live list, including packs the user added.

```bash
cstudio init <<'JSON'
{"domain": "...", "goal": "...", "audience": "...", "constraints": [], "taboos": [], "language": "ru", "raw": "..."}
JSON
```

Keep from the output: `run_id`, `run_dir`, `home`, `domain.pack`,
`mode`, `branches` (each has `id`, `agent`, `strategy`, `label`, `cards`).

Then warm the embedding model in the background (first use downloads ~1 GB
once; later runs load from cache): run `cstudio novelty --warmup` with
`run_in_background: true`. Do not wait for it.

## Step 2. Trends + predictable answers (parallel, one message)

- **`creative-studio:trend-analyst`**, prompt:
  > run_id: `<id>` · run_dir: `<dir>` · state dir: `<home>` · language: `<lang>`
  > Brief: `<brief JSON>`
  > Domain pack: `${CLAUDE_PLUGIN_ROOT}/domains/<domain>/domain.md` (section "Trend angles").
  > Collect fresh signals, derive 3-5 insights (trend → need → white space → counter-trend), end with a `cs:trends` block.

- **`creative-studio:cliche-hunter`**, prompt:
  > MODE: baseline · run_id: `<id>` · language: `<lang>`
  > Brief: `<brief JSON>`
  > Cliché bank: `${CLAUDE_PLUGIN_ROOT}/domains/<domain>/cliche-bank.md`
  > List the 15-25 most predictable answers to THIS brief. End with a `cs:baseline` block.

Then `cstudio status --run <id>` (expect `trends` and `baseline` artifacts;
ingest manually if missing) and `cstudio context --run <id>`.

## Step 3. Divergence: one generator per branch (parallel, one message)

For every branch from `init` spawn its `agent` (`creative-studio:diverger` or
`creative-studio:outsider`) with:

> run_id: `<id>` · run_dir: `<dir>` · branch: `<id>` · strategy: `<strategy>` (`<label>`)
> language: `<lang>` · concepts to return: `<pipeline.concepts_per_branch>` · head samples: `<pipeline.head_samples_per_branch>` · tail threshold p < `<pipeline.tail_probability>`
> Read first: `<run_dir>/context.md` (brief, trends, predictable answers, do-not-repeat list) and your branch's cards in `<run_dir>/draw.json`.
> Domain: `${CLAUDE_PLUGIN_ROOT}/domains/<domain>/domain.md` and `craft.md`.
> End with one `cs:concepts` block.

Do not add anything about other branches: independence between branches is
the point.

Then:

```bash
cstudio pool --run <id>
```

If `missing_branches` is not empty, ingest the missing agents' answers manually
(Ground rule 2) and run `pool` again.

## Step 4. Novelty filter

```bash
cstudio novelty --run <id> --compact
```

The output lists every filtered concept with `reason_code` (`cliche`,
`cliche_collage`, `predictable`, `repeat`, `duplicate`) and a human-readable
`reason`. If `degraded` is true, note it for the report. If the model is still
downloading the command just waits; that is fine.

## Step 5. Cliché-hunter review + refill

```bash
cstudio review-input --run <id>
```

Spawn **`creative-studio:cliche-hunter`**:

> MODE: review · run_id: `<id>` · language: `<lang>`
> Read `<run_dir>/review-input.md` (survivors of the embedding filter, soft flags first) and the bank `${CLAUDE_PLUGIN_ROOT}/domains/<domain>/cliche-bank.md`.
> Mark structural clichés the embeddings missed; propose new bank entries. End with a `cs:review` block.

Then `cstudio survivors --run <id>`.

If `refill_needed` is true and refill rounds remain
(`pipeline.max_refill_rounds`): `cstudio draw --run <id> --branch R1 --like <id of the branch with most survivors>`,
spawn that branch's agent with the Step 3 prompt plus
"Also read `<run_dir>/refill-notes.md`: these failure modes already happened.",
then repeat `pool` → `novelty` → `review-input` → cliché-hunter → `survivors`.
Never loop more than the configured rounds; continue with what survives.

If `bank_proposals` > 0, show them in the report as suggestions. Add them to
the local bank only if the user agrees:
`cstudio bank-add --domain <domain> --category "<category>" --text "<entry>"`.

## Step 6. Critique (parallel, one message)

- **`creative-studio:creative-director`**:
  > MODE: score · run_id: `<id>` · language: `<lang>`
  > Read `<run_dir>/context.md` (brief + identity) and `<run_dir>/critique-input.md`.
  > Score EVERY concept with the rubric; evidence must be verbatim quotes. End with a `cs:scores` block.
- **`creative-studio:audience-proxy`**:
  > run_id: `<id>` · language: `<lang>` · audience: `<brief.audience or "not specified">`
  > Read `<run_dir>/context.md` and `<run_dir>/critique-input.md`. React to every concept as this audience. End with a `cs:audience` block.

Then:

```bash
cstudio validate --run <id>
cstudio pairs --run <id>
```

`validate` checks that every evidence quote really occurs in the concept and
lowers unsupported scores. If more than a quarter of the survivors are
`unscored`, re-spawn the director for those ids only.

## Step 7. Blind pairwise tournament

Spawn a **fresh** `creative-studio:creative-director` (not a continuation of
the scoring one; it must not see the scores):

> MODE: tournament · run_id: `<id>` · language: `<lang>`
> Read `<run_dir>/context.md` (brief only matters) and `<run_dir>/pairs.md`. Judge every pair. End with a `cs:judgments` block.

Then `cstudio rank --run <id>` (rubric + win rate, diversity-aware finalists).

## Step 8. Converge: versions

Spawn **`creative-studio:editor`**:

> run_id: `<id>` · language: `<lang>`
> Read `<run_dir>/context.md`, `<run_dir>/finalists.md`, `${CLAUDE_PLUGIN_ROOT}/domains/<domain>/domain.md` (section "Output of the editor") and `craft.md`.
> For each finalist write safe / bold / director's versions. End with a `cs:versions` block.

Then `cstudio report --run <id>` and show the user that report (you may
translate headings to the brief's language; keep every number and reason).
Add: assumptions you made in Step 1, degraded modes, bank proposals.

Finish with the question, in the user's language:

> Which one? Reply with the finalist and version (e.g. "F2 bold") and **why**,
> in a sentence. Or "none" and why. The reason goes into your taste profile.

If the `AskUserQuestion` tool is available and the session is interactive, you
may ask with it instead (options: F1, F2, F3, None; then ask for the reason in
free text). Otherwise end the turn here; the user answers in the next message.

## Step 9. Record the choice

When the user has picked (or rejected all), confirm in one or two sentences
what was chosen and what the taste profile will learn, then end your message
with exactly one block (the Stop hook writes it to the log and to the taste
profile; do not edit those files yourself):

```cs:selection
{"run_id": "<id>", "choice": "F2", "version": "bold", "reason": "<the user's reason, in their words>", "rejected": {"F1": "<why not, if the user said>", "F3": "<…>"}}
```

`choice` is the finalist label, or `"none"`. `version` is `safe`, `bold` or
`director` (null if not given). If the user gave no reason, ask for one first;
a choice without a reason teaches the taste profile nothing.

If hooks are disabled, record it directly instead:
`cstudio log select --run <id> --choice F2 --version bold --reason "<reason>"`.

## Files

- Agent block formats: `${CLAUDE_PLUGIN_ROOT}/skills/create/reference/protocol.md`
- Troubleshooting and manual recovery: `${CLAUDE_PLUGIN_ROOT}/skills/create/reference/recovery.md`
