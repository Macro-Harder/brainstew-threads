#!/usr/bin/env python3
"""brainstew-threads — thread wikis for brainstew (a DLC, not a fork).

One wiki per agent/project, with a context tool that pulls only what
matters. It latches onto a brainstew wiki and adds to it; brainstew
works fine without it, and it never touches brainstew itself.

What it adds, inside a brainstew repo (``--root``, default ``.``):

- ``wiki/threads/<name>/`` — one directory per thread (one agent,
  one project): ``thread.json`` (metadata + rules + source),
  ``rules.md``, ``facts.md`` (distilled facts worth keeping),
  ``history.md`` (the index: every turn verbatim, in order).
- ``wiki/synthesis/thread-<name>.md`` — only via ``publish``: the
  thread as a proper brainstew page (rules + facts), listed in
  ``wiki/index.md`` under Synthesis and logged in ``wiki/log.md``.

Rules it follows (brainstew's own):

- It never writes to ``raw/`` and never changes brainstew's code.
- It never creates a page outside the four page folders, so
  ``brainstew lint`` never sees the thread files — the thread wiki
  is invisible to lint and search, and can never break them.
- ``publish`` writes a real page, so it follows the page rules:
  frontmatter with title/type/summary/sources/updated, a valid
  source (a source-page slug or an existing ``raw/`` file), an
  index entry under Synthesis, and a log entry. Run
  ``python -m brainstew lint`` after publishing, as always.
- Log entries use brainstew's verbs (``edit`` for thread events).

Usage:
  threads.py new <name> --rules "..." [--source <slug-or-raw-path>]
  threads.py log --thread <name> --role Q|A --text "..."
  threads.py note --thread <name> --text "..."
  threads.py context --thread <name> --query "..." [--recent N]
  threads.py show --thread <name>
  threads.py list
  threads.py publish --thread <name> [--source <slug-or-raw-path>]

Stdlib only. No brainstew import: it reads the wiki directory
directly, so it works on any brainstew-layout wiki.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

VERSION = "0.1.0"

PAGE_DIRS = ("sources", "entities", "concepts", "synthesis")
LOG_VERBS = ("ingest", "query", "lint", "edit")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "that", "this", "these", "those", "it", "its", "is", "are",
    "was", "were", "be", "been", "what", "which", "who", "whom", "when",
    "where", "why", "how", "do", "does", "did", "can", "could", "should",
    "would", "will", "shall", "you", "your", "yours", "my", "me", "we",
    "our", "they", "their", "them", "he", "she", "his", "her", "i", "am",
    "as", "at", "by", "from", "not", "no", "yes", "if", "then",
    "than", "so", "such", "into", "about", "over", "under", "again",
    "please", "just", "also", "there", "here", "have", "has", "had",
}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return date.today().isoformat()


def _check_thread_name(name):
    """A thread is an agent's name, and it becomes a directory
    name, so it may only use safe characters."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name or ""):
        raise SystemExit(
            f"bad thread name {name!r}: use letters, digits, '-' or '_'")
    return name


def _keywords(text):
    """The meaningful words in a question: lowercased, at least 3
    letters, stopwords dropped."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _clean_scalar(text):
    """A frontmatter scalar for brainstew: no quotes, commas, or
    colons (its parser rejects them)."""
    return re.sub(r"[\",:]", " ", text or "").strip() or "(none)"


def _require_brainstew(root):
    """This is an add-on: it needs a brainstew wiki to latch onto."""
    wiki = Path(root) / "wiki"
    if not (wiki / "index.md").is_file() or not (wiki / "log.md").is_file():
        raise SystemExit(
            f"{root} is not a brainstew wiki (no wiki/index.md and "
            f"wiki/log.md). Run this inside a brainstew repo.")
    return wiki


def _thread_dir(wiki, name):
    return wiki / "threads" / name


def _load_record(wiki, name):
    path = _thread_dir(wiki, name) / "thread.json"
    if not path.exists():
        raise SystemExit(f"no such thread: {name}")
    return json.loads(path.read_text())


def _append_log(wiki, verb, title, details=None):
    """Append a lifecycle event to wiki/log.md. Per-turn history
    lives in the thread's own history.md, not here — log.md
    records thread events (created, published), the way brainstew
    records operations."""
    lines = [f"## [{today()}] {verb} | {title}"]
    for d in (details or []):
        lines.append(f"- {d}")
    with (wiki / "log.md").open("a") as f:
        f.write("\n" + "\n".join(lines) + "\n")


def _append_history(wiki, name, kind, sender, at, text):
    """Append one turn to the thread's history page — the wiki's
    index, verbatim and in order."""
    tdir = _thread_dir(wiki, name)
    page = tdir / "history.md"
    if not page.exists():
        page.write_text(f"# History — {name}\n")
    with page.open("a") as f:
        f.write(f"\n## {'Q' if kind == 'Q' else 'A'} {sender} at {at}\n\n{text}\n")


def _parse_history(text):
    """Split a history page into sections, in order:
    {"kind": "Q"/"A", "from", "at", "text"}."""
    sections = []
    current = None
    for line in (text or "").splitlines():
        m = re.match(r"## ([QA]) (\S+) at (\S+)\s*$", line)
        if m:
            current = {"kind": m.group(1), "from": m.group(2),
                       "at": m.group(3), "text": ""}
            sections.append(current)
        elif current is not None:
            current["text"] += line + "\n"
    for s in sections:
        s["text"] = s["text"].strip()
    return sections


def _group_turns(sections):
    """Group Q/A sections into turns, in chronological order. An
    answer belongs to the most recent question that has no answer
    yet; a question without an answer is a turn on its own."""
    turns = []
    for s in sections:
        if s["kind"] == "Q":
            turns.append({"q": s, "a": None})
        elif turns and turns[-1]["q"] is not None and turns[-1]["a"] is None:
            turns[-1]["a"] = s
        else:
            # An answer with no question before it (history edited
            # by hand, or a section out of order): keep it as its
            # own turn rather than dropping it.
            turns.append({"q": None, "a": s})
    return turns


def _turn_text(turn):
    parts = []
    if turn.get("q"):
        parts.append(turn["q"]["text"])
    if turn.get("a"):
        parts.append(turn["a"]["text"])
    return "\n".join(parts)


def _print_turn(turn):
    if turn.get("q"):
        q = turn["q"]
        print(f"## Q {q['from']} at {q['at']}\n\n{q['text']}")
    if turn.get("a"):
        a = turn["a"]
        print(f"\n## A {a['from']} at {a['at']}\n\n{a['text']}")


def _valid_source(root, source):
    """A publish source must be a source-page slug or an existing
    raw/ file — the only things brainstew lint accepts."""
    if not source:
        return False
    wiki = Path(root) / "wiki"
    if (wiki / "sources" / f"{source}.md").is_file():
        return True
    if source.startswith("raw/") and (Path(root) / source).is_file():
        return True
    return False


def _wiki_pages(wiki, keys):
    """Brainstew pages whose title, summary, or body match the
    query keywords (scored like brainstew search: title 10,
    summary 5, body 1). Returns [(slug, title, summary, snippet)]
    best first, capped at 5."""
    found = []
    for folder in PAGE_DIRS:
        d = wiki / folder
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^title: (.*)$", text, re.M)
            title = m.group(1).strip() if m else path.stem
            m = re.search(r"^summary: (.*)$", text, re.M)
            summary = m.group(1).strip() if m else ""
            lowered = text.lower()
            score = 0
            for k in keys:
                score += 10 * title.lower().count(k)
                score += 5 * summary.lower().count(k)
                score += lowered.count(k)
            if score <= 0:
                continue
            snippet = ""
            for line in text.splitlines():
                if any(k in line.lower() for k in keys) and line.strip():
                    snippet = line.strip()
                    break
            found.append((score, path.stem, title, summary, snippet))
    found.sort(key=lambda f: -f[0])
    return [(slug, title, summary, snippet)
            for _, slug, title, summary, snippet in found[:5]]


def cmd_new(args):
    wiki = _require_brainstew(args.root)
    name = _check_thread_name(args.name)
    tdir = _thread_dir(wiki, name)
    if (tdir / "thread.json").exists():
        raise SystemExit(f"thread {name} already exists")
    if args.source and not _valid_source(args.root, args.source):
        raise SystemExit(
            f"bad source {args.source!r}: use a source-page slug "
            f"or an existing raw/ file")
    tdir.mkdir(parents=True, exist_ok=True)
    record = {"thread": name, "created_at": utcnow(),
              "rules": args.rules or "",
              "source": args.source or ""}
    (tdir / "thread.json").write_text(json.dumps(record, indent=2))
    (tdir / "rules.md").write_text(
        f"# Rules — {name}\n\n{record['rules'] or '(none)'}\n")
    (tdir / "facts.md").write_text(f"# Facts — {name}\n")
    (tdir / "history.md").write_text(f"# History — {name}\n")
    _append_log(wiki, "edit", f"thread {name} created",
                [f"Rules: {record['rules'] or '(none)' }"])
    print(f"thread {name}")
    return 0


def cmd_log(args):
    wiki = _require_brainstew(args.root)
    name = _check_thread_name(args.thread)
    _load_record(wiki, name)
    _append_history(wiki, name, args.role, "agent", utcnow(), args.text)
    return 0


def cmd_note(args):
    wiki = _require_brainstew(args.root)
    name = _check_thread_name(args.thread)
    _load_record(wiki, name)
    page = _thread_dir(wiki, name) / "facts.md"
    if not page.exists():
        page.write_text(f"# Facts — {name}\n")
    with page.open("a") as f:
        f.write(f"\n- {utcnow()}: {args.text}\n")
    return 0


def cmd_context(args):
    """Only the context that matters for a question: the thread's
    rules, its distilled facts, the recent turns, older turns
    whose words match the question, and matching brainstew pages.
    The assistant reads this instead of the whole history, so a
    long thread stays cheap to answer in."""
    wiki = _require_brainstew(args.root)
    name = _check_thread_name(args.thread)
    record = _load_record(wiki, name)
    tdir = _thread_dir(wiki, name)
    print(f"thread {record['thread']} — context for: "
          f"{args.query or '(no question — recent turns only)'}")
    print(f"rules: {record.get('rules') or '(none)'}")
    facts = tdir / "facts.md"
    if facts.exists() and facts.read_text().strip():
        print("--- facts")
        print(facts.read_text().rstrip())
    history = tdir / "history.md"
    sections = _parse_history(history.read_text()) if history.exists() else []
    turns = _group_turns(sections)
    recent = turns[-args.recent:] if args.recent > 0 else []
    if recent:
        print(f"--- recent (last {len(recent)} turn(s))")
        for t in recent:
            _print_turn(t)
    keys = _keywords(args.query)
    if keys:
        scored = []
        for t in turns:
            if t in recent:
                continue
            hits = keys & _keywords(_turn_text(t))
            if hits:
                scored.append((len(hits), t))
        scored.sort(key=lambda s: -s[0])
        if scored:
            print(f"--- matching \"{args.query}\" "
                  f"({len(scored)} older turn(s))")
            for _, t in scored:
                _print_turn(t)
        pages = _wiki_pages(wiki, keys)
        if pages:
            print("--- wiki pages")
            for slug, title, summary, snippet in pages:
                print(f"- [[{slug}]] - {title}"
                      + (f": {summary}" if summary else "")
                      + (f" — {snippet}" if snippet else ""))
    return 0


def cmd_show(args):
    wiki = _require_brainstew(args.root)
    name = _check_thread_name(args.thread)
    record = _load_record(wiki, name)
    tdir = _thread_dir(wiki, name)
    print(f"thread {record['thread']} (created "
          f"{record.get('created_at', '?')})")
    print(f"rules: {record.get('rules') or '(none)'}")
    for page in ("facts.md", "history.md"):
        path = tdir / page
        if path.exists() and path.read_text().strip():
            print(f"--- {page}")
            print(path.read_text().rstrip())
    return 0


def cmd_list(args):
    wiki = _require_brainstew(args.root)
    base = wiki / "threads"
    if not base.is_dir():
        print("(no threads)")
        return 0
    for tdir in sorted(base.iterdir()):
        if not (tdir / "thread.json").is_file():
            continue
        record = json.loads((tdir / "thread.json").read_text())
        print(f"{record['thread']} — rules: "
              f"{record.get('rules') or '(none)'}")
    return 0


def _index_add(wiki, slug, summary):
    """List a page in wiki/index.md under its section. The heading
    order is never touched, and a slug is listed exactly once."""
    index = wiki / "index.md"
    text = index.read_text()
    bullet = f"- [[{slug}]] - {summary}\n"
    if f"[[{slug}]]" in text:
        return
    heading = {"sources": "Sources", "entities": "Entities",
               "concepts": "Concepts", "synthesis": "Synthesis"}
    folder = "synthesis"
    lines = text.splitlines(keepends=True)
    out = []
    in_section = False
    inserted = False
    for line in lines:
        if line.startswith("## "):
            in_section = line[3:].strip() == heading[folder]
        if in_section and not inserted and line.strip() == "":
            out.append(bullet)
            inserted = True
        out.append(line)
    if not inserted:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(bullet)
    index.write_text("".join(out))


def _rebuild_hub(wiki):
    """The threads hub page (wiki/synthesis/threads.md): a synthesis
    page that [[links]] to every published thread page, and that
    every thread page links back to. Without it, a published thread
    page is an orphan (nothing links to it) and `brainstew lint`
    warns. The hub's sources are the union of the threads' sources.
    The add-on owns this page entirely."""
    threads = []
    sources = []
    for path in sorted((wiki / "synthesis").glob("thread-*.md")):
        text = path.read_text()
        m = re.search(r"^title: (.*)$", text, re.M)
        title = m.group(1).strip() if m else path.stem
        m = re.search(r"^summary: (.*)$", text, re.M)
        summary = m.group(1).strip() if m else ""
        m = re.search(r"^sources: \[(.*)\]$", text, re.M)
        for s in (m.group(1).split(",") if m else []):
            s = s.strip()
            if s and s not in sources:
                sources.append(s)
        threads.append((path.stem, title, summary))
    if not threads:
        return
    body = "# Threads\n\nPublished thread wikis.\n\n"
    for slug, title, summary in threads:
        body += f"- [[{slug}]] - {title}"
        if summary:
            body += f": {summary}"
        body += "\n"
    hub = wiki / "synthesis" / "threads.md"
    hub.write_text(
        "---\n"
        "title: Threads\n"
        "type: synthesis\n"
        "summary: Published thread wikis\n"
        f"sources: [{', '.join(sources)}]\n"
        f"updated: {today()}\n"
        "---\n\n" + body)
    _index_add(wiki, "threads", "Published thread wikis")


def cmd_publish(args):
    """Put a thread into the brainstew wiki proper, as a synthesis
    page. Explicit and optional — the thread works without it.
    Follows the page rules exactly: frontmatter, a valid source,
    an index entry under Synthesis, and a log entry."""
    wiki = _require_brainstew(args.root)
    root = Path(args.root)
    name = _check_thread_name(args.thread)
    record = _load_record(wiki, name)
    source = args.source or record.get("source") or ""
    if not _valid_source(root, source):
        raise SystemExit(
            "publish needs a valid source (a source-page slug or an "
            "existing raw/ file): pass --source, or create the thread "
            "with --source. Without one, the page would fail "
            "`brainstew lint`.")
    slug = f"thread-{name}"
    summary = _clean_scalar(
        args.summary or record.get("rules") or f"Thread {name}")
    page = wiki / "synthesis" / f"{slug}.md"
    tdir = _thread_dir(wiki, name)
    facts = ""
    facts_path = tdir / "facts.md"
    if facts_path.exists():
        facts = facts_path.read_text().strip()
    body = (f"# Thread {name}\n\n"
            f"## Rules\n\n{record.get('rules') or '(none)'}\n")
    if facts:
        body += f"\n{facts}\n"
    body += (f"\nFull history: wiki/threads/{name}/history.md\n"
             f"Part of [[threads]].\n")
    page.write_text(
        "---\n"
        f"title: Thread {name}\n"
        "type: synthesis\n"
        f"summary: {summary}\n"
        f"sources: [{source}]\n"
        f"updated: {today()}\n"
        "---\n\n" + body)
    _index_add(wiki, slug, summary)
    _rebuild_hub(wiki)
    _append_log(wiki, "edit", f"thread {name} published",
                [f"Page: [[{slug}]]"])
    print(slug)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="threads.py",
        description="Thread wikis for brainstew: one wiki per agent, "
                    "with a context tool that pulls only what matters.")
    p.add_argument("--root", default=".",
                   help="brainstew root (default: current dir)")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("new", help="create a thread wiki")
    q.add_argument("name")
    q.add_argument("--rules", default="")
    q.add_argument("--source", default="")

    q = sub.add_parser("log", help="append a turn to a thread's history")
    q.add_argument("--thread", required=True)
    q.add_argument("--role", choices=["Q", "A"], required=True)
    q.add_argument("--text", required=True)

    q = sub.add_parser("note", help="record a fact in a thread's wiki")
    q.add_argument("--thread", required=True)
    q.add_argument("--text", required=True)

    q = sub.add_parser("context", help="only the context that matters for a question")
    q.add_argument("--thread", required=True)
    q.add_argument("--query", default="")
    q.add_argument("--recent", type=int, default=3)

    q = sub.add_parser("show", help="print a thread's wiki")
    q.add_argument("--thread", required=True)

    sub.add_parser("list", help="list threads")

    q = sub.add_parser("publish", help="put a thread into the wiki as a synthesis page")
    q.add_argument("--thread", required=True)
    q.add_argument("--source", default="")
    q.add_argument("--summary", default="")

    args = p.parse_args(argv)
    return {
        "new": cmd_new, "log": cmd_log, "note": cmd_note,
        "context": cmd_context, "show": cmd_show, "list": cmd_list,
        "publish": cmd_publish,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
