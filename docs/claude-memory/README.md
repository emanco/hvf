# Claude Code memory snapshot

This folder is a **snapshot** of the Claude Code auto-memory that lived at:

```
~/.claude/projects/-Users-<username>-dev-hvf/memory/
```

at the time of the last commit touching it. Claude reads/writes its real
memory at that runtime location — committing this copy lets the context
travel with the repo so a fresh checkout on another machine can be
"primed" with the prior session's notes.

## What's in here

- `MEMORY.md` — the index file Claude loads on every turn (one-line
  pointers to the other files).
- `feedback_*.md` — operational lessons learned (sampler quirks, NSSM
  recovery, MT5 IPC trap, news filter caveats, etc.). Most relevant when
  Claude is making changes to the bot.
- `project_*.md` — point-in-time observations about strategy state,
  performance, instrument lists. These age fast — verify against current
  code/DB before acting on them.

## How to restore on a new machine

After cloning the repo to `~/dev/hvf` on a new laptop:

```bash
mkdir -p ~/.claude/projects/-Users-<your-username>-dev-hvf/memory
cp docs/claude-memory/*.md \
   ~/.claude/projects/-Users-<your-username>-dev-hvf/memory/
```

Substitute `<your-username>` with your local macOS username (the path
encodes the project directory). On the original machine that's `emanuelemanco`.

Once restored, opening Claude Code in this repo will load `MEMORY.md`
automatically on the first turn of each session.

## How to keep this snapshot fresh

Memory updates during a session don't automatically sync here. Either:

1. Ask Claude to re-snapshot before committing: `please refresh
   docs/claude-memory/ from the live memory dir and commit`.
2. Or just run:

```bash
cp ~/.claude/projects/-Users-<username>-dev-hvf/memory/*.md docs/claude-memory/
git add docs/claude-memory/ && git commit -m "refresh memory snapshot"
```

The live memory is the source of truth between snapshots; this folder is
the portable archive.
