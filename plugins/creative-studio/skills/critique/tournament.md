# Blind pairwise tournament

Absolute scores are noisy; pairwise preferences are more reliable. The
tournament runs on the top concepts by rubric, but the judge is a **fresh**
critic instance that sees no scores, only pairs, so it is not anchored by its
earlier numbers.

## Schedule (done by `cstudio pairs`)

- round robin among the top `tournament_size` concepts (default 6 → 15 pairs);
- pair order shuffled with a fixed seed;
- each concept appears roughly equally often as **A** and as **B**, to cancel
  the judge's position bias.

## Procedure per pair

1. Read A, then B. Then read B, then A (seriously: the second-read order
   matters for position bias).
2. Ask, in this order:
   - Which one would I defend in front of the person who wrote the brief?
   - Which one would the audience remember tomorrow without being reminded?
   - Which one is more alive, and which is just competent?
3. Write the winner and one sentence naming the decisive difference. Not
   "A is more creative", but "A's hook changes meaning on return; B states the
   same feeling three times".
4. `margin`: `clear` if you would not change your mind after a night's sleep,
   otherwise `slight`.

## Bias checks before you submit

- Count how often you picked A. If it is far from half, re-read the pairs
  where you picked A by a slight margin.
- Longer is not better. If you mostly picked the longer one, re-check.
- Do not punish an idea for being strange if the strangeness makes sense in
  hindsight; do punish strangeness that is just noise.

## Scoring (done by `cstudio rank`)

Win rate = (wins + 0.5 × ties) / games. Final score = 0.5 × rubric total +
0.5 × win rate (configurable). Finalists are chosen greedily with a diversity
penalty (MMR, λ = 0.6): each next finalist maximises 0.6 × final − 0.4 × its
highest embedding similarity to the finalists already chosen, so the user gets
genuinely different options rather than three takes on one move.
