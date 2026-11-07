#!/usr/bin/env python3
"""Tests for brainstew-threads (threads.py): thread wikis that
latch onto a brainstew wiki, and the context tool.

Run with the system python (stdlib only):
    python3 -m unittest tests.test_threads -v

Everything runs against a fake brainstew root in a temp dir; the
real brainstew repo is never touched.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run_threads(*argv, root):
    return subprocess.run(
        [sys.executable, str(ROOT / "threads.py"), "--root", str(root),
         *argv],
        capture_output=True, text=True)


class ThreadsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bsthreads-test-"))
        self.root = self.tmp / "wiki-root"
        wiki = self.root / "wiki"
        for d in ("sources", "entities", "concepts", "synthesis"):
            (wiki / d).mkdir(parents=True)
        (wiki / "index.md").write_text(
            "# Wiki Index\n\n## Sources\n"
            "- [[test]] - A test source page.\n\n"
            "## Entities\n\n## Concepts\n\n## Synthesis\n")
        (wiki / "log.md").write_text("# Wiki Log\n")
        (self.root / "raw").mkdir()
        (self.root / "raw" / "test.txt").write_text("test source\n")
        (wiki / "sources" / "test.md").write_text(
            "---\ntitle: Test Source\ntype: source\n"
            "summary: A test source page.\n"
            "sources: [raw/test.txt]\nupdated: 2026-11-07\n---\n\n"
            "The test source.\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _turn(self, thread, question, answer):
        out = run_threads("log", "--thread", thread, "--role", "Q",
                          "--text", question, root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        out = run_threads("log", "--thread", thread, "--role", "A",
                          "--text", answer, root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)

    def _new(self, name="website", rules="Answer in one sentence.",
             source=None):
        argv = ["new", name, "--rules", rules]
        if source:
            argv += ["--source", source]
        out = run_threads(*argv, root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def test_new_creates_thread_wiki_and_logs_it(self):
        self._new()
        tdir = self.root / "wiki" / "threads" / "website"
        self.assertTrue((tdir / "thread.json").is_file())
        record = json.loads((tdir / "thread.json").read_text())
        self.assertEqual(record["rules"], "Answer in one sentence.")
        self.assertTrue((tdir / "rules.md").is_file())
        self.assertTrue((tdir / "facts.md").is_file())
        self.assertTrue((tdir / "history.md").is_file())
        log = (self.root / "wiki" / "log.md").read_text()
        self.assertIn("## [", log)
        self.assertIn("edit | thread website created", log)
        # No page was created, so the index is untouched.
        index = (self.root / "wiki" / "index.md").read_text()
        self.assertNotIn("website", index)

    def test_log_note_and_context(self):
        self._new()
        self._turn("website", "What is the project deadline?", "Friday.")
        self._turn("website", "What colour should the homepage be?",
                   "Blue.")
        self._turn("website", "What is 6 times 7?", "42.")
        out = run_threads("note", "--thread", "website",
                          "--text", "Deadline is Friday.", root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        out = run_threads("context", "--thread", "website",
                          "--query", "deadline", "--recent", "1",
                          root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        # Rules, facts, the recent turn (6x7), and the matching
        # older turn (deadline) — but not the homepage turn.
        self.assertIn("Answer in one sentence.", out.stdout)
        self.assertIn("Deadline is Friday.", out.stdout)
        self.assertIn("What is 6 times 7?", out.stdout)
        self.assertIn("What is the project deadline?", out.stdout)
        self.assertIn("Friday.", out.stdout)
        self.assertNotIn("What colour should the homepage be?",
                         out.stdout)

    def test_context_includes_matching_wiki_pages(self):
        self._new()
        (self.root / "wiki" / "concepts" / "deadline-policy.md").write_text(
            "---\ntitle: Deadline Policy\ntype: concept\n"
            "summary: How deadlines are set.\n"
            "sources: [test]\nupdated: 2026-11-07\n---\n\n"
            "Every project has a deadline, set on Friday.\n")
        out = run_threads("context", "--thread", "website",
                          "--query", "deadline", root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("--- wiki pages", out.stdout)
        self.assertIn("[[deadline-policy]]", out.stdout)

    def test_publish_writes_lint_clean_page(self):
        self._new(source="raw/test.txt")
        self._turn("website", "What is the project deadline?", "Friday.")
        out = run_threads("note", "--thread", "website",
                          "--text", "Deadline is Friday.", root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        out = run_threads("publish", "--thread", "website",
                          root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "thread-website")
        page = self.root / "wiki" / "synthesis" / "thread-website.md"
        self.assertTrue(page.is_file())
        text = page.read_text()
        # Frontmatter a brainstew lint would accept.
        self.assertIn("title: Thread website", text)
        self.assertIn("type: synthesis", text)
        self.assertIn("sources: [raw/test.txt]", text)
        self.assertIn("updated: ", text)
        self.assertIn("Answer in one sentence.", text)
        self.assertIn("Deadline is Friday.", text)
        # The page links only to the hub, a real page — no broken
        # links, and it is not an orphan: the hub links back.
        self.assertIn("[[threads]]", text)
        self.assertEqual(text.count("[["), 1)
        hub = self.root / "wiki" / "synthesis" / "threads.md"
        self.assertTrue(hub.is_file())
        self.assertIn("[[thread-website]]", hub.read_text())
        index = (self.root / "wiki" / "index.md").read_text()
        self.assertIn("- [[thread-website]] -", index)
        self.assertIn("- [[threads]] -", index)
        self.assertIn("## Synthesis", index)
        log = (self.root / "wiki" / "log.md").read_text()
        self.assertIn("edit | thread website published", log)

    def test_publish_refuses_without_source(self):
        self._new()
        out = run_threads("publish", "--thread", "website",
                          root=self.root)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("valid source", out.stderr)
        page = self.root / "wiki" / "synthesis" / "thread-website.md"
        self.assertFalse(page.exists())

    def test_new_refuses_outside_brainstew(self):
        bare = self.tmp / "not-a-wiki"
        bare.mkdir()
        out = run_threads("new", "x", root=bare)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("not a brainstew wiki", out.stderr)

    def test_list(self):
        self._new("alpha", rules="Be brief.")
        self._new("beta", rules="Be thorough.")
        out = run_threads("list", root=self.root)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("alpha — rules: Be brief.", out.stdout)
        self.assertIn("beta — rules: Be thorough.", out.stdout)


if __name__ == "__main__":
    unittest.main()
