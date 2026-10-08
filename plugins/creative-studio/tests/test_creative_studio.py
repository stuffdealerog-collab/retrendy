"""Tests for creative-studio scripts. Stdlib unittest; no network.

    python3 -m unittest discover -s tests -v

The semantic novelty test needs fastembed + the cached model and is skipped
otherwise (run `bin/cstudio novelty --warmup` once to enable it).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cs_common as cs  # noqa: E402
import novelty_check as nc  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def block(kind: str, data: dict) -> str:
    return f"Some commentary.\n\n```cs:{kind}\n{json.dumps(data, ensure_ascii=False)}\n```\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.env = {**os.environ, "CREATIVE_STUDIO_HOME": str(self.home), "CS_NO_UV": "1"}
        self.env.pop("CLAUDE_ENV_FILE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, script: str, *args: str, stdin: str | None = None, env: dict | None = None) -> str:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], input=stdin, capture_output=True,
                           text=True, env=env or self.env, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, f"{script} {args} failed:\n{r.stderr}\n{r.stdout}")
        return r.stdout

    def cli_json(self, script: str, *args: str, stdin: str | None = None):
        return json.loads(self.cli(script, *args, stdin=stdin))

    def hook(self, which: str, payload: dict) -> None:
        self.cli("log_generation.py", which, stdin=json.dumps(payload, ensure_ascii=False))


class TemplatesAndBlocks(unittest.TestCase):
    def test_seed_templates_count_as_empty(self):
        self.assertEqual(cs.human_content((ROOT / "data" / "taste-profile.md").read_text(encoding="utf-8")), "")
        tpl = ROOT / "skills" / "brand-memory" / "brand" / "_template.md"
        self.assertEqual(cs.human_content(tpl.read_text(encoding="utf-8")), "")

    def test_filled_line_is_detected(self):
        text = (ROOT / "data" / "taste-profile.md").read_text(encoding="utf-8").replace(
            "## Что я ценю в идеях\n", "## Что я ценю в идеях\n- точная бытовая деталь\n")
        self.assertIn("точная бытовая деталь", cs.human_content(text))

    def test_extract_blocks_variants(self):
        text = 'a\n```json cs:concepts\n{"x": 1}\n```\n```cs:baseline\n{"items": []} trailing words\n```\n```cs:bad\n{oops\n```'
        kinds = [k for k, _ in cs.extract_blocks(text)]
        self.assertEqual(kinds, ["concepts", "baseline"])

    def test_untagged_json_block_is_recovered_by_signature(self):
        text = 'Done.\n```json\n{"run_id": "r_1", "judgments": [{"pair": "P01", "winner": "A"}]}\n```'
        self.assertEqual([k for k, _ in cs.extract_blocks(text)], ["judgments"])
        self.assertEqual(cs.extract_blocks('```json\n{"judgments": []}\n```'), [])  # no run_id: not ours

    def test_cliche_bank_size_and_ids_unique(self):
        bank = nc.parse_bank(ROOT / "domains" / "lyrics" / "cliche-bank.md")
        self.assertGreaterEqual(len(bank), 60)
        self.assertLessEqual(len(bank), 100)
        ids = [b["ref_id"] for b in bank]
        self.assertEqual(len(ids), len(set(ids)))


class LogUpsert(Base):
    def test_status_never_moves_backwards(self):
        cs.ensure_home(self.home)
        cs.upsert_log(self.home, [{"id": "c1", "status": "candidate", "title": "t"}])
        cs.upsert_log(self.home, [{"id": "c1", "status": "filtered", "reason": "cliché"}])
        cs.upsert_log(self.home, [{"id": "c1", "status": "candidate"}])
        row = cs.read_jsonl(self.home / cs.LOG_NAME)[0]
        self.assertEqual((row["status"], row["reason"]), ("filtered", "cliché"))

    def test_finalist_can_become_selected_or_rejected(self):
        cs.ensure_home(self.home)
        cs.upsert_log(self.home, [{"id": "c1", "status": "finalist"}, {"id": "c2", "status": "finalist"}])
        cs.upsert_log(self.home, [{"id": "c1", "status": "selected"}, {"id": "c2", "status": "rejected"}])
        rows = {r["id"]: r["status"] for r in cs.read_jsonl(self.home / cs.LOG_NAME)}
        self.assertEqual(rows, {"c1": "selected", "c2": "rejected"})


class NoveltyLexical(Base):
    def test_degraded_mode_still_filters_verbatim(self):
        out = self.cli_json("novelty_check.py", "--backend", "lexical", "--domain", "lyrics",
                            "--text", "Танец под дождём как жест свободы",
                            "--text", "Сторож дачного кооператива поёт о ящике с ключами соседей")
        self.assertTrue(out["degraded"])
        codes = {f["title"][:5]: f["reason_code"] for f in out["filtered"]}
        self.assertEqual(codes.get("Танец"), "cliche")
        self.assertEqual(out["counts"]["kept"], 1)


@unittest.skipUnless(nc.__dict__.get("np") or __import__("importlib").util.find_spec("fastembed"), "fastembed not installed")
class NoveltySemantic(Base):
    def test_fixture_outcomes(self):
        model_cache = os.environ.get("CS_TEST_MODEL_CACHE")
        if model_cache:
            (self.home / "cache").mkdir(parents=True, exist_ok=True)
            os.symlink(model_cache, self.home / "cache" / "models")
        out = self.cli_json("novelty_check.py", "--backend", "fastembed", "--domain", "lyrics",
                            "--pool", str(FIX / "novelty_pool.json"), "--baseline", str(FIX / "baseline.json"),
                            "--history-file", str(FIX / "history.jsonl"))
        pool = {c["id"]: c for c in json.loads((FIX / "novelty_pool.json").read_text(encoding="utf-8"))["concepts"]}
        outcome = {k["id"]: ("soft" if k["soft_flag"] else "kept") for k in out["kept"]}
        outcome.update({f["id"]: f["reason_code"] for f in out["filtered"]})
        wrong = {cid: (outcome[cid], c["accept"]) for cid, c in pool.items() if outcome[cid] not in c["accept"]}
        self.assertEqual(wrong, {}, "unexpected novelty outcomes")
        pair = sorted(outcome[c] for c in ("fresh-1", "dup-1"))
        self.assertEqual(pair, ["duplicate", "kept"], "exactly one of a duplicate pair is collapsed")
        fresh5 = next(k for k in out["kept"] if k["id"] == "fresh-5")
        self.assertTrue(any(w["type"] == "rhyme" and w["ref_id"] == "LY-029" for w in fresh5["line_warnings"]))


class Decks(unittest.TestCase):
    def test_deck_sizes(self):
        import studio
        sizes = {d: len(studio.load_deck(d)) for d in ("scamper", "triz-40", "oblique-strategies", "constraints", "foreign-domains")}
        self.assertEqual(sizes, {"scamper": 7, "triz-40": 40, "oblique-strategies": 36, "constraints": 30, "foreign-domains": 60})

    def test_draw_is_seeded_and_respects_exclusions(self):
        import random
        import studio
        a = studio.draw_cards({"triz-40": 3, "foreign-domains": 2}, random.Random(7), ["beekeeping"])
        b = studio.draw_cards({"triz-40": 3, "foreign-domains": 2}, random.Random(7), ["beekeeping"])
        self.assertEqual([c["id"] for c in a], [c["id"] for c in b])
        many = studio.draw_cards({"foreign-domains": 60}, random.Random(1), ["beekeeping"])
        self.assertNotIn("F01", [c["id"] for c in many])


class SessionStart(Base):
    def test_neutral_mode_and_env_file(self):
        env_file = Path(self.tmp.name) / "env.sh"
        env = {**self.env, "CLAUDE_ENV_FILE": str(env_file)}
        out = self.cli("session_context.py", stdin=json.dumps({"cwd": self.tmp.name, "session_id": "s1"}), env=env)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("neutral mode", ctx)
        self.assertIn(f"export CS_HOME={self.home}", env_file.read_text())

    def test_filled_brand_is_loaded(self):
        cs.ensure_home(self.home)
        (self.home / "brand" / "acme.md").write_text("# Brand\n\n## Голос\n- сухо и точно, без восклицаний\n", encoding="utf-8")
        ctx = json.loads(self.cli("session_context.py", stdin="{}"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("сухо и точно", ctx)
        self.assertIn("Active brand: acme", ctx)


class McpServer(unittest.TestCase):
    def test_protocol_without_network(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sources_status", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "social_search", "arguments": {"platform": "tiktok", "query": "x"}}}]
        env = {k: v for k, v in os.environ.items() if k not in ("APIFY_TOKEN", "YOUTUBE_API_KEY")}
        env["CREATIVE_STUDIO_HOME"] = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, str(ROOT / "servers" / "trend_sources.py")], capture_output=True, text=True, env=env,
                           input="\n".join(json.dumps(m) for m in msgs) + "\n", timeout=30)
        replies = {d["id"]: d for d in map(json.loads, r.stdout.splitlines())}
        self.assertEqual(sorted(replies), [1, 2, 3, 4])
        self.assertIn("google_trends_daily", [t["name"] for t in replies[2]["result"]["tools"]])
        self.assertFalse(json.loads(replies[4]["result"]["content"][0]["text"])["configured"])


def concept(title: str, logline: str, body: str, sample: str, op: str, p: float) -> dict:
    return {"title": title, "logline": logline, "concept": body, "sample": sample, "operator": op, "p": p,
            "predictable": "x", "escalation": "y"}


class PipelineOffline(Base):
    """Whole run with fake agent outputs, lexical backend, hooks fed through stdin."""

    def test_full_run_and_selection(self):
        brief = {"domain": "lyrics", "goal": "песня об одиночестве в большом городе", "audience": "", "constraints": [],
                 "taboos": ["реальные люди"], "language": "ru", "raw": "песня об одиночестве"}
        init = self.cli_json("studio.py", "init", "--seed", "42", stdin=json.dumps(brief, ensure_ascii=False))
        run = init["run_id"]
        self.assertEqual(init["mode"], "neutral")
        self.assertEqual([b["id"] for b in init["branches"]], ["A", "B", "C", "D"])

        sub = lambda agent, text: self.hook("hook-subagent-stop", {"cwd": self.tmp.name, "agent_type": agent, "last_assistant_message": text})  # noqa: E731
        sub("creative-studio:trend-analyst", block("trends", {"run_id": run, "mode": "evergreen", "sources": [], "signals": [],
                                                              "insights": [{"trend": "t", "need": "n", "white_space": "w", "counter_trend": "c", "tension": "x"}]}))
        sub("creative-studio:cliche-hunter", block("baseline", {"run_id": run, "items": ["Одинокий человек в толпе мегаполиса"]}))
        ideas = {
            "A": [concept("Ключница", "Сторож поёт о ящике с ключами соседей", "Каждый куплет — крючок с биркой.", "Крючок двенадцать\nВы обещали забрать", "T01", 0.05),
                  concept("Гарантийный талон", "Песня как гарантийный талон на отношения", "Пункты гарантии.", "Гарантия не распространяется", "SC1", 0.08)],
            "B": [concept("Ливень", "Танец под дождём как жест свободы", "Танец под дождём как жест свободы", "Мы будем вечно молодыми", "O01", 0.12),
                  concept("Девятый", "Курьер поднимается на девятый этаж пешком", "Каждый этаж — куплет.", "Третий: пахнет луком", "K01", 0.06)],
            "C": [concept("Тихая дискотека", "Пара расстаётся на тихой дискотеке", "Разные каналы в наушниках.", "Ты на красном, я на синем", "T13", 0.04),
                  concept("Стол находок", "Зонт в такси рассказывает о хозяйке", "Опись находок.", "Я пролежал под сиденьем", "O02", 0.07)],
            "D": [concept("Диспетчерская", "Пилот и диспетчер расстаются по протоколу", "Readback каждой фразы.", "Повторите, вас не понял", "F02 ATC", 0.03),
                  concept("Улей", "Семья решает, кто уходит, как рой", "Старая матка уходит с половиной.", "Нас стало слишком много", "F01 Bees", 0.05)],
        }
        for br, cs_ in ideas.items():
            agent = "creative-studio:outsider" if br == "D" else "creative-studio:diverger"
            sub(agent, block("concepts", {"run_id": run, "branch": br, "strategy": f"s{br}", "head": [{"text": f"head {br}", "p": 0.4}], "concepts": cs_}))
        log = cs.read_jsonl(self.home / cs.LOG_NAME)
        self.assertEqual(len(log), 8)
        self.assertTrue(all(r["status"] == "candidate" and r["domain"] == "lyrics" and r["brief"] for r in log))

        pool = self.cli_json("studio.py", "pool", "--run", run)
        self.assertEqual((pool["pool"], pool["missing_branches"]), (8, []))
        ctx = self.cli_json("studio.py", "context", "--run", run)
        self.assertTrue(ctx["neutral"])
        nov = self.cli_json("novelty_check.py", "--run", run, "--backend", "lexical")
        self.assertEqual(nov["counts"]["by_reason"].get("cliche"), 1)
        self.cli_json("studio.py", "review-input", "--run", run)
        kept_ids = [k["id"] for k in nov["kept"]]
        sub("creative-studio:cliche-hunter", block("review", {"run_id": run, "flags": [{"id": kept_ids[-1], "verdict": "cliche", "pattern": "p", "reason": "r"}],
                                                              "bank_proposals": [{"category": "Story arcs", "text": "новое / new"}]}))
        surv = self.cli_json("studio.py", "survivors", "--run", run)
        self.assertEqual(surv["survivors"], 6)
        survivors = json.loads((self.home / "runs" / run / "survivors.json").read_text())["kept"]
        pool_rows = {c["id"]: c for c in json.loads((self.home / "runs" / run / "pool.json").read_text())}
        scores = []
        for n, cid in enumerate(survivors):
            quote = pool_rows[cid]["logline"]
            entry = {c: {"score": 2 + (n % 3), "evidence": quote, "why": "w"} for c in ("novelty", "surprise", "usefulness", "brief_fit", "craft")}
            if n == 0:
                entry["craft"]["evidence"] = "цитата, которой нет в тексте"
            scores.append({"id": cid, **entry, "taboo_violation": False, "strongest": "novelty", "weakest": "craft"})
        sub("creative-studio:creative-director", block("scores", {"run_id": run, "scores": scores}))
        sub("creative-studio:audience-proxy", block("audience", {"run_id": run, "reactions": [{"id": c, "resonance": 3, "reaction": "r", "evidence": "e", "would_do": "skip"} for c in survivors]}))
        val = self.cli_json("studio.py", "validate", "--run", run)
        self.assertEqual(val["evidence_issues"], 1)
        pairs = self.cli_json("studio.py", "pairs", "--run", run)
        self.assertEqual(pairs["pairs"], 15)
        sched = json.loads((self.home / "runs" / run / "pairs.json").read_text())
        sub("creative-studio:creative-director", block("judgments", {"run_id": run, "judgments": [{"pair": p["pair"], "winner": "A", "why": "w"} for p in sched["pairs"]]}))
        rank = self.cli_json("studio.py", "rank", "--run", run)
        fins = rank["finalists"]
        self.assertEqual([f["label"] for f in fins], ["F1", "F2", "F3"])
        self.assertEqual(len({f["strategy"] for f in fins}), 3, "finalists should come from different strategies")
        sub("creative-studio:editor", block("versions", {"run_id": run, "finalists": [
            {"id": f["id"], "label": f["label"], "versions": {v: {"title": f"{v} {f['label']}", "hook": "h", "verse": "v", "note": "n"} for v in ("safe", "bold", "director")}} for f in fins]}))
        report = self.cli("studio.py", "report", "--run", run)
        self.assertIn("Funnel", report)
        self.assertIn("Director's cut", report)

        # Stop hook after the presentation turn: statuses reconciled, no selection yet.
        self.hook("hook-stop", {"cwd": self.tmp.name, "last_assistant_message": report})
        statuses = {r["id"]: r["status"] for r in cs.read_jsonl(self.home / cs.LOG_NAME)}
        self.assertEqual(sorted(s for s in statuses.values() if s == "finalist"), ["finalist"] * 3)
        self.assertEqual(list(statuses.values()).count("filtered"), 2)

        # Selection turn.
        sel = {"run_id": run, "choice": "F2", "version": "bold", "reason": "точная бытовая деталь и смелая форма", "rejected": {"F1": "слишком мило"}}
        self.hook("hook-stop", {"cwd": self.tmp.name, "last_assistant_message": "Записал.\n" + block("selection", sel)})
        rows = {r["id"]: r for r in cs.read_jsonl(self.home / cs.LOG_NAME)}
        chosen = rows[fins[1]["id"]]
        self.assertEqual((chosen["status"], chosen["version"]), ("selected", "bold"))
        self.assertIn("точная бытовая деталь", chosen["reason"])
        self.assertIn("слишком мило", rows[fins[0]["id"]]["reason"])
        self.assertEqual(rows[fins[2]["id"]]["status"], "rejected")
        self.assertTrue(all(r["status"] != "candidate" for r in rows.values()))
        for field in ("id", "ts", "domain", "brief", "title", "text", "strategy", "operator", "scores", "status", "reason"):
            self.assertIn(field, chosen)
        taste = (self.home / "taste-profile.md").read_text(encoding="utf-8")
        self.assertIn(f"run {run}", taste)
        self.assertIn("preferred version: bold ×1", taste)
        # idempotent: a second Stop does not duplicate the journal entry
        self.hook("hook-stop", {"cwd": self.tmp.name, "last_assistant_message": block("selection", sel)})
        self.assertEqual((self.home / "taste-profile.md").read_text(encoding="utf-8").count(f"run {run}"), 1)
        # next session loads the learned taste even though the template part is still empty
        ctx = json.loads(self.cli("session_context.py", stdin="{}"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Taste learned from past choices", ctx)

        # A second run sees the first run's concepts as history.
        init2 = self.cli_json("studio.py", "init", stdin=json.dumps(brief, ensure_ascii=False))
        self.assertGreater(init2["memory_digest_items"], 0)
        ctx2 = (self.home / "runs" / init2["run_id"]).exists()
        self.assertTrue(ctx2)


if __name__ == "__main__":
    unittest.main()
