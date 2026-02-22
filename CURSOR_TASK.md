# Cursor Task — Music Scheduler Feature Sprint
> Implement these in order. Each section is self-contained. All files are Flask/Jinja2 + vanilla JS.
> Reference images in repo root for UI targets: M1 format 1-4.png, Screenshot 2026-02-19 *.png, Customize-the-look-of-your-clocks-in-Version-72.png, customizing_musicmaster_9.png, a-screenshot-of-a-computer-description-automatica.png, download.jpg / download(1).jpg.

---

## TASK 1 — Clock Editor Redesign (HIGHEST PRIORITY)

**Problem:** The clock editor is only a simple "New Clock" modal. Users cannot build, visualize, or properly edit clock templates with full M1/Aiir-style functionality.

**Target UI:** See `Screenshot 2026-02-19 110913.png` (Aiir clock editor) and `Customize-the-look-of-your-clocks-in-Version-72.png` (MusicMaster).

**Implement a full-screen clock editor page/panel** at `/clock-editor/<clock_id>` or as a large modal (min 90vw × 90vh) with TWO panes:

### Left pane — Slot List (like Aiir):
- Columns: `#`, `Air Time` (cumulative from 00:00), `Type/Category` (colored badge matching category color), `Title` (shows "Unscheduled position"), `Duration` (~MM:SS), `Cart ID`
- Each row is draggable (drag to reorder slots)
- Clicking a row opens an inline editor for that slot: category picker, type (music/jingle/liner/traffic/voicetrack/spot/imaging), minimum duration, maximum duration, optional fixed cart
- "+" button at bottom to add a new slot
- Current Duration total shown at bottom right (like Aiir: "57:00 (−02:59)" if under 60 min)
- Slot types beyond music: jingle, liner, traffic, voicetrack, spot, imaging, lognote, sweeper

### Right pane — Visual Clock (like M1 / MusicMaster):
- SVG donut/ring chart (NOT a full pie — use a hollow ring with a white center circle radius ~40% of outer)
- Each slot = one arc segment, sized proportionally to slot's `min_duration_seconds` (default 210s = 3:30)
- Color each segment by its category's `color` field (from `/api/categories`)
- If category has no color, use a default palette
- Label each segment with the category shortname (abbreviated) inside or outside with leader lines
- Below the donut: tabs for "Pie View" | "Category Usage" | "Element Usage"
  - Category Usage: table of Category | Slot Count | Total Time | % of Hour
  - Element Usage: breakdown of music vs jingle vs traffic vs other
- Clock name editable inline at top

### Slot data model additions (update `engine/models.py` `make_slot()`):
```python
{
  "category": "",
  "type": "music",         # music|jingle|liner|traffic|voicetrack|spot|imaging|lognote
  "min_duration_seconds": 0,
  "max_duration_seconds": 0,   # 0 = no max
  "nominal_length_s": 210,     # used for pie chart sizing
  "fixed_cart": "",            # force a specific cart/track ID
  "label": "",                 # optional display label override
  "position": 0,               # sort order
}
```

### Save flow:
- Auto-save on any change with 800ms debounce (PUT `/api/clocks/<id>`)
- "Save" button as explicit save too

**Files:** `templates/index.html` (clock tab section + modal), `app.py` (clock PUT route already exists), `engine/models.py` (make_slot).

---

## TASK 2 — Categories Tab

**Problem:** No dedicated Categories management tab. Users need to define, color-code, rank, and manage rotation categories.

**Add a "Categories" nav tab** (insert after "Clocks" in the nav bar). Tab ID: `tab-categories`.

### Categories tab UI:
- Left panel: sortable list of all categories (drag to reorder = sets `priority` field)
- Right panel: category detail form

### Category form fields:
- **Name** (text)
- **Short Code** (2-4 chars, e.g. "CUR", "REC", "GLD") — used in clock slot type badges
- **Color** (color picker — this color is used everywhere: clock slot badges, schedule row background, pie chart segments)
- **Priority / Order** (numeric, lower = scheduled first)
- **Active** (toggle)
- **Schedulable** (toggle — housekeeping categories like imports can be non-schedulable)
- **Rotation Depth** (how many songs deep to rotate, 0 = unlimited)
- **Min Rest (songs)** — minimum songs between plays of same song in this category
- **Min Rest (hours)** — minimum hours between plays of same song in this category
- **Max Plays Per Day** (0 = unlimited)
- **Max Plays Per Week** (0 = unlimited)
- **Description** (text area)

### API: routes already exist at `/api/categories`. Update `engine/models.py` `make_category()` to include these new fields.

### Category color in UI:
- Everywhere a category appears (clock slots, schedule rows, track library pills), use `category.color` as the background/accent color
- Schedule row background = `category.color + '22'` (hex with 13% opacity)
- Category badge = `background: category.color + '33', color: category.color, border: 1px solid category.color + '66'`

---

## TASK 3 — Track Field Expansion

**Problem:** Missing many Music1/MusicMaster track fields. See `customizing_musicmaster_9.png` and `a-screenshot-of-a-computer-description-automatica.png`.

### Add these fields to `engine/models.py` `make_track()`:

```python
# Rotation tracking
"play_count": 0,              # total lifetime plays
"last_played_at": None,       # ISO datetime
"last_played_date": None,     # YYYY-MM-DD
"spins_today": 0,
"spins_this_week": 0,

# Library metadata
"source": "",                 # "CD", "Digital", "Streaming", "Imported", etc.
"encoding": "",               # "MP3", "WAV", "FLAC", "AAC", etc.
"quality_rating": 0,          # 1-9 (MusicMaster style)
"language": "",               # "English", "Spanish", etc.
"explicit": False,

# Artist info
"artist_keywords": "",        # comma-separated keywords for artist separation grouping
"featuring": "",              # featured artists
"gender": 0,                  # 1=Male, 2=Female, 3=Group/Mixed (already exists but may not be complete)
"role": "",                   # "M"=Male solo, "F"=Female solo, "G"=Group, "D"=Duo

# Scheduling controls
"daypart_restrictions": [],   # list of daypart names where this track CAN play (empty = all)
"can_open_hour": True,        # allowed as first song in an hour
"can_close_hour": True,       # allowed as last song in an hour
"start_date": None,           # YYYY-MM-DD — don't play before this date
"end_date": None,             # YYYY-MM-DD — don't play after this date
"days_of_week": [],           # [0-6] Mon=0 — restrict to specific days (empty = all)
"special_occasion": "",       # "Christmas", "Easter", etc.

# Music data
"release_year": None,         # int
"chart_peak": None,           # peak chart position
"chart_weeks": None,          # weeks on chart
"label": "",                  # record label
"songwriter": "",             # songwriter/composer (already has composer)
"lyrics": "",                 # searchable lyrics snippet

# Technical
"intro_type": "",             # "cold", "ramp", "instrumental"
"outro_type": "",             # "cold", "fade", "natural"
"hook_start_ms": 0,           # where the hook/chorus starts
"hook_end_ms": 0,
```

### Update track add/edit form in `templates/index.html`:
- Organize the track form into collapsible sections: **Basic Info**, **Scheduling Controls**, **Artist Info**, **Technical**, **Metadata**
- Add all new fields with appropriate input types
- `daypart_restrictions` = multi-select checkboxes of daypart names
- `days_of_week` = 7 checkbox toggles (M T W T F S S)

### Update track library column picker:
- Add ALL new fields to `TRACK_COLS` array in `templates/index.html`
- Make the column picker actually work (it exists but columns may not render)
- Key columns to add: `play_count`, `last_played_date`, `source`, `encoding`, `role`, `gender`, `release_year`, `chart_peak`, `artist_keywords`, `intro_ms`, `outro_ms`, `bpm`

---

## TASK 4 — View Schedule Improvements

**Problem:** Can't drag/move songs, replace by search is missing, violation scanner may be broken.

**File:** `templates/view_schedule.html`

### 4a — Drag-and-drop reorder:
- Use SortableJS (load from CDN: `https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js`)
- In list view, make table rows draggable
- On drop, call `PUT /api/schedule/<id>/move-track` with `{ from_index, to_index }`
- Visual feedback: drag handle `⠿` icon in leftmost column, ghost row while dragging

### 4b — Replace by search:
- Each row's action buttons (already have `.row-actions` showing on hover) should include a "🔄 Replace" button
- Clicking opens a search modal: search by title, artist, category, BPM range, tempo, mood, gender
- Results list shows matching tracks (paginated, 50 at a time)
- Clicking a result calls `PUT /api/schedule/<id>/replace-track` with `{ position, new_track_id }`

### 4c — Rule violation scanner fix:
- The "Scan Violations" button should call `POST /api/schedule/<id>/validate`
- Display results in the `.violations-panel` section
- Check that `app.py` route at `/api/schedule/<schedule_id>/validate` returns proper JSON with `{ errors: [], warnings: [], summary: {} }`
- If the route is broken (look at `engine/validator.py`), fix it

### 4d — Hour navigation:
- The hour strip exists but may not scroll the table to the right hour
- When clicking an hour chip, scroll the schedule table so that hour's first track is visible at the top
- Add `id` attributes to each hour's first row in the format `hour-row-6` for hour 6

---

## TASK 5 — Rules Expansion

**Problem:** Rules are too simplistic. Missing many M1/MusicMaster rule types.

**File:** `templates/index.html` (rules tab), `engine/rules.py`, `engine/validator.py`, `engine/rotator.py`

### Add these rule fields to `engine/rules.py` `DEFAULT_RULES`:

```python
# Artist separation
"artist_separation_songs": 9,
"artist_separation_ms": 5400000,
"artist_keyword_separation_songs": 6,    # NEW: songs between tracks sharing same artist keyword
"artist_keyword_separation_ms": 3600000, # NEW

# Gender/Role balance
"max_gender_run": -1,          # max consecutive same gender (-1 = off)
"gender_balance_enabled": False,
"gender_ratio_male": 50,       # target % male (0-100)

# Tempo/Energy flow
"max_tempo_run": 3,
"tempo_step_limit": 2,         # NEW: max tempo jump between consecutive songs (1-5 scale)
"energy_step_limit": 0,
"bpm_step_limit": 0,
"no_double_up_energy": False,   # NEW: forbid same energy level twice in a row

# Sound code separation
"sound_code_separation_songs": 3,   # NEW: min songs between tracks with same sound code

# Daypart rules
"enforce_daypart_restrictions": True,  # NEW: respect track.daypart_restrictions field

# Date/occasion rules
"enforce_date_range": True,
"enforce_days_of_week": True,          # NEW: respect track.days_of_week field

# Hour position rules
"enforce_hour_open_close": True,

# Rotation scheduling
"max_plays_per_day_enabled": False,    # NEW: enforce track.max_plays_per_day
"max_plays_per_week_enabled": False,   # NEW

# Title/Album separation
"title_separation_hours": 3,
"title_separation_ms": 10800000,
"album_separation_songs": 0,

# Cross-day separation
"check_prev_day_song": False,
"check_prev_day_artist": False,

# Stack key
"stack_key_separation_songs": 3,

# Double shots
"allow_double_shots": False,
"double_shot_separation_songs": 0,

# Conditional If/Then rules (existing)
"conditional_rules": [],
```

### Update rules UI in `templates/index.html` rules tab:
- Organize rules into sections with headers: **Separation**, **Flow & Balance**, **Daypart & Date**, **Hour Position**, **Advanced**
- Add all new fields with appropriate inputs (number, toggle, range)
- Save via PUT `/api/rules`

### Update `engine/rotator.py` to enforce new rules:
- `artist_keyword_separation_songs/ms`: parse `track.artist_keywords` as comma-separated, check if any keyword matches recent tracks
- `sound_code_separation_songs`: check `track.sound_codes` list
- `enforce_daypart_restrictions`: check track's `daypart_restrictions` list against current hour's daypart name
- `enforce_days_of_week`: check `track.days_of_week` against generation date's weekday
- `tempo_step_limit`: check `abs(prev_track.tempo - candidate.tempo) <= tempo_step_limit`

---

## TASK 6 — Branding & Light Mode

**Problem:** No branding customization or light mode.

### Implement a Settings panel (new tab or gear icon top-right):

#### Station Branding:
- Station Name (text) — displayed in sidebar logo area
- Station Tagline (text)
- Logo Upload — store as base64 in `data/config/branding.json`, show in sidebar
- Primary Accent Color (color picker) — replaces `--accent: #7c6cf0` CSS variable
- Secondary Accent Color — replaces `--accent2`

#### Theme:
- Dark Mode / Light Mode toggle
- Light mode CSS variable overrides:
  ```css
  [data-theme="light"] {
    --bg: #f8fafc;
    --bg2: #f1f5f9;
    --surface: rgba(0,0,0,0.04);
    --border: rgba(0,0,0,0.1);
    --text: #0f172a;
    --text2: #475569;
    --text3: #94a3b8;
  }
  ```
- Store preference in `localStorage`

#### Implementation:
- Create `GET/PUT /api/branding` route in `app.py` that reads/writes `data/config/branding.json`
- On page load, fetch branding and apply CSS variables via JS
- Add settings icon (⚙) in top-right nav

---

## TASK 7 — Track Library Column Picker Fix

**Problem:** Column picker button exists (`⊞ Columns`) but columns may not all render.

**File:** `templates/index.html` — `TRACK_COLS` array and `renderTrackRow()` function.

### Ensure ALL columns in `TRACK_COLS` render properly:
- Find `TRACK_COLS` array and `renderTrackRow()` function
- Verify the column picker checkbox list matches `TRACK_COLS` IDs
- Add missing columns: `play_count`, `last_played_date`, `source`, `encoding`, `role`, `artist_keywords`, `release_year`, `chart_peak`, `bpm`, `intro_ms`, `outro_ms`, `sound_codes`, `cart`
- Ensure `_visibleCols` set is used correctly in `renderTrackRow()`
- The default columns should be: `title`, `artist`, `category`, `duration`, `tempo`, `cart`, `active`

---

## Notes for Cursor

- **Data is flat JSON files** in `data/` — no ORM, no database. Use `_load_all()`, `_load_one()`, `_save()` from `app.py`.
- **Frontend is vanilla JS** — no React, no Vue. All data via `fetch()` to REST API.
- **Python backend** is Flask in `app.py`. All routes in one file.
- **IDs** are UUID4 strings.
- **No test runner required** — just make it work in the browser.
- When adding new fields to models, existing JSON files won't have them — use `.get('field', default)` everywhere.
- The clock PUT route at `PUT /api/clocks/<id>` already exists and handles `slots` correctly.
- Category colors are hex strings like `#6c63ff` stored in `category.color` field.
- SortableJS CDN: `https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js`

## Do NOT do in Cursor (already fixed by Claude):
- Zetta .LOG export format — already fixed in `app.py`
- WideOrbit / ENCO export formats — already fixed in `app.py`
- Daypart map interactive editing — already fixed in `templates/index.html`
- Daypart + weekday grid colors (brighter) — already fixed in `templates/index.html`
- Clock template Edit button — already added to `templates/index.html`
