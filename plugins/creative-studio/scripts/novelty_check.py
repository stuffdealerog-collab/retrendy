#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["fastembed>=0.4", "numpy"]
# ///
"""Embedding-based novelty filter for creative-studio.

Every concept in the pool is compared with three reference sets:
  * bank      - the domain cliché bank (+ local additions in <home>/cliche-bank/)
  * baseline  - the run's "predictable answers" (pre-mortem by cliche-hunter and
                the high-probability "head" samples the generators threw away)
  * history   - the last N concepts this studio generated in the same domain
and then duplicates inside the pool are collapsed. Output is JSON with a
machine-readable reason for every rejection.

Backends: fastembed (ONNX, default) > sentence-transformers > lexical fallback
(char n-grams; cross-lingual paraphrases are NOT caught in that mode, and the
output says `"degraded": true`).

Examples:
  novelty_check.py --run r_20261008_1640_ab12
  novelty_check.py --domain lyrics --text "Dancing in the rain under city lights"
  novelty_check.py --domain lyrics --pool tests/fixtures/pool.json --history-file tests/fixtures/history.jsonl
  novelty_check.py --warmup
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_common as cs  # noqa: E402

ITEM_RE = re.compile(r"^\s*[-*]\s+\*\*([A-Z][A-Z0-9]*-\d+)\*\*\s*(\{[a-z, ]+\})?\s*(.+?)\s*$")


# ------------------------------------------------------------------ references

def parse_bank(path: Path, source: str = "bank") -> list[dict]:
    """`- **LY-001** {tag} text / variant` lines; `## ` headings are categories."""
    if not path or not path.exists():
        return []
    items, category = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        ref_id, tags, text = m.group(1), (m.group(2) or "").strip("{} "), m.group(3)
        variants = [v.strip() for v in re.split(r"\s+/\s+", text) if v.strip()]
        items.append({
            "source": source, "ref_id": ref_id, "category": category, "text": text,
            "tags": [t.strip() for t in tags.split(",") if t.strip()], "variants": variants,
        })
    return items


def load_bank(domain: str, home: Path) -> list[dict]:
    pack = cs.domain_pack(domain)
    refs = []
    if pack["files"].get("cliche-bank"):
        refs += parse_bank(Path(pack["files"]["cliche-bank"]))
    refs += parse_bank(home / "cliche-bank" / f"{pack['slug']}.md")
    return refs


def load_baseline(run_path: Path | None, extra_file: str | None) -> list[dict]:
    items = []
    for path in filter(None, [run_path / "baseline.json" if run_path else None, Path(extra_file) if extra_file else None]):
        data = cs.read_json(path, {}) or {}
        for i, text in enumerate(data.get("items", []), 1):
            text = text.get("text") if isinstance(text, dict) else text
            if text:
                items.append({"source": "baseline", "ref_id": f"BL-{i:03d}", "text": text, "variants": [text], "tags": []})
    return items


def concept_text(row: dict) -> str:
    parts = [row.get("title"), row.get("logline"), row.get("concept") or row.get("text")]
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())


def load_history(home: Path, domain: str, run_id: str | None, window: int, same_domain: bool,
                 history_file: str | None) -> list[dict]:
    rows = cs.read_jsonl(Path(history_file)) if history_file else cs.read_jsonl(home / cs.LOG_NAME)
    rows = [r for r in rows if r.get("run_id") != run_id and (not same_domain or r.get("domain") == domain)]
    rows.sort(key=lambda r: r.get("ts", ""))
    out = []
    for r in rows[-window:] if window else []:
        text = concept_text(r)
        core = ". ".join(p.strip().rstrip(".") for p in (r.get("title"), r.get("logline")) if p and p.strip())
        if text:
            out.append({"source": "history", "ref_id": r.get("id"), "run_id": r.get("run_id"), "text": text,
                        "variants": [text] + ([core] if core and core != text else []), "tags": [], "status": r.get("status")})
    return out


# -------------------------------------------------------------------- backends

class Lexical:
    """Char 3-gram cosine. Catches near-verbatim repeats only."""
    kind, name, model = "lexical", "lexical", "char-3gram"

    @staticmethod
    def _vec(text: str) -> Counter:
        t = f"  {cs.norm_text(text)}  "
        return Counter(t[i:i + 3] for i in range(len(t) - 2))

    def matrix(self, a: list[str], b: list[str]) -> list[list[float]]:
        va, vb = [self._vec(x) for x in a], [self._vec(x) for x in b]
        na = [math.sqrt(sum(v * v for v in x.values())) or 1.0 for x in va]
        nb = [math.sqrt(sum(v * v for v in x.values())) or 1.0 for x in vb]
        out = []
        for x, nx in zip(va, na):
            out.append([sum(c * y.get(g, 0) for g, c in x.items()) / (nx * ny) for y, ny in zip(vb, nb)])
        return out


class Semantic:
    kind = "semantic"

    def __init__(self, name: str, model: str, encode, cache_path: Path):
        self.name, self.model, self._encode = name, model, encode
        self._db = sqlite3.connect(str(cache_path))
        self._db.execute("CREATE TABLE IF NOT EXISTS emb (model TEXT, h TEXT, v BLOB, PRIMARY KEY (model, h))")

    def embed(self, texts: list[str]):
        import numpy as np
        keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
        found = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = f"SELECT h, v FROM emb WHERE model=? AND h IN ({','.join('?' * len(chunk))})"
            for h, blob in self._db.execute(q, [self.model, *chunk]):
                found[h] = np.frombuffer(blob, dtype=np.float32)
        missing = [(k, t) for k, t in zip(keys, texts) if k not in found]
        if missing:
            uniq = dict(missing)
            vecs = self._encode(list(uniq.values()))
            rows = []
            for k, v in zip(uniq.keys(), vecs):
                v = np.asarray(v, dtype=np.float32)
                v = v / (np.linalg.norm(v) or 1.0)
                found[k] = v
                rows.append((self.model, k, array.array("f", v.tolist()).tobytes()))
            self._db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?, ?)", rows)
            self._db.commit()
        return np.stack([found[k] for k in keys]) if keys else np.zeros((0, 1), dtype=np.float32)

    def matrix(self, a: list[str], b: list[str]):
        if not a or not b:
            return [[0.0] * len(b) for _ in a]
        return (self.embed(a) @ self.embed(b).T).tolist()


def make_backend(cfg: dict, home: Path, requested: str, lite: bool):
    model = cfg["lite_model"] if lite else cfg["model"]
    cache_dir = Path(cfg.get("model_cache_dir") or home / "cache" / "models").expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    emb_cache = home / "cache" / "embeddings.sqlite"
    errors = []
    if requested in ("auto", "fastembed"):
        try:
            from fastembed import TextEmbedding
            try:
                engine = TextEmbedding(model, cache_dir=str(cache_dir), local_files_only=True)
            except Exception:  # not downloaded yet
                engine = TextEmbedding(model, cache_dir=str(cache_dir))
            return Semantic("fastembed", model, lambda xs: list(engine.embed(xs, batch_size=32)), emb_cache), errors
        except Exception as exc:  # ImportError, network, unsupported model
            errors.append(f"fastembed: {type(exc).__name__}: {exc}")
    if requested in ("auto", "sentence-transformers"):
        try:
            from sentence_transformers import SentenceTransformer
            st = SentenceTransformer(model, cache_folder=str(cache_dir))
            return Semantic("sentence-transformers", model,
                            lambda xs: st.encode(xs, normalize_embeddings=True), emb_cache), errors
        except Exception as exc:
            errors.append(f"sentence-transformers: {type(exc).__name__}: {exc}")
    return Lexical(), errors


# ---------------------------------------------------------------------- checks

SENT_SPLIT = re.compile(r"(?<=[.!?…;])\s+")


def facets(c: dict) -> list[tuple[str, str]]:
    """Views of one concept that are compared separately (max wins).
    A long description dilutes cosine against a short cliché phrase, so the
    core (title + logline), the logline and each sentence are checked too."""
    title, logline = (c.get("title") or "").strip(), (c.get("logline") or "").strip()
    body = (c.get("concept") or c.get("text") or "").strip()
    views = [("full", concept_text(c)), ("core", ". ".join(p.rstrip(".") for p in (title, logline) if p)), ("logline", logline)]
    views += [(f"sentence {i}", s.strip()) for i, s in enumerate(SENT_SPLIT.split(body), 1) if len(s.strip()) >= 15][:6]
    seen, out = set(), []
    for name, text in views:
        if text and text not in seen:
            seen.add(text)
            out.append((name, text))
    return out


def _flatten(refs: list[dict]) -> tuple[list[str], list[dict]]:
    flat, owner = [], []
    for ref in refs:
        for variant in ref["variants"]:
            flat.append(variant)
            owner.append(ref)
    return flat, owner


IDEA_FACETS = ("full", "core", "logline")


def concept_matches(backend, pool: list[dict], refs: list[dict], k: int = 2, idea_only: bool = False) -> list[list[tuple[float, dict, str]]]:
    """For each concept: the k closest distinct references as (sim, ref, facet),
    max over the concept's facets (or only the idea-level ones) and each reference's variants."""
    flat, owner = _flatten(refs)
    if not pool or not flat:
        return [[] for _ in pool]
    rows, row_owner = [], []
    for ci, c in enumerate(pool):
        for name, text in facets(c):
            if idea_only and name not in IDEA_FACETS:
                continue
            rows.append(text)
            row_owner.append((ci, name))
    best: list[dict[int, tuple[float, dict, str]]] = [{} for _ in pool]
    for (ci, facet), row in zip(row_owner, backend.matrix(rows, flat)):
        slot = best[ci]
        for sim, ref in zip(row, owner):
            key = id(ref)
            if key not in slot or sim > slot[key][0]:
                slot[key] = (float(sim), ref, facet)
    return [sorted(slot.values(), key=lambda x: -x[0])[:k] for slot in best]


def best_matches(backend, texts: list[str], refs: list[dict]) -> list[tuple[float, dict | None]]:
    """Plain text vs references (used for sample lines)."""
    flat, owner = _flatten(refs)
    if not texts:
        return []
    if not flat:
        return [(0.0, None) for _ in texts]
    out = []
    for row in backend.matrix(texts, flat):
        j = max(range(len(row)), key=row.__getitem__)
        out.append((float(row[j]), owner[j]))
    return out


LAST_WORD_RE = re.compile(r"([\w'-]+)\W*$", re.U)


def _stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    return w[:-1] if len(w) >= 5 else w


def rhyme_warnings(sample: str, rhyme_refs: list[dict]) -> list[dict]:
    """Flag banned rhyme pairs at line ends (lexical; stems are approximate)."""
    ends = []
    for line in (sample or "").splitlines():
        m = LAST_WORD_RE.search(line.strip())
        if m:
            ends.append(_stem(m.group(1)))
    out = []
    for ref in rhyme_refs:
        words = {_stem(w) for w in re.split(r"[\s/—–,-]+", ref["text"]) if len(w) > 1}
        hit = sorted({e for e in ends if any(e.startswith(w) or w.startswith(e) for w in words if len(w) >= 3)})
        if len(hit) >= 2:
            out.append({"type": "rhyme", "ref_id": ref["ref_id"], "text": ref["text"], "line_ends": hit})
    return out


def collage_of(bank_hits: list[tuple[float, dict, str]], thr: dict) -> bool:
    """Two different clichés both nearby: each alone is under the hard threshold,
    together they are the idea. top1 >= soft and top2 >= collage_second."""
    return (len(bank_hits) >= 2 and thr.get("collage_second") is not None
            and bank_hits[0][0] >= thr["soft"] and bank_hits[1][0] >= thr["collage_second"])


def check(pool: list[dict], refs: dict[str, list[dict]], backend, thr: dict, line_cfg: dict) -> dict:
    # {rhyme} entries are lexical line-end checks; {structure} entries describe form and
    # match any concept that describes its own chorus, so cliche-hunter judges those.
    concept_refs = {src: [r for r in items if not {"rhyme", "structure"} & set(r["tags"])] for src, items in refs.items()}
    per_source = {src: concept_matches(backend, pool, items, 2) for src, items in concept_refs.items() if items}
    # The collage rule looks only at idea-level facets: one sentence describing the mechanics is weak evidence.
    bank_idea = concept_matches(backend, pool, concept_refs.get("bank", []), 2, idea_only=True)
    kept, filtered = [], []
    for i, c in enumerate(pool):
        best_sim, best_ref, best_facet = 0.0, None, None
        for src, matches in per_source.items():
            if matches[i] and matches[i][0][0] > best_sim:
                best_sim, best_ref, best_facet = matches[i][0]
        entry = {"id": c["id"], "title": c.get("title", ""), "branch": c.get("branch"),
                 "strategy": c.get("strategy"), "p": c.get("p")}
        match = None
        if best_ref is not None:
            match = {"source": best_ref["source"], "ref_id": best_ref["ref_id"], "facet": best_facet,
                     "text": best_ref["text"][:200], "sim": round(best_sim, 3)}
            if best_ref.get("run_id"):
                match["run_id"] = best_ref["run_id"]
        if best_ref is not None and best_sim >= thr["hard"]:
            code = {"bank": "cliche", "baseline": "predictable", "history": "repeat"}[best_ref["source"]]
            what = {"cliche": f"cliché {best_ref['ref_id']}",
                    "predictable": "a predictable answer to this brief",
                    "repeat": f"earlier concept {best_ref['ref_id']} (run {best_ref.get('run_id')})"}[code]
            filtered.append({**entry, "status": "filtered", "reason_code": code, "match": match,
                             "reason": f"Its {best_facet} is too close to {what}: «{match['text'][:90]}» "
                                       f"(cos {best_sim:.2f} ≥ {thr['hard']:.2f})"})
        elif collage_of(bank_idea[i], thr):
            (s1, r1, f1), (s2, r2, f2) = bank_idea[i][:2]
            filtered.append({**entry, "status": "filtered", "reason_code": "cliche_collage", "match": match,
                             "second_match": {"source": "bank", "ref_id": r2["ref_id"], "facet": f2, "text": r2["text"][:200], "sim": round(s2, 3)},
                             "reason": f"Cliché collage: {r1['ref_id']} «{r1['text'][:50]}» (cos {s1:.2f}) + "
                                       f"{r2['ref_id']} «{r2['text'][:50]}» (cos {s2:.2f}); two near-clichés glued together"})
        else:
            kept.append({**entry, "novelty_embed": round(1 - best_sim, 3), "nearest": match,
                         "soft_flag": best_sim >= thr["soft"], "_concept": c})

    # Collapse duplicates inside the pool: prefer tail ideas (low p), then the more novel one.
    # Pair similarity = max(full vs full, core vs core): detail-rich and terse versions of one idea still meet.
    kept.sort(key=lambda k: (k["p"] if isinstance(k.get("p"), (int, float)) else 1.0, -k["novelty_embed"]))
    if len(kept) > 1:
        fulls = [concept_text(k["_concept"]) for k in kept]
        cores = [dict(facets(k["_concept"])).get("core") or fulls[i] for i, k in enumerate(kept)]
        mf, mc = backend.matrix(fulls, fulls), backend.matrix(cores, cores)
        sims = [[max(a, b) for a, b in zip(rf, rc)] for rf, rc in zip(mf, mc)]
        survivors = []
        for i, k in enumerate(kept):
            dup = next((j for j in survivors if sims[i][j] >= thr["pool_duplicate"]), None)
            if dup is None:
                survivors.append(i)
            else:
                twin = kept[dup]
                filtered.append({"id": k["id"], "title": k["title"], "branch": k["branch"], "strategy": k["strategy"],
                                 "p": k["p"], "status": "filtered", "reason_code": "duplicate",
                                 "match": {"source": "pool", "ref_id": twin["id"], "text": twin["title"], "sim": round(sims[i][dup], 3)},
                                 "reason": f"Duplicate inside the pool of {twin['id']} «{twin['title'][:60]}» (cos {sims[i][dup]:.2f} ≥ {thr['pool_duplicate']:.2f})"})
        # Same idea or just the same brief? Embeddings can't tell in this band; cliche-hunter decides.
        near = [{"a": kept[i]["id"], "b": kept[j]["id"], "a_title": kept[i]["title"], "b_title": kept[j]["title"],
                 "sim": round(sims[i][j], 3)}
                for x, i in enumerate(survivors) for j in survivors[x + 1:] if thr["near_duplicate"] <= sims[i][j] < thr["pool_duplicate"]][:12]
        similarity = {"ids": [kept[i]["id"] for i in survivors],
                      "matrix": [[round(sims[i][j], 3) for j in survivors] for i in survivors]}
        kept = [kept[i] for i in survivors]
    else:
        near, similarity = [], {"ids": [k["id"] for k in kept], "matrix": [[1.0]] if kept else []}

    # Line-level warnings (domain packs with line_check): clichéd lines and rhymes.
    bank = refs.get("bank", [])
    sem_bank = [r for r in bank if not {"rhyme", "structure"} & set(r["tags"])]
    rhyme_bank = [r for r in bank if "rhyme" in r["tags"]]
    for k in kept:
        sample = k["_concept"].get("sample") or ""
        warnings = []
        if line_cfg.get("enabled") and sample:
            lines = [l.strip() for l in sample.splitlines() if len(l.strip()) >= line_cfg["min_chars"]]
            for line, (sim, ref) in zip(lines, best_matches(backend, lines, sem_bank)):
                if ref is not None and sim >= thr["line"]:
                    warnings.append({"type": "line", "line": line, "ref_id": ref["ref_id"], "text": ref["text"][:120], "sim": round(sim, 3)})
            warnings += rhyme_warnings(sample, rhyme_bank)
        k["line_warnings"] = warnings
        del k["_concept"]
    kept.sort(key=lambda k: -k["novelty_embed"])
    return {"kept": kept, "filtered": filtered, "near_duplicates": sorted(near, key=lambda n: -n["sim"]),
            "similarity": similarity}


# ------------------------------------------------------------------------- cli

def load_pool(path: Path, run_id: str | None) -> list[dict]:
    data = cs.read_json(path)
    if data is None:
        raise SystemExit(f"cannot read pool {path}")
    items = data.get("concepts", data) if isinstance(data, dict) else data
    pool = []
    for i, c in enumerate(items, 1):
        if isinstance(c, str):
            c = {"title": c}
        c = dict(c)
        c.setdefault("id", cs.concept_id(run_id or "adhoc", c.get("title", ""), c.get("concept", "")) if run_id else f"p{i:02d}")
        pool.append(c)
    return pool


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id: reads runs/<id>/pool.json + baseline.json, writes novelty.json")
    ap.add_argument("--pool", help="JSON list of concepts (title, logline, concept, sample, p)")
    ap.add_argument("--text", action="append", help="check a single idea (repeatable)")
    ap.add_argument("--domain", help="domain pack (default: from the run's brief)")
    ap.add_argument("--baseline", help="extra baseline JSON {items:[...]}")
    ap.add_argument("--history-file", help="use this JSONL instead of the generation log")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--threshold", type=float, help="override hard threshold")
    ap.add_argument("--backend", choices=["auto", "fastembed", "sentence-transformers", "lexical"])
    ap.add_argument("--lite", action="store_true", help="use the small model (faster, weaker on paraphrases)")
    ap.add_argument("--home", help="state directory (default: resolved like the hooks do)")
    ap.add_argument("--out", help="write the result JSON here too")
    ap.add_argument("--compact", action="store_true", help="omit kept-concept details on stdout")
    ap.add_argument("--warmup", action="store_true", help="download/load the model and embed all cliché banks")
    args = ap.parse_args(argv)

    home = cs.ensure_home(Path(args.home).expanduser() if args.home else cs.resolve_home())
    cfg = cs.load_config(home)["novelty"]
    backend, errors = make_backend(cfg, home, args.backend or cfg.get("backend", "auto"), args.lite)
    lexical = backend.kind == "lexical"

    if args.warmup:
        refs = [r for d in cs.list_domains() for r in load_bank(d["slug"], home)]
        if backend.kind == "semantic":
            backend.embed([v for r in refs for v in r["variants"]])
        print(cs.dump({"backend": backend.name, "model": backend.model, "embedded_bank_items": len(refs),
                       "degraded": lexical, "errors": errors}))
        return 0

    run_path, run_id, domain = None, None, args.domain
    if args.run:
        run_id = args.run
        run_path = cs.run_dir(home, run_id)
        brief = cs.read_json(run_path / "brief.json", {}) or {}
        domain = domain or brief.get("domain")
        pool = load_pool(run_path / "pool.json", run_id)
    elif args.pool:
        pool = load_pool(Path(args.pool), None)
    elif args.text:
        pool = [{"id": f"t{i:02d}", "title": t} for i, t in enumerate(args.text, 1)]
    else:
        ap.error("one of --run, --pool, --text, --warmup is required")
    domain = domain or "generic"
    pack = cs.domain_pack(domain)

    thr = {
        "hard": args.threshold or (cfg["lexical_threshold"] if lexical else cfg["threshold"]),
        "soft": cfg["lexical_soft_threshold"] if lexical else cfg["soft_threshold"],
        "pool_duplicate": cfg["lexical_threshold"] if lexical else cfg["pool_duplicate_threshold"],
        "line": cfg["lexical_threshold"] if lexical else cfg["line_threshold"],
        "collage_second": None if lexical else cfg.get("collage_second_threshold"),
        "near_duplicate": cfg["lexical_soft_threshold"] if lexical else cfg.get("near_duplicate_threshold", 0.75),
    }
    refs = {
        "bank": load_bank(domain, home),
        "baseline": load_baseline(run_path, args.baseline),
        "history": [] if args.no_history else load_history(home, pack["slug"], run_id, cfg["history_window"],
                                                           cfg.get("history_same_domain_only", True), args.history_file),
    }
    line_cfg = {"enabled": bool(pack["meta"].get("line_check")), "min_chars": cfg.get("line_min_chars", 12)}
    result = check(pool, refs, backend, thr, line_cfg)
    report = {
        "run_id": run_id, "domain": pack["slug"], "domain_pack": pack["status"],
        "backend": backend.name, "model": backend.model, "degraded": lexical,
        "thresholds": thr, "references": {k: len(v) for k, v in refs.items()},
        "counts": {
            "pool": len(pool), "kept": len(result["kept"]), "filtered": len(result["filtered"]),
            "by_reason": dict(Counter(f["reason_code"] for f in result["filtered"])),
            "soft_flagged": sum(1 for k in result["kept"] if k["soft_flag"]),
            "line_warnings": sum(len(k["line_warnings"]) for k in result["kept"]),
            "near_duplicate_pairs": len(result["near_duplicates"]),
        },
        **result,
    }
    if errors and lexical:
        report["backend_errors"] = errors
    if run_path:
        cs.write_json(run_path / "novelty.json", report)
    if args.out:
        cs.write_json(Path(args.out), report)
    shown = dict(report)
    shown.pop("similarity", None)  # kept in novelty.json for diversity-aware ranking, too long for stdout
    if args.compact:
        shown["kept"] = [{"id": k["id"], "title": k["title"], "novelty_embed": k["novelty_embed"],
                          "soft_flag": k["soft_flag"], "line_warnings": len(k["line_warnings"])} for k in report["kept"]]
    print(cs.dump(shown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
