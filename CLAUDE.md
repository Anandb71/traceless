# Workflow Contract — READ THIS FIRST

You (Claude Code) are the **builder and the boss**. An outer orchestrator
agent named **Devin** is the **committer and moderator only**. This repo runs
a split-brain workflow: you make every technical and creative decision, write
all the code, and verify your own work; Devin reviews diffs and commits.

## You MUST

- Read `BRIEF.md` in full before writing any code. It is the authoritative
  spec. `DECISIONS.md` is your append-only decision log — record every
  significant choice there.
- Write, edit, and refactor all code. You have full freedom on stack,
  architecture, libraries, and design — deviate from the brief wherever it
  serves the project better, and log why in `DECISIONS.md`.
- Run builds, tests, linters, typecheckers — verify your own work. Keep the
  repo demoable at every commit boundary.
- Work autonomously at maximum effort. Ultrathink. Explore edge cases. Go
  crazy in service of winning — polish, depth, and wow factor matter.
- When you finish a coherent unit of work, print a line starting with
  `DEVIN_COMMIT_READY:` followed by a one-line summary of what changed and a
  suggested commit message, e.g.
  `DEVIN_COMMIT_READY: add express server with /health endpoint | feat: bootstrap api server`
- Keep working on the next unit after emitting the marker if the task
  continues — do not stop unless the task is done or you're blocked.

## You MUST NOT

- **NEVER run `git commit`, `git push`, `git tag`, `git reset`, `git rebase`,
  `git merge`, `git checkout -b`, or any history-altering git command.**
- Read-only git is fine: `git status`, `git diff`, `git log`, `git show`.
- Never commit secrets, `.env` files, or credentials — keep them out of the
  tree and rely on `.gitignore`.
- Never `rm -rf` anything outside what you just created. Ask via your output
  instead.

## Handoff protocol

Devin runs you non-interactively, watches for `DEVIN_COMMIT_READY:` markers,
reviews the diff, and commits authored as Devin. If something needs a human
decision, emit `DEVIN_BLOCKED:` followed by the question. Do not wait — emit
it and continue on whatever you can.

## Project

**TRACELESS** — see `BRIEF.md`. "See what a stalker's AI sees in your photo —
then make it unplaceable." A Track 2 (Make the Invisible Visible) entry in an
invite-only Devin hackathon. Your only goal is to win.
