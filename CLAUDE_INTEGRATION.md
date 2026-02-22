# Claude ↔ Cursor Integration Guide

This file defines how Claude Code and Cursor AI divide work, hand off tasks,
and manage context limits on the music-scheduler project.

---

## Roles at a Glance

| Claude Code | Cursor |
|-------------|--------|
| Multi-file coordinated changes | Single-file edits and inline tweaks |
| Backend logic (engine/, app.py routes) | HTML/CSS/JS UI polish |
| Git operations (commit, push, branch) | Repetitive boilerplate / renaming |
| Cross-codebase research and analysis | Anything needing live visual feedback |
| Scheduling algorithm work | Formatting / style fixes |
| New API endpoints (route + template together) | Small isolated bug fixes in one file |
| HANDOFF.md updates | Can also update HANDOFF.md after its tasks |

**When in doubt:** if the task touches more than two files or requires reasoning
about how the whole system fits together, give it to Claude Code.

---

## Handoff Protocol: Claude → Cursor (Near-Automatic)

A Cursor rule (`.cursor/rules/handoff.mdc`) fires at every Cursor session start
and checks for `CURSOR_TASK.md`. If it contains a task, Cursor reads it and
begins working immediately — **you only need to switch windows.**

### What Claude does when handing off to Cursor:
1. Writes the task into `CURSOR_TASK.md` (specific files, what to change, why).
2. Updates `HANDOFF.md` with full session context.
3. Commits and pushes both files.
4. Tells you: "Handed off to Cursor — just open Cursor."

### What you do:
- Switch to Cursor. That's it. The rule reads `CURSOR_TASK.md` automatically.

### What Cursor does:
- Reads `CURSOR_TASK.md` and `CLAUDE.md` at session start.
- Announces the task and begins working.
- Clears `CURSOR_TASK.md` when done (replaces content with `# No pending task`).

---

## Handoff Protocol: Cursor → Claude

When Cursor finishes its portion or hits its own limits:

1. Cursor updates `HANDOFF.md` with what it changed and what remains.
2. Cursor clears `CURSOR_TASK.md` (if not already done).
3. User starts a new Claude Code session and says:
   "Read CLAUDE.md and HANDOFF.md, then continue."
4. Claude reads both files to restore full context before touching any code.

---

## Context Limit Management

### For Claude Code sessions
- Claude auto-compresses prior conversation context; new sessions inherit a summary.
- `CLAUDE.md` provides persistent project knowledge — Claude reads it at session start.
- `HANDOFF.md` provides point-in-time state — update it before ending any session.
- If a feature is large, scope each session to one sub-feature to keep context lean.

### Starting a new Claude Code session
Say: "Read CLAUDE.md and HANDOFF.md, then continue where we left off."
Claude will read both files before making any changes.

### Starting a new Cursor session
Just open Cursor. The `.cursor/rules/handoff.mdc` rule fires automatically
and checks `CURSOR_TASK.md`. If Claude left a task, Cursor will announce it
and start working. No copy-paste needed.

---

## File Responsibilities

| File | Owner | Purpose |
|------|-------|---------|
| `CLAUDE.md` | Both (Claude primary) | Long-lived project overview — stack, conventions, entity map, API surface |
| `CLAUDE_INTEGRATION.md` | Both | This file — workflow rules |
| `HANDOFF.md` | Both (whoever last worked) | Current state, next steps, files in play |
| `CURSOR_TASK.md` | Claude writes / Cursor clears | The specific task for Cursor's next session; auto-read by `.cursor/rules/handoff.mdc` |
| `.cursor/rules/handoff.mdc` | Claude (do not edit manually) | Cursor rule that auto-reads CURSOR_TASK.md at session start |

Rules for keeping files accurate:
- `CLAUDE.md` — update when: stack changes, new major feature added, conventions change.
- `HANDOFF.md` — update at the end of every work session, before any handoff.
- `CURSOR_TASK.md` — Claude writes a task here before handing off; Cursor clears it when done.
- Never let `HANDOFF.md` go stale. A stale handoff doc is worse than no doc.

---

## Quick Reference: What to Say

**To Claude Code (new session after limit):**
> "Read CLAUDE.md and HANDOFF.md, then continue where we left off."

**To Cursor (after Claude handoff):**
> Just open Cursor — the rule fires automatically and reads `CURSOR_TASK.md`.
> If it doesn't trigger: "Read CURSOR_TASK.md and CLAUDE.md and start the task."

**To Claude Code (hand off to Cursor):**
> "Write CURSOR_TASK.md, update HANDOFF.md, commit everything, and hand off to Cursor."

**To Claude Code (Cursor finished, back to Claude):**
> "Cursor finished its part. Read HANDOFF.md and take over."
