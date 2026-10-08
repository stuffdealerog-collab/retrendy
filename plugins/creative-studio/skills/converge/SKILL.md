---
description: Convergence method of creative-studio - turn finalist concepts into three executable versions (safe, bold, director's cut) without losing what made them win. Preloaded into the editor agent. Use directly when the user has a chosen concept and wants it developed into safe / bold / director's variants.
argument-hint: "[concept to develop]"
---

# Converge: three versions of each finalist

The finalists won because of one specific move (the device). Convergence
develops that move into something executable. It is not a chance to swap in a
different, safer idea. **Every version keeps the device**; the versions differ
in how far they push it and how much they ask of the audience.

If invoked directly by the user: produce the three versions of their concept
in plain text and skip the block.

## Inputs

- `context.md`: brief, identity or neutral mode, audience;
- `finalists.md`: each finalist with its rubric scores, strongest and weakest
  criterion;
- domain pack: `domain.md` (section "Output of the editor") and `craft.md`.

## The three versions

| Version | Purpose | Rules |
|---|---|---|
| **safe** | The version a cautious client approves today. | Keep the device intact but make the entry point obvious: clearer setup, familiar form, no ambiguity in the hook. Remove anything that could be misread. It must still not be a cliché: if making it safe kills the device, say so in `note` instead of shipping a cliché. |
| **bold** | The version that commits fully. | Push the device to its logical extreme: more specific, less explained, riskier. Fix the finalist's `weakest` criterion without softening its `strongest`. Allowed to lose part of the audience to win the rest harder. |
| **director** | The authored version: what a strong director or songwriter would make of it. | One idiosyncratic decision that only this version has (a structural choice, a point of view, an unusual form), executed with maximal craft. Add a production or delivery note that makes it makeable. |

## Procedure per finalist

1. Write the device in one sentence. If you cannot, re-read the finalist.
2. Fix the weakest criterion first (from `finalists.md`): e.g. weak craft →
   rewrite the sample lines; weak brief fit → reconnect to the goal.
3. Write `bold` first (it is the truest to the device), then derive `safe` by
   making the entry easier, and `director` by adding the one authored choice.
4. Run the domain's craft rules over every line (lyrics: concrete nouns, one
   image system, prosody, no cliché-bank rhymes or phrases).
5. Check every version against the brief's taboos and hard constraints.

## Domain fields

Lyrics: `title`, `hook` (2-4 lines), `verse` (4-8 lines), `note`.
Other domains: `title`, `text` (the executable description in the domain's
format), `note`. Follow the domain pack if it says otherwise.

## Output

Before the block, at most three lines per finalist on what changed between
versions. Then exactly one `cs:versions` block (format in
`${CLAUDE_PLUGIN_ROOT}/skills/create/reference/protocol.md`) with all
finalists, using their `id` and `label` from `finalists.md`.
