---
description: Manage creative-studio identity memory - create or edit a brand file, switch the active brand, fill or review the taste profile, and distil past choices from the choice journal into explicit taste principles. Use when the user wants to set up their brand, voice, taste or preferences for the creative studio, asks what the studio has learned about their taste, or wants to reset to neutral mode.
argument-hint: "[status | new-brand <name> | use <name> | taste | distil | neutral]"
allowed-tools: Bash(cstudio *) Read
---

# Brand and taste memory

Two separate things, kept in the state dir (`cstudio identity` prints it):

| File | What it is | Who writes it |
|---|---|---|
| `brand/<name>.md` | A brand or project identity: who speaks, to whom, voice, values, never-do list, references. Several can exist; one is active. | The user (you help by interviewing). Template: `${CLAUDE_SKILL_DIR}/brand/_template.md`. |
| `taste-profile.md` | The user's personal taste across projects. The upper part is written by the user; below `<!-- cs:auto -->` the Stop hook appends every choice (what, which version, why) and recomputes derived signals. | User (upper part), hook (lower part). |

The SessionStart hook loads both into context **only when they contain real
content**. Templates and empty sections count as empty; then the studio runs in
**neutral mode** and must not invent an identity.

Request: `$ARGUMENTS`

## status (default)

Run `cstudio identity` and report: state dir, brand files, which brand is
active and whether it is filled, whether the taste profile is filled, how many
choices are journaled. Suggest the next useful action in one line.

## new-brand <name>

1. `cstudio identity --init-brand <name>` copies the template to
   `<state>/brand/<name>.md` (it refuses to overwrite).
2. Interview the user, **one section at a time**, with concrete questions from
   the template's prompts. Write their answers in their words; do not upgrade
   them into marketing language. Leave a section empty rather than guess.
3. Show the filled file; on confirmation make it active:
   `cstudio identity --use-brand <name>`.

## use <name>

`cstudio identity --use-brand <name>`. `cstudio identity --use-brand none`
returns to "no active brand" (the only filled brand file, if exactly one, is
still auto-selected; use `neutral` to switch everything off).

## taste

Open `<state>/taste-profile.md` with Read, ask the user about each upper
section (what they value, what irritates them, reference works, default risk
level), and edit only the upper part. Never edit below `<!-- cs:auto -->`.

## distil

Read the choice journal and derived signals (below `<!-- cs:auto -->`). Find
patterns that recur at least twice (a version they keep choosing, a kind of
reason they keep giving, strategies that win). Propose 3-5 principles to the
user, each with the journal entries that support it. Write the accepted ones
into the upper "What I value" / "What irritates me" sections, in the user's
words. Do not delete journal entries.

## neutral

To run without identity temporarily: `CREATIVE_STUDIO_BRAND=` is not enough if
the taste profile is filled. Tell the user the options: rename the brand file
with a leading underscore (`_name.md` is ignored), or move the upper part of
the taste profile aside. Do not delete their files yourself.

## Rules

- Identity informs judgement (brief fit, editor's choices); it never overrides
  the explicit brief.
- Do not create a brand from your own imagination, from the user's email, name
  or company name. Only from what the user tells you in this conversation.
- Keep files short: 40-80 lines for a brand. The hook truncates context at
  `session_context.max_chars` (default 6000 characters).
