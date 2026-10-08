# Rubric

Five criteria, 1-5 each, every score with a verbatim quote as evidence.
Weights (configurable in `config/studio.json` → `rubric.weights`): novelty
0.25, surprise 0.20, usefulness 0.15, brief fit 0.20, craft 0.20. The script
blends the critic's novelty with the embedding distance (30 %), mixes in the
audience-proxy's resonance (10 %), then combines the rubric with the
tournament win rate (50/50) for the finalists.

Novelty and surprise are different: **novelty** is distance from what exists
(clichés, past ideas, the obvious answers to this brief); **surprise** is
whether the idea violates the audience's expectation *inside* the experience
and then makes sense in hindsight. Something can be new and unsurprising (a
new topic told the expected way) or surprising and not new (a well-known twist
used well).

## Novelty: is this far from what already exists?

| Score | Anchor |
|---|---|
| 1 | A cliché or a direct paraphrase of an obvious answer to this brief. |
| 2 | A familiar idea with a new coat: different nouns, same move. |
| 3 | A recognisable approach applied to an unusual subject, or an unusual approach to a familiar subject. |
| 4 | You cannot name a work that does this; the core move is fresh, though its parts are known. |
| 5 | The core move itself is new to you, and obviously right once seen. |

Evidence: the phrase that carries the core move.

## Surprise: does it break expectation, and then make sense?

| Score | Anchor |
|---|---|
| 1 | Everything goes where you expect from the first line. |
| 2 | One small unexpected detail. |
| 3 | A clear turn or reframe at one point. |
| 4 | The premise itself is unexpected, and the turn lands with a "of course" feeling. |
| 5 | It changes how you see the subject afterwards: an "inevitable surprise". |

Evidence: the line or element where the expectation breaks. Random
strangeness with no hindsight logic is at most 2.

## Usefulness: does it do the job the brief exists for?

| Score | Anchor |
|---|---|
| 1 | It would not achieve the goal even if executed perfectly. |
| 2 | It achieves the goal only with a lot of explanation or luck. |
| 3 | It plausibly achieves the goal for part of the audience. |
| 4 | It clearly achieves the goal; the audience has a reason to care, share, remember. |
| 5 | It achieves the goal and creates a second effect (talkability, reuse, a ritual). |

Evidence: the element that makes the audience act or remember.

## Brief fit: does it respect the brief?

| Score | Anchor |
|---|---|
| 1 | Ignores the goal or breaks a hard constraint (if a taboo, also set `taboo_violation`). |
| 2 | Related to the topic but answers a different question. |
| 3 | Fits the brief with a stretch the user may not accept. |
| 4 | Fits the brief, the audience and the constraints. |
| 5 | Fits and turns a constraint of the brief into an advantage. |

Evidence: the part that addresses the goal or the constraint. In identity
mode, brand and taste profile count here; in neutral mode they don't exist.

## Craft: is it made well in this domain?

Use the domain's `craft.md` (lyrics: concrete nouns, image system, prosody,
fresh rhyme, a hook that earns repetition).

| Score | Anchor |
|---|---|
| 1 | Generic language, mixed metaphors, unworkable. |
| 2 | Workable but flat; generic phrasing dominates. |
| 3 | Competent and consistent, no surprises in execution. |
| 4 | Precise, specific, quotable in places. |
| 5 | Every element serves the device; you would quote it to someone else. |

Evidence: the best or worst line of the sample.

## Taboo veto

If the concept breaks a taboo from the brief (or the domain's taboo defaults),
set `taboo_violation: true` and explain in `taboo_note`. The concept's total
becomes 0 regardless of scores.
