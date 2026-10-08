"""Shared helpers for creative-studio scripts.

Stdlib only: hooks and the MCP server import this module, and they must work on a
bare `python3` with no packages installed.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator

try:  # POSIX file locking; on Windows we fall back to a no-op lock.
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SEED_DATA = PLUGIN_ROOT / "data"
DOMAINS_DIR = PLUGIN_ROOT / "domains"
OPERATORS_DIR = PLUGIN_ROOT / "skills" / "diverge" / "operators"
DEFAULT_CONFIG = PLUGIN_ROOT / "config" / "studio.json"

LOG_NAME = "generation-log.jsonl"
STATUSES = ("candidate", "filtered", "rejected", "finalist", "selected")
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}


# --------------------------------------------------------------------------- paths

def _usable(value: str | None) -> bool:
    return bool(value) and "${" not in str(value)


def _derived_plugin_data() -> Path | None:
    """Mirror Claude Code's layout: cache/<mkt>/<plugin>/<ver> -> data/<plugin>-<mkt>."""
    parts = PLUGIN_ROOT.parts
    if "cache" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("cache")
    if len(parts) < i + 4:
        return None
    base = Path(*parts[:i])
    market, plugin = parts[i + 1], parts[i + 2]
    ident = re.sub(r"[^A-Za-z0-9_-]", "-", f"{plugin}@{market}")
    return base / "data" / ident


def resolve_home(cwd: str | None = None, plugin_data: str | None = None) -> Path:
    """Where mutable state (log, taste profile, brands, runs, caches) lives.

    Order: CREATIVE_STUDIO_HOME > <project>/.creative-studio > plugin data dir
    (explicit arg, CS_HOME set by the SessionStart hook, CLAUDE_PLUGIN_DATA,
    or derived from the cache layout) > <plugin>/data (dev checkout only).
    """
    env_home = os.environ.get("CREATIVE_STUDIO_HOME")
    if _usable(env_home):
        return Path(env_home).expanduser()
    project = Path(cwd or os.getcwd()) / ".creative-studio"
    if project.is_dir():
        return project
    for candidate in (plugin_data, os.environ.get("CS_HOME"), os.environ.get("CLAUDE_PLUGIN_DATA")):
        if _usable(candidate):
            return Path(candidate).expanduser()
    derived = _derived_plugin_data()
    if derived is not None:
        return derived
    return SEED_DATA


def ensure_home(home: Path) -> Path:
    """Create the state layout and seed templates on first use. Idempotent."""
    for sub in ("brand", "runs", "trend-snapshots", "cache", "cliche-bank"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    log = home / LOG_NAME
    if not log.exists():
        log.touch()
    taste = home / "taste-profile.md"
    if not taste.exists() and (SEED_DATA / "taste-profile.md").exists() and home != SEED_DATA:
        shutil.copyfile(SEED_DATA / "taste-profile.md", taste)
    return home


# -------------------------------------------------------------------------- config

def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(home: Path | None = None) -> dict:
    cfg = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if home is not None:
        user_cfg = home / "config.json"
        if user_cfg.exists():
            try:
                cfg = _deep_merge(cfg, json.loads(user_cfg.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                warn(f"ignoring malformed {user_cfg}: {exc}")
    return cfg


# ------------------------------------------------------------------------- helpers

def warn(msg: str) -> None:
    print(f"[creative-studio] {msg}", file=sys.stderr)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def concept_id(run_id: str, title: str, body: str) -> str:
    digest = hashlib.sha1(f"{run_id}|{norm_text(title)}|{norm_text(body)}".encode("utf-8")).hexdigest()
    return "c_" + digest[:10]


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, dump(obj) + "\n")


def atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Exclusive advisory lock; parallel SubagentStop hooks write the same log."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ----------------------------------------------------------------------------- log

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            warn(f"skipping malformed line in {path.name}")
    return rows


def upsert_log(home: Path, records: Iterable[dict]) -> int:
    """Insert or update records by `id`. Status never moves backwards
    (e.g. a late `candidate` write cannot undo `filtered`), except that
    `selected` and `rejected` are both final decisions taken after `finalist`."""
    records = [r for r in records if r.get("id")]
    if not records:
        return 0
    log = home / LOG_NAME
    with locked(log):
        rows = read_jsonl(log)
        index = {row.get("id"): i for i, row in enumerate(rows)}
        changed = 0
        for rec in records:
            if rec["id"] in index:
                row = rows[index[rec["id"]]]
                merged = dict(row)
                for key, value in rec.items():
                    if value is None:
                        continue
                    if key == "scores" and isinstance(value, dict):
                        merged["scores"] = {**(row.get("scores") or {}), **value}
                    elif key == "status":
                        old, new = row.get("status", "candidate"), value
                        if STATUS_RANK.get(new, 0) >= STATUS_RANK.get(old, 0) or (
                            old in ("finalist", "selected", "rejected") and new in ("selected", "rejected")
                        ):
                            merged["status"] = new
                    else:
                        merged[key] = value
                if merged != row:
                    rows[index[rec["id"]]] = merged
                    changed += 1
            else:
                rec.setdefault("status", "candidate")
                rec.setdefault("ts", now_iso())
                index[rec["id"]] = len(rows)
                rows.append(rec)
                changed += 1
        if changed:
            atomic_write(log, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return changed


# ------------------------------------------------------------------------ markdown

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal `key: value` frontmatter parser (lists as [a, b] or comma strings)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.split(" #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        elif value.lower() in ("true", "false"):
            meta[key.strip()] = value.lower() == "true"
        else:
            meta[key.strip()] = value.strip("'\"")
    return meta, text[m.end():]


def is_placeholder_line(line: str) -> bool:
    s = line.strip()
    return (
        not s
        or s.startswith(">")
        or s.startswith("<!--")
        or s.endswith("-->")
        or s.startswith("#")
        or s in ("-", "- ", "*", "—", "_TODO_", "TODO")
        or re.fullmatch(r"[-*]\s*(_.*_|\.\.\.|…|TODO.*)?", s) is not None
        or re.fullmatch(r"([-*]\s*)?\*\*[^*]+:?\*\*:?\s*(_.*_)?", s) is not None
        or re.fullmatch(r"\|[\s|:-]*\|", s) is not None
    )


def human_content(text: str, stop_marker: str = "<!-- cs:auto -->") -> str:
    """Lines a human actually wrote (template instructions, headings, empty
    `**Label:**` fields and auto-maintained sections are ignored).
    Empty string => the template is untouched."""
    if stop_marker in text:
        text = text.split(stop_marker, 1)[0]
    _, body = parse_frontmatter(text)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return "\n".join(l for l in body.splitlines() if not is_placeholder_line(l)).strip()


# ---------------------------------------------------------------- fenced cs blocks

BLOCK_RE = re.compile(r"```[^\n`]*?\bcs:([a-z_]+)[^\n]*\n(.*?)\n\s*```", re.S)


def extract_blocks(text: str) -> list[tuple[str, Any]]:
    """Find ```cs:<kind>``` (or ```json cs:<kind>```) fenced JSON blocks."""
    found = []
    for kind, body in BLOCK_RE.findall(text or ""):
        body = body.strip()
        try:
            found.append((kind, json.loads(body)))
        except json.JSONDecodeError:
            # Tolerate trailing commentary after the JSON object.
            try:
                obj, _ = json.JSONDecoder().raw_decode(body)
                found.append((kind, obj))
            except json.JSONDecodeError:
                warn(f"cs:{kind} block is not valid JSON; skipped")
    return found


def texts_from_transcript(path: str | None) -> list[str]:
    """Assistant text + SubagentHandback reports from a transcript JSONL."""
    if not path:
        return []
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return []
    out = []
    for row in read_jsonl(p):
        msg = row.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            out.append(content)
            continue
        for part in content or []:
            if part.get("type") == "text":
                out.append(part.get("text", ""))
            elif part.get("type") == "tool_use" and isinstance(part.get("input"), dict):
                message = part["input"].get("message")
                if isinstance(message, str):
                    out.append(message)
    return out


# --------------------------------------------------------------------------- runs

def runs_dir(home: Path) -> Path:
    return home / "runs"


def run_dir(home: Path, run_id: str) -> Path:
    return runs_dir(home) / run_id


def latest_run_id(home: Path) -> str | None:
    pointer = runs_dir(home) / "LATEST"
    if pointer.exists():
        rid = pointer.read_text(encoding="utf-8").strip()
        if rid and run_dir(home, rid).is_dir():
            return rid
    return None


def domain_pack(domain: str) -> dict:
    """Locate a domain pack; unknown domains run on the generic core."""
    slug = re.sub(r"[^a-z0-9-]", "-", (domain or "").strip().lower()) or "generic"
    path = DOMAINS_DIR / slug
    if not (path / "domain.md").exists():
        return {"slug": slug, "status": "generic", "path": None, "files": {}, "meta": {}}
    meta, _ = parse_frontmatter((path / "domain.md").read_text(encoding="utf-8"))
    files = {name: str(path / f"{name}.md") for name in ("domain", "craft", "cliche-bank") if (path / f"{name}.md").exists()}
    return {"slug": slug, "status": meta.get("status", "stub"), "path": str(path), "files": files, "meta": meta}


def list_domains() -> list[dict]:
    if not DOMAINS_DIR.is_dir():
        return []
    return [domain_pack(p.name) for p in sorted(DOMAINS_DIR.iterdir()) if p.is_dir() and not p.name.startswith("_")]


# ----------------------------------------------------------------- identity

def active_brand(home: Path, cfg: dict) -> tuple[str | None, Path | None]:
    """Active brand: CREATIVE_STUDIO_BRAND > config.active_brand > the only filled brand file."""
    brand_dir = home / "brand"
    name = os.environ.get("CREATIVE_STUDIO_BRAND") or cfg.get("active_brand")
    if name:
        path = brand_dir / (name if name.endswith(".md") else f"{name}.md")
        return (path.stem, path) if path.exists() else (path.stem, None)
    filled = [p for p in sorted(brand_dir.glob("*.md")) if not p.name.startswith("_") and human_content(p.read_text(encoding="utf-8"))]
    if len(filled) == 1:
        return filled[0].stem, filled[0]
    return None, None


def identity_context(home: Path, cfg: dict) -> dict:
    """Brand + taste text for prompts. Empty templates yield `neutral: True`."""
    out: dict[str, Any] = {"brand_name": None, "brand": "", "taste": "", "taste_journal": "", "neutral": True}
    name, path = active_brand(home, cfg)
    if path is not None:
        raw = path.read_text(encoding="utf-8")
        if human_content(raw):
            out.update(brand_name=name, brand=re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip())
    taste_path = home / "taste-profile.md"
    if taste_path.exists():
        raw = taste_path.read_text(encoding="utf-8")
        human = human_content(raw)
        if human:
            out["taste"] = re.sub(r"<!--.*?-->", "", raw.split("<!-- cs:auto -->", 1)[0], flags=re.S).strip()
        if "<!-- cs:auto -->" in raw:
            auto = raw.split("<!-- cs:auto -->", 1)[1]
            entries = re.findall(r"^- \d{4}-\d{2}-\d{2} .*?(?=^- \d{4}-\d{2}-\d{2} |^## |<!-- cs:signals|\Z)", auto, flags=re.M | re.S)
            limit = int(cfg.get("session_context", {}).get("journal_entries", 8))
            signals = ""
            m = re.search(r"<!-- cs:signals:start -->(.*?)<!-- cs:signals:end -->", auto, flags=re.S)
            if m and "no choices yet" not in m.group(1):
                signals = m.group(1).strip()
            if entries:
                out["taste_journal"] = ("Derived signals:\n" + signals + "\n\n" if signals else "") + \
                    "Recent choices (newest first):\n" + "\n".join(e.strip() for e in entries[:limit])
    out["neutral"] = not (out["brand"] or out["taste"] or out["taste_journal"])
    return out
