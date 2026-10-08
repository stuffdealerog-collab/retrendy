---
description: Divergent generation method of creative-studio (verbalized sampling, tail selection, predictable→bolder escalation, operator cards SCAMPER / TRIZ / oblique / constraints / conceptual blending). Preloaded into the diverger and outsider agents. Use directly when the user wants a quick set of non-obvious variations for one idea without the full /create pipeline.
argument-hint: "[idea or brief to diverge on]"
---

# Diverge: produce ideas from the tail, not the head

A language model asked for "creative ideas" returns the most probable ones:
the head of its distribution. Asking it to "be more creative" moves the head
a little. This method does not ask for creativity; it changes **what you sample
from** and **what you keep**.

If you were invoked directly by the user (not as a creative-studio agent), run
steps 1-4 on their idea, return 6 concepts in plain text and skip the block.

## Inputs (from your prompt)

- `run_dir/context.md`: brief, identity (or neutral mode), trends and insights,
  **predictable answers** (do not build on them), **do-not-repeat list** (past runs).
- `run_dir/draw.json`: your branch's cards (deck, id, title, text), drawn by a
  random seed. You must use them; you did not choose them, which is the point.
- domain pack: what a concept is in this domain, craft rules.

## Step 1. Map the head (verbalized sampling, part 1)

Write down, privately, the 8-10 answers a typical model would give to this
brief, each with a probability `p` (how likely a typical model is to produce
it; the list need not sum to 1). These are the head. Include the ones from
`context.md` that apply. Put the `N` highest-probability ones you produced
yourself (N = "head samples" in the prompt) in the block as `head`: they become
extra references for the novelty filter, so every idea near them will be
rejected automatically.

## Step 2. Sample the tail (verbalized sampling, part 2)

Generate candidates **with explicit probabilities**, keeping only those with
`p` below the tail threshold from the prompt (default 0.15). Use your cards as
the generative move. Each card is a transformation, not a theme:

- apply the card to a specific part of the brief (the speaker, the object, the
  form, the situation, the audience's habit), not to "the idea" in general;
- one card can yield several candidates; a candidate may combine two cards;
- record which card produced it in `operator` (e.g. `TRIZ-13 Inversion`).

Generate about twice as many tail candidates as you must return; you will
discard half in step 4. A concept with `p` ≥ threshold is not allowed in
`concepts`, no matter how good it feels: if it is good and probable, someone
else already made it.

Probabilities are your honest estimate, not decoration. If every candidate
gets 0.01 the estimate is meaningless; spread them (0.02-0.14 is typical in
the tail).

## Step 3. Escalate each candidate (predictable → bolder and more specific)

For every candidate, three moves:

1. **Draft**: the concept in one or two sentences.
2. **What is predictable here?** Name it concretely: the expected speaker, the
   expected image, the expected ending, the expected emotion, the generic noun.
   Usually something is.
3. **Escalate**: replace the predictable part with something both **bolder**
   (riskier, stranger, more committed) and **more specific** (a concrete
   object, number, place, procedure, phrase). Bold without specific becomes
   surreal noise; specific without bold becomes a nice detail on a generic idea.

Keep the escalated version. Put the named predictable part in `predictable`
and the change in `escalation`: the critic reads them.

## Step 4. Self-filter before returning

Drop a candidate if:

- it is near anything in "predictable answers" or "do not repeat", even
  paraphrased (the script will reject it anyway at cosine ≥ 0.8, and a
  rejected concept is a wasted slot);
- it glues two clichés together ("rain + city lights"): the filter catches
  collages too;
- it violates a taboo or a hard constraint of the brief;
- it only works because of a pun on the brief's wording;
- two of your candidates are the same move with different nouns: keep the
  better one.

Then pick the requested number, maximising **spread**: different speakers,
forms, emotional angles, scales. Ten variations of one trick lose to five
different tricks.

## Step 5. Write the sample

Every concept carries a `sample` in the domain's form (for lyrics: hook +
4-8 lines of verse, following `craft.md`). The sample proves the concept works
in actual material and gives the critic something to quote. Abstract emotion
words in the sample (love, pain, soul, forever) are a sign the concept is not
specific yet; go back to step 3.

## Output

End with exactly one block (format: `${CLAUDE_PLUGIN_ROOT}/skills/create/reference/protocol.md`, `cs:concepts`):

```cs:concepts
{"run_id": "…", "branch": "A", "strategy": "structural",
 "head": [{"text": "…", "p": 0.4}],
 "concepts": [{"title": "…", "logline": "…", "concept": "…", "sample": "line 1\nline 2", "operator": "…", "p": 0.07, "predictable": "…", "escalation": "…"}]}
```

Before the block, write at most five lines: which cards worked, which did not
and why. No preamble, no recap of the brief.

## Operator decks

Your cards come from these decks (read a deck only if `draw.json` is missing):

- `operators/scamper.md`: substitute, combine, adapt, modify, put to other use, eliminate, reverse
- `operators/triz-40.md`: the 40 inventive principles translated into creative moves
- `operators/oblique-strategies.md`: lateral prompts that break the current frame
- `operators/constraints.md`: formal constraints that force non-default solutions
- `operators/conceptual-blending.md`: method for the outsider (input spaces → blend → emergent structure)
- `operators/foreign-domains.md`: far domains for the outsider to import structure from
