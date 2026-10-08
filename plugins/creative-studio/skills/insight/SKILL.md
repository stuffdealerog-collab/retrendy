---
description: Turn trend signals into creative insights with the chain trend -> human need -> white space -> counter-trend, plus the tension a concept can exploit. Preloaded into the trend-analyst agent. Use directly when the user has trends or observations and asks what they mean, where the opportunity is, or what everyone else will do with them.
argument-hint: "[signals or topic]"
---

# Insight: from what is happening to where nobody is standing

A trend is not an idea. Most competitors will read the same trend the same way;
their answers are the predictable centre. An insight finds the **need** behind
the trend and the **space** the obvious answers leave empty.

If invoked directly by the user: produce 3-5 insight cards as a table and stop.

## The chain (one insight card)

1. **Trend**: one signal or cluster from trend-radar, with its evidence.
2. **Need**: the human need or anxiety that makes the trend happen. Ask "why
   would a person do this at 11 p.m. on a Tuesday?" twice. Needs are old
   (belonging, control, status, relief, meaning, play); trends are new
   costumes for them.
3. **Obvious answer**: what most brands/creators will make from this trend.
   (Feed these to the baseline: they are predictable.)
4. **White space**: what the obvious answers ignore: a neglected audience, an
   unspoken side of the need, a format nobody uses for it, a feeling everyone
   avoids.
5. **Counter-trend**: what the people tired of this trend want. Every
   peaking trend creates its opposite (hyper-polish → deliberate mess; constant
   irony → sincerity; speed → slowness). The counter-trend is often where the
   next idea is.
6. **Tension**: the contradiction a concept can exploit, in one line: "wants
   to be seen, afraid of being watched".

## Quality checks

- The need is a human truth, not a marketing phrase ("consumers seek
  authenticity" fails; "people curate their mess to look relaxed" passes).
- The white space is specific enough that two different teams would make
  noticeably different things from it.
- At least one card is built on a counter-trend, and at least one on a
  `rising` (not `peaking`) signal.
- Respect the brief's audience. In neutral mode do not assume a brand's
  position; describe opportunities, not brand strategy.

## Output (inside the trend-analyst's `cs:trends` block)

`insights[]`, each with `trend`, `need`, `white_space`, `counter_trend`,
`tension`. 3-5 cards. Quality over count.
