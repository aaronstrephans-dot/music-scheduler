# Handoff — Current Work State

> Updated by whoever last worked on the project.
> See CLAUDE_INTEGRATION.md for the full handoff protocol.

---

## Last Updated
2026-02-22 — Claude Code session (setup session)

## Last Completed Work
- Set up Claude/Cursor integration workflow
- Created CLAUDE.md (long-lived project overview)
- Created CLAUDE_INTEGRATION.md (handoff rules and role split)
- Created this file (HANDOFF.md)
- No feature code was changed in this session

---

## Current Status
**No active feature in progress.**

The project is at a clean state with Music1 feature parity implemented:
- Full CRUD for all entity types
- Clock-based and day-template-based schedule generation
- Full-week generation
- Reports, exports (Zetta, ENCO, WideOrbit, ASCAP, Music1 txt, CSV), FTP upload
- Bulk track operations, schedule clone, track replace/move

---

## Next Steps
*(Fill this in at the start of the next work session)*

Nothing queued. Awaiting new feature request from user.

---

## Files Currently In Play
None — clean state.

---

## Decisions / Gotchas to Remember
- Data is flat JSON files — no database. All entity CRUD goes through `_load_one()` / `_save()` in `app.py`.
- `engine/rotator.py → build_schedule()` is the core scheduling algorithm. Changes here affect all schedule generation paths.
- The frontend is vanilla JS with no build step — edit templates directly in `templates/`.
- `index.html` serves three different pages (`/library`, `/clocks-editor`, `/rules-editor`) via tab switching in JS — be careful when adding new tabs.
- Track library loads can be slow at scale since every track is a separate JSON file. Avoid multiple `_load_all(TRACKS_DIR)` calls per request.
- M1 import files are in repo root: `PraiseFM.m1`, `Praise FM.WED`.

---

## How to Resume

**Claude Code:**
> "Read CLAUDE.md and HANDOFF.md, then continue where we left off."

**Cursor:**
> "Read HANDOFF.md and continue the task described there."
