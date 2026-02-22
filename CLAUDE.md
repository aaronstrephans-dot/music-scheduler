# Music Scheduler — Project Overview

> Long-lived reference for Claude Code, Cursor AI, and any future sessions.
> Keep this file updated when the stack, conventions, or major features change.
> For current work state and Cursor handoffs, see HANDOFF.md.

---

## What This Is

A web-based radio music scheduling system that replicates the core feature set of Music1 (M1).
It schedules songs into hourly clocks, enforces separation rules, generates full-day/full-week
schedules, and exports to industry formats (Zetta, WideOrbit, ENCO, CSV, ASCAP/BMI log).

Target user: a radio program director or music director running a small-to-mid-size station.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 · Flask |
| Frontend | Vanilla JS (no framework) · Jinja2 templates |
| Data store | Flat JSON files per entity (no database) |
| AI (optional) | Pluggable provider via `ai/` module — requires `AI_PROVIDER` env var |
| Entry point | `run.py` → `app.py` (Flask app) |

---

## Repository Layout

```
app.py                  Flask app — all routes and CRUD helpers
run.py                  Entry point (calls app.run)
engine/
  models.py             make_* factory functions for all entity types
  rotator.py            build_schedule() — core scheduling algorithm
  rules.py              DEFAULT_RULES, merge_rules()
  validator.py          validate_schedule(), _hms() helper
ai/                     Optional AI provider module
templates/
  dashboard.html        / — summary stats
  index.html            /library and /clocks-editor and /rules-editor (SPA tabs)
  generate.html         /generate — week generation UI
  view_schedule.html    /view — day-by-day schedule viewer
  export.html           /export — export + FTP upload UI
  reports.html          /reports — rotation, artist sep, category, compliance
data/                   Runtime JSON data (gitignored in prod; keep in dev)
  tracks/               One JSON file per track
  artists/              One JSON file per artist
  categories/           One JSON file per category
  clocks/               One JSON file per clock template
  day_templates/        One JSON file per day template (hour→clock map)
  dayparts/             One JSON file per daypart
  schedules/            Generated schedules (one JSON per schedule)
  play_history/         Per-date-per-hour play logs for separation
  announcers/           Jock/announcer records
  sound_codes/          Up to 30 named sound codes
  traffic/              Traffic/spot components
  artist_groups/        Artist groups (shared separation pool)
  exports/              Generated export files (csv, log, txt)
  rules.json            Global rotation rules (singleton)
```

---

## Key Concepts

### Entities
- **Track** — a song. Fields: title, artist, category, duration_seconds, cart/cart_number, bpm, energy, tempo (1-5), mood (1-5), gender (1-2), intro_ms, outro_ms, sound_codes, isrc_code, publisher, composer, album, active.
- **Clock** — an hourly template with ordered slots. Each slot has a type (music/jingle/traffic/etc.) and category constraint.
- **Day Template** — maps each hour 0–23 to a clock_id.
- **Schedule** — a generated list of tracks for a time period, saved to `data/schedules/`.
- **Rules** — global rotation rules: artist_separation_ms, song_separation_ms, tempo rules, gender balance, etc.

### Scheduling Flow
1. User picks a clock (or day template for full-day).
2. `engine/rotator.py → build_schedule()` iterates clock slots, selects eligible tracks per category, enforces separation rules, returns ordered track list.
3. Schedule saved to `data/schedules/` as JSON.
4. View/export from `view_schedule.html` or `export.html`.

### Export Formats
- `csv` — generic CSV
- `music1` — fixed-width Music1-style .txt log
- `ascap` — pipe-delimited ASCAP/BMI broadcast log
- `zetta-log` — tab-delimited Zetta log
- `wideorbit` / `enco` — tab-delimited traffic logs
- FTP upload supported via `POST /api/export/ftp`

### M1 File Import
- `import_m1_direct.py` — parses `.m1` / `.WED` Music1 library files
- Reference files in repo root: `PraiseFM.m1`, `Praise FM.WED`, `M1 Format*.png`

---

## API Surface (app.py)

All REST endpoints follow the pattern `GET/POST /api/<entity>` and `GET/PUT/DELETE /api/<entity>/<id>`.

| Prefix | Resource |
|--------|----------|
| `/api/tracks` | Song library (CRUD + bulk-action + import + play logging) |
| `/api/artists` | Artist records |
| `/api/categories` | Categories (rotation pools) |
| `/api/clocks` | Clock templates |
| `/api/day-templates` | Day templates |
| `/api/dayparts` | Dayparts |
| `/api/announcers` | Announcers/jocks |
| `/api/sound-codes` | Sound codes |
| `/api/traffic` | Traffic/spot components |
| `/api/artist-groups` | Artist groups |
| `/api/rules` | Global rules (GET + PUT) |
| `/api/schedule/generate` | Generate single-clock schedule |
| `/api/schedule/generate-day` | Generate full-day schedule from template |
| `/api/generate` | Generate full 7-day week |
| `/api/schedule/<id>/...` | View, update, delete, validate, move-track, replace-track, clone, export |
| `/api/schedule/date/<date>` | Look up schedule by date |
| `/api/play-history` | Per-day/hour play history |
| `/api/export` | Batch export to files |
| `/api/export/download/<file>` | Download exported file |
| `/api/export/ftp` | FTP upload |
| `/api/reports/...` | Rotation, artist-sep, category, compliance, never-played |
| `/api/ai/...` | AI clock gen, flow analysis, rules suggestions (requires AI_PROVIDER) |
| `/api/stats` | Dashboard summary |
| `/api/status` | Health check |

---

## Coding Conventions

- **No ORM** — data is plain dicts loaded/saved as JSON files via `_load_all()`, `_load_one()`, `_save()`, `_delete()`.
- **IDs** — UUID4 strings assigned at creation by `make_*` factory functions in `engine/models.py`.
- **Timestamps** — ISO-8601 UTC strings, e.g. `"2026-02-22T14:30:00Z"`. Use `_now()` in `app.py`.
- **Immutable fields** — `id` and `added_at`/`created_at` are never overwritten on PUT.
- **Frontend** — vanilla JS, no build step. JS lives inline in templates or in small `<script>` blocks. Fetch the REST API for all data.
- **No test runner** — tests live in `tests/` but there is no CI. Run with `pytest tests/` manually.
- **Flat file gotchas** — loading all tracks is O(n disk reads). Avoid calling `_load_all(TRACKS_DIR)` more than once per request where possible.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AI_PROVIDER` | Enables AI routes (`anthropic`, `openai`, etc.) |
| `FLASK_ENV` | Set to `development` for debug mode |

---

## What's Been Built (as of 2026-02-22)

- Full CRUD for all entity types (tracks, artists, categories, clocks, day templates, dayparts, announcers, sound codes, traffic, artist groups)
- Clock-based and day-template-based schedule generation
- Full-week generation with overnight fill controls
- Play history tracking and prev-day separation checks
- Schedule validation (rule violations flagged with errors/warnings)
- Schedule viewer with inline track swap/replace
- Reports: rotation depth, artist separation, category analysis, compliance log, never-played
- Export: CSV, Music1 txt, ASCAP, Zetta, WideOrbit, ENCO, FTP upload
- Bulk track operations (activate/deactivate/recategorize/delete/set_field)
- Schedule clone
- Dynamic column picker in track library
- M1 file import parser (`import_m1_direct.py`)
- Optional AI provider integration (analyze flow, generate clock, suggest rules)
