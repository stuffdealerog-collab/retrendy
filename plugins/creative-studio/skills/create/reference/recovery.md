# Recovery and troubleshooting

Read only when something in `/create` did not go as described.

| Symptom | Cause | What to do |
|---|---|---|
| `cstudio: command not found` | plugin `bin/` not on PATH (very old Claude Code, or running outside a session) | Use `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/studio.py" <cmd>`; for novelty `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/novelty_check.py"`; for the log `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_generation.py"`. |
| `status` shows no artifact after an agent returned | hooks disabled (`disableAllHooks`), agent omitted the block, or JSON was invalid | Paste the agent's answer into `cstudio log ingest --run <id> --agent <name> <<'CS' … CS`. If the JSON is broken, fix only the syntax, never the content. |
| Two runs share a state dir unexpectedly | `CREATIVE_STUDIO_HOME` or a project `.creative-studio/` folder | `cstudio log stats` prints the resolved home. |
| `novelty` says `"degraded": true` | neither `fastembed` nor `sentence-transformers` could load (no `uv`, offline first run) | Install once: `uv` (recommended) or `pip install fastembed numpy`. Then `cstudio novelty --warmup`. Lexical mode only catches near-verbatim repeats: tell the user. |
| `novelty` is slow the first time | model download (~1 GB for mpnet; `--lite` uses ~220 MB MiniLM) | Wait, or set `"novelty": {"model": "<lite model>"}` in `<home>/config.json`. |
| Almost everything filtered as `repeat` | the domain has many earlier runs with similar briefs | That is the filter working. Change the brief's angle, or lower `history_window`, or raise `threshold` in `<home>/config.json` (not below 0.75 for mpnet). |
| Almost everything filtered as `predictable` | the baseline list is too broad (cliche-hunter listed themes, not answers) | Re-run cliche-hunter baseline with "answers, not themes", then `pool` + `novelty` again. |
| Critic scores everything 4-5 | rubric drift | Re-spawn the director with "use the anchors; median score must be 3". |
| Stop hook did not record the selection | the `cs:selection` block was missing or malformed | `cstudio log select --run <id> --choice F2 --version bold --reason "…"`. |
| Need to rebuild log statuses | any manual edit of run files | `cstudio log reconcile --run <id>` (idempotent). |
