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

## Handoff Protocol: Claude → Cursor

When Claude Code hits a context limit or determines Cursor is better suited:

1. Claude updates `HANDOFF.md` with:
   - What was just completed
   - What needs to happen next (specific, actionable)
   - Which files to focus on
   - Any gotchas or decisions already made
2. Claude commits and pushes all in-progress work.
3. Claude tells the user: "Ready to hand off — see HANDOFF.md."
4. User opens Cursor and says: "Read HANDOFF.md and continue."

## Handoff Protocol: Cursor → Claude

When Cursor finishes its portion or hits its own limits:

1. Cursor updates `HANDOFF.md` with what it changed and what remains.
2. User starts a new Claude Code session and says:
   "Read CLAUDE.md and HANDOFF.md, then continue."
3. Claude reads both files to restore full context before touching any code.

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
Open `HANDOFF.md` and paste its content into the Cursor chat as context,
or say: "Read HANDOFF.md and continue the task described there."

---

## File Responsibilities

| File | Owner | Purpose |
|------|-------|---------|
| `CLAUDE.md` | Both (Claude primary) | Long-lived project overview — stack, conventions, entity map, API surface |
| `CLAUDE_INTEGRATION.md` | Both | This file — workflow rules |
| `HANDOFF.md` | Both (whoever last worked) | Current state, next steps, files in play |

Rules for keeping files accurate:
- `CLAUDE.md` — update when: stack changes, new major feature added, conventions change.
- `HANDOFF.md` — update at the end of every work session, before any handoff.
- Never let `HANDOFF.md` go stale. A stale handoff doc is worse than no doc.

---

## Quick Reference: What to Say

**To Claude Code (new session after limit):**
> "Read CLAUDE.md and HANDOFF.md, then continue where we left off."

**To Cursor (after Claude handoff):**
> "Read HANDOFF.md and continue the task described there."

**To Claude Code (hand off to Cursor):**
> "Update HANDOFF.md, commit everything, and hand off to Cursor."

**To Claude Code (Cursor finished, back to Claude):**
> "Cursor finished its part. Read HANDOFF.md and take over."
