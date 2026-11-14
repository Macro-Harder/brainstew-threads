# brainstew-threads

Thread wikis for [brainstew](https://github.com/Macro-Harder/brainstew): one wiki per agent/project, with a context tool that pulls only what matters.

A thread is one of an agent team's agents: a name, its own rules for its project, and its own history, all served by the one assistant. This add-on gives each thread a wiki of its own (rules, distilled facts, and the history page, which is the index) and a tool that returns only the context that matters for a question, so a long thread stays cheap to answer in.

## A DLC, not a fork

brainstew works fine without this. It is an add-on: drop it into a brainstew repo and it latches on; take it out and the wiki is untouched. It never changes brainstew itself and never writes to `raw/`.

What it adds, inside a brainstew repo:

- `wiki/threads/<name>/`: the thread wiki: `thread.json` (metadata, rules, source), `rules.md`, `facts.md`, `history.md` (every turn verbatim, in order). These live outside brainstew's four page folders, so `brainstew lint` and `brainstew search` never see them, and they can never break lint.
- `wiki/synthesis/thread-<name>.md`: only via `publish`: the thread as a proper brainstew page (rules + facts), listed in `wiki/index.md` under Synthesis and logged in `wiki/log.md`.
- Thread lifecycle events in `wiki/log.md`, using brainstew's `edit` verb.

See [INTEGRATION.md](INTEGRATION.md) for the full install and the AGENTS.md snippet.

## Quickstart

```bash
git clone https://github.com/Macro-Harder/brainstew
cd brainstew
cp /path/to/brainstew-threads/threads.py .
cp -r /path/to/brainstew-threads/.agents/skills/thread-wiki .agents/skills/

# One thread per project, with its rules
python3 threads.py new website --rules "Answer in one sentence." \
  --source raw/my-article.md

# Record a turn (question, then answer)
python3 threads.py log --thread website --role Q \
  --text "What is the project deadline?"
python3 threads.py log --thread website --role A --text "Friday."

# Record a fact worth keeping
python3 threads.py note --thread website --text "Deadline is Friday."

# Only the context that matters for a question
python3 threads.py context --thread website \
  --query "when is the deadline due?" --recent 3

# Put the thread into the wiki as a synthesis page (optional)
python3 threads.py publish --thread website --source raw/my-article.md
python -m brainstew lint
```

## How it works

`threads.py` is stdlib-only Python, no brainstew import: it reads the wiki directory directly, so it works on any brainstew-layout wiki.

- `new <name> --rules "..." [--source ...]`: create a thread wiki.
- `log --thread <name> --role Q|A --text "..."`: append a turn to the thread's history page.
- `note --thread <name> --text "..."`: append a distilled fact.
- `context --thread <name> --query "..." [--recent N]`: the thread's rules, its facts, the last N turns (default 3), older turns whose words match the question, and matching brainstew pages. The assistant reads this before answering; the tool narrows, the assistant makes the final call.
- `show --thread <name>`: print the whole thread wiki. `list`: list the threads.
- `publish --thread <name> [--source ...]`: write the thread as a synthesis page. It needs a valid source (a source-page slug or an existing `raw/` file); without one it refuses, because a page with no source would fail `brainstew lint`.

## License

Apache License 2.0. See `LICENSE`. Copyright 2026 J.P. Picard aka Macro-Harder.
