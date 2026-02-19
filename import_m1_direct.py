#!/usr/bin/env python3
"""
import_m1_direct.py — Full Music1 (.m1) database importer.

Imports: Songs → tracks, Artists → artists, Categories → categories,
         Clocks + ClockItems → clocks, Days → day_templates,
         Vars (DPName/DPColor) → dayparts.

Cross-platform: Linux (mdbtools) and Windows (pyodbc).

Usage:
    python import_m1_direct.py /path/to/Station.m1
    python import_m1_direct.py /path/to/Station.m1 --dry-run
    python import_m1_direct.py /path/to/Station.m1 --only songs
    python import_m1_direct.py /path/to/Station.m1 --only songs artists categories

Linux requirements:
    sudo apt-get install mdbtools

Windows requirements:
    pip install pyodbc
    Microsoft Access Database Engine (same bitness as Python):
    https://www.microsoft.com/en-us/download/details.aspx?id=54920
"""

import csv
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
TRACKS_DIR        = os.path.join(BASE_DIR, "data", "tracks")
ARTISTS_DIR       = os.path.join(BASE_DIR, "data", "artists")
CATEGORIES_DIR    = os.path.join(BASE_DIR, "data", "categories")
CLOCKS_DIR        = os.path.join(BASE_DIR, "data", "clocks")
DAY_TEMPLATES_DIR = os.path.join(BASE_DIR, "data", "day_templates")
DAYPARTS_DIR      = os.path.join(BASE_DIR, "data", "dayparts")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Backend abstraction (Linux mdbtools / Windows pyodbc)
# ---------------------------------------------------------------------------

ON_WINDOWS = platform.system() == "Windows"


def _check_mdbtools():
    for tool in ("mdb-tables", "mdb-export"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            print(f"ERROR: '{tool}' not found. Install with:  sudo apt-get install mdbtools")
            sys.exit(1)


def _linux_tables(m1_path):
    _check_mdbtools()
    r = subprocess.run(["mdb-tables", "-1", m1_path],
                       capture_output=True, text=True, check=True)
    return [t.strip() for t in r.stdout.splitlines() if t.strip()]


def _linux_read(m1_path, table):
    _check_mdbtools()
    r = subprocess.run(["mdb-export", m1_path, table],
                       capture_output=True, text=True, check=True)
    reader = csv.DictReader(r.stdout.splitlines())
    return list(reader)


def _windows_read(m1_path, table):
    try:
        import pyodbc
    except ImportError:
        print("ERROR: pip install pyodbc")
        sys.exit(1)
    drivers = [d for d in pyodbc.drivers()
               if any(k in d.lower() for k in ("access", "mdb", "accdb"))]
    if not drivers:
        print("ERROR: No Microsoft Access ODBC driver found.")
        sys.exit(1)
    conn = pyodbc.connect(f"Driver={{{drivers[0]}}};DBQ={m1_path};", autocommit=True)
    cur  = conn.cursor()
    cur.execute(f"SELECT * FROM [{table}]")
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return rows


def _windows_tables(m1_path):
    try:
        import pyodbc
    except ImportError:
        return []
    drivers = [d for d in pyodbc.drivers()
               if any(k in d.lower() for k in ("access", "mdb", "accdb"))]
    if not drivers:
        return []
    conn = pyodbc.connect(f"Driver={{{drivers[0]}}};DBQ={m1_path};", autocommit=True)
    cur  = conn.cursor()
    tables = [row.table_name for row in cur.tables(tableType="TABLE")]
    conn.close()
    return tables


def list_tables(m1_path):
    return _windows_tables(m1_path) if ON_WINDOWS else _linux_tables(m1_path)


def read_table(m1_path, table):
    try:
        return _windows_read(m1_path, table) if ON_WINDOWS else _linux_read(m1_path, table)
    except Exception as e:
        print(f"  WARNING: Could not read table '{table}': {e}")
        return []


def _int(val, default=0):
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "-1")


def _str(val):
    if val is None:
        return ""
    return str(val).strip()


def ensure_dirs():
    for d in (TRACKS_DIR, ARTISTS_DIR, CATEGORIES_DIR,
              CLOCKS_DIR, DAY_TEMPLATES_DIR, DAYPARTS_DIR):
        os.makedirs(d, exist_ok=True)


def write_json(directory, obj):
    path = os.path.join(directory, f"{obj['id']}.json")
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

def _duration_s(ms_val):
    """Convert Music1 millisecond length to seconds."""
    ms = _int(ms_val, 0)
    return ms // 1000 if ms else None


# ---------------------------------------------------------------------------
# Sound codes  (Music1 SC1-SC30 boolean columns)
# ---------------------------------------------------------------------------

def _extract_sound_codes(row):
    codes = []
    for i in range(1, 31):
        if _bool(row.get(f"SC{i}", False)):
            codes.append(i)
    return codes


# ---------------------------------------------------------------------------
# Hours string helpers
# ---------------------------------------------------------------------------

def _hours_string(row, prefix="Hours"):
    """Build 24-char allowed_hours from Hours1..Hours7 (each is a 24-bit int or string)."""
    # Music1 stores allowed hours as 7 separate Long Integer bitmasks (one per day).
    # For our scheduler we OR them all together into a single 24-char "any day" mask.
    bits = 0
    for i in range(1, 8):
        val = _int(row.get(f"{prefix}{i}", 0))
        bits |= val
    if bits == 0:
        return "111111111111111111111111"
    result = ""
    for h in range(24):
        result += "1" if (bits >> h) & 1 else "0"
    return result


# ---------------------------------------------------------------------------
# Import: Artists
# ---------------------------------------------------------------------------

def import_artists(m1_path, dry_run=False):
    print("\n=== Importing Artists ===")
    rows = read_table(m1_path, "Artists")
    imported = 0
    id_map   = {}  # m1_id (int) → our UUID

    for row in rows:
        m1_id = _int(row.get("ID", 0))
        name  = _str(row.get("Name", ""))
        if not name:
            continue

        our_id = _uuid()
        id_map[m1_id] = our_id

        artist = {
            "id":            our_id,
            "m1_id":         m1_id,
            "added_at":      _now(),
            "name":          name,
            "name_key":      name.upper(),
            "alpha_key":     _str(row.get("AlphaKey", "")),
            "canon_key":     _str(row.get("CannonKey", "")),
            "rec_type":      _int(row.get("RecTyp", 0)),
            "separation_ms": _int(row.get("Separation", 5400000)),
            "gender":        _int(row.get("Gender", 0)),
            "allow_double":  _bool(row.get("AllowDbl", False)),
            "auto_sep":      _bool(row.get("AutoSep", True)),
            # group_id resolved in second pass if needed
            "group_id":      _int(row.get("GroupID", 0)) or None,
        }

        if not dry_run:
            write_json(ARTISTS_DIR, artist)
        imported += 1

    print(f"  Imported {imported} artists")
    return id_map   # m1_artist_id → our UUID


# ---------------------------------------------------------------------------
# Import: Categories
# ---------------------------------------------------------------------------

# Music1 category colour int → CSS hex
def _m1_color(val):
    n = _int(val, 0)
    if n == 0:
        return None
    r =  n        & 0xFF
    g = (n >>  8) & 0xFF
    b = (n >> 16) & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


def import_categories(m1_path, dry_run=False):
    print("\n=== Importing Categories ===")
    rows     = read_table(m1_path, "Categories")
    imported = 0
    id_map   = {}   # m1_id → our UUID
    rows_by_m1id = {}

    for row in rows:
        m1_id = _int(row.get("ID", 0))
        name  = _str(row.get("Name", ""))
        if not name:
            continue
        rows_by_m1id[m1_id] = row
        our_id = _uuid()
        id_map[m1_id] = our_id

    # Second pass — resolve alternate IDs now that id_map is complete
    for row in rows:
        m1_id = _int(row.get("ID", 0))
        name  = _str(row.get("Name", ""))
        if not name or m1_id not in id_map:
            continue

        our_id = id_map[m1_id]

        cat = {
            "id":               our_id,
            "m1_id":            m1_id,
            "added_at":         _now(),
            "name":             name,
            "type":             _int(row.get("Typ", 1)),
            "color":            _m1_color(row.get("Color")),
            "priority":         _int(row.get("Priority", 0)),
            "grouping":         _int(row.get("Grouping", 0)),
            "title_separation_ms": _int(row.get("TitleSeparation", 7200000)),
            "prev_day_sep_ms":  _int(row.get("PrevDaySep", 0)),
            "alternate1":       id_map.get(_int(row.get("Alternate1", 0))),
            "alternate2":       id_map.get(_int(row.get("Alternate2", 0))),
            "alternate3":       id_map.get(_int(row.get("Alternate3", 0))),
            "play_by_pct":      _bool(row.get("PlayByPct", False)),
            "is_packet":        _bool(row.get("IsPacket", False)),
            "show_packets":     _bool(row.get("ShowPackets", True)),
            "schedulable":      _bool(row.get("Schedulable", True)),
            "force_rank_rotation": _bool(row.get("ForceRankRotation", False)),
            "recycle":          _bool(row.get("Recycle", True)),
            "min_rotation":     _int(row.get("MinRotation", 35)),
            "search_depth":     _int(row.get("SearchDepth", 1)),
            "enforce_artist_sep": _bool(row.get("EnforceArtistSep", True)),
            "exclude_frequent_hours": _bool(row.get("ExcludeFrequentHours", False)),
            "exclude_same_hour_prev_day": _bool(row.get("ExcludeSameHourPrevDay", False)),
            "allow_unscheduled": _bool(row.get("AllowUnscheduled", True)),
            "sched_mode":       _int(row.get("SchedMode", 1)),
            "num_songs":        _int(row.get("NumSongs", 0)),
            "avg_length_ms":    _int(row.get("AvgLen", 0)),
            "total_plays":      _int(row.get("TotalPlays", 0)),
        }

        if not dry_run:
            write_json(CATEGORIES_DIR, cat)
        imported += 1

    print(f"  Imported {imported} categories")
    return id_map   # m1_cat_id → our UUID


# ---------------------------------------------------------------------------
# Import: Songs (tracks)
# ---------------------------------------------------------------------------

def import_songs(m1_path, artist_id_map, cat_id_map, dry_run=False):
    print("\n=== Importing Songs ===")
    rows     = read_table(m1_path, "Songs")
    imported = 0
    skipped  = 0
    id_map   = {}   # m1_song_id → our UUID

    for row in rows:
        m1_id = _int(row.get("ID", 0))
        title = _str(row.get("Title", ""))
        if not title:
            skipped += 1
            continue

        artist_m1 = _int(row.get("Artist", 0))
        # Fall back: artist name stored on row (some exports flatten it)
        artist_name = _str(row.get("ArtistName", ""))
        if not artist_name:
            # We can't resolve name from id_map alone (we don't store names there),
            # so leave empty — caller can re-link after loading artist JSON files
            artist_name = f"[m1_artist_{artist_m1}]" if artist_m1 else "Unknown Artist"

        length_ms = _int(row.get("Length", 0))

        our_id = _uuid()
        id_map[m1_id] = our_id

        track = {
            "id":             our_id,
            "m1_id":          m1_id,
            "added_at":       _now(),
            "play_count":     0,
            "last_played_at": None,

            # Core
            "title":          title,
            "artist":         artist_name,
            "m1_artist_id":   artist_m1,
            "artist2_id":     _int(row.get("Artist2", 0)) or None,
            "alt_artists":    _str(row.get("AltArtists", "")),
            "category":       _str(row.get("Category", "")),  # m1 stores ID; resolve below

            # Timing (ms)
            "duration_ms":    length_ms,
            "duration_seconds": length_ms // 1000 if length_ms else None,
            "intro_ms":       _int(row.get("Intro", 0)),
            "outro_ms":       _int(row.get("Outro", 0)),
            "hook_in_ms":     _int(row.get("HookIn", 0)),
            "hook_out_ms":    _int(row.get("HookOut", 0)),
            "mix_in_ms":      _int(row.get("MixIn", 0)),
            "mix_out_ms":     _int(row.get("MixOut", 0)),

            # Musical attributes
            "gender":         _int(row.get("Gender", 0)),
            "tempo":          _int(row.get("Tempo", 0)),
            "tempo_min":      _int(row.get("Tempo1", 0)),
            "tempo_max":      _int(row.get("Tempo2", 0)),
            "texture":        _int(row.get("Texture", 0)),
            "texture_min":    _int(row.get("Texture1", 0)),
            "texture_max":    _int(row.get("Texture2", 0)),
            "mood":           _int(row.get("Mood", 0)),
            "key1":           _int(row.get("Key1", 0)),
            "key2":           _int(row.get("Key2", 0)),
            "bpm":            _int(row.get("BPM", 0)) or None,

            # Sound codes
            "sound_codes":    _extract_sound_codes(row),

            # Hour / day restrictions
            "hour_restricted": _bool(row.get("HrRestricted", False)),
            "allowed_hours":   _hours_string(row, "Hours"),
            "start_hour":      _int(row.get("StartHour", 0)),
            "end_hour":        _int(row.get("EndHour", 0)),

            # Date range
            "start_date": _str(row.get("StartDate", "")) or None,
            "end_date":   _str(row.get("EndDate", "")) or None,
            "hit_date":   _str(row.get("HitDate", "")) or None,

            # Hour position
            "can_open_hour":  not _bool(row.get("Beginning", False)),
            "can_close_hour": not _bool(row.get("Ending", False)),

            # Automation
            "cart":       _str(row.get("Cart", "")),
            "file_path":  _str(row.get("File", "")),
            "auto_params": _str(row.get("AutoParams", "")),
            "id_in_player": _str(row.get("IDInPlayer", "")),

            # Metadata
            "album":         _str(row.get("AlbumID", "")),
            "genre":         _str(row.get("Genre", "")),
            "composer":      _str(row.get("Composer", "")),
            "arranger":      _str(row.get("Arranger", "")),
            "publisher":     _str(row.get("Publisher", "")),
            "record_label":  _str(row.get("RecordLabel", "")),
            "catalog_num":   _str(row.get("CatalogNum", "")),
            "origin":        _str(row.get("Origin", "")),
            "prog_type":     _str(row.get("ProgType", "")),
            "prod_source":   _str(row.get("ProdSource", "")),
            "music_usage":   _str(row.get("MusicUsage", "")),

            # Licensing
            "isrc_code":      _str(row.get("ISCICode", "")),
            "work_code":      _str(row.get("WorkCode", "")),
            "recording_code": _str(row.get("RecordingCode", "")),
            "native_content": _bool(row.get("NativeContent", False)),
            "mcps":           _bool(row.get("MCPS", False)),
            "prior_approval": _bool(row.get("PriorApproval", False)),

            # Custom fields
            "user1": _str(row.get("User1", "")),
            "user2": _str(row.get("User2", "")),
            "user3": _str(row.get("User3", "")),
            "user4": _str(row.get("User4", "")),

            # Scheduling
            "announcer":      _int(row.get("Announcer", 0)),
            "link_type":      _int(row.get("LinkTyp", 0)),
            "link_align":     _int(row.get("LinkAlign", 0)),
            "pct_play":       _int(row.get("PctPlay", 100)),
            "chart_position": _int(row.get("ChartPosition", 0)),
        }

        if not dry_run:
            write_json(TRACKS_DIR, track)
        imported += 1

    print(f"  Imported {imported} songs, skipped {skipped}")
    return id_map


def resolve_song_artists(artist_id_map, m1_path, dry_run=False):
    """
    Second pass: load artist JSON files, build m1_id → name map,
    then update tracks that have placeholder m1_artist_id fields.
    """
    if dry_run:
        return

    # Build m1_id → name from written artist files
    m1_to_name = {}
    for fname in os.listdir(ARTISTS_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(ARTISTS_DIR, fname)) as f:
            a = json.load(f)
        if a.get("m1_id"):
            m1_to_name[a["m1_id"]] = a["name"]

    updated = 0
    for fname in os.listdir(TRACKS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(TRACKS_DIR, fname)
        with open(path) as f:
            track = json.load(f)
        m1_art = track.get("m1_artist_id")
        if m1_art and track.get("artist", "").startswith("[m1_artist_"):
            name = m1_to_name.get(m1_art)
            if name:
                track["artist"] = name
                with open(path, "w") as f:
                    json.dump(track, f, indent=2)
                updated += 1

    if updated:
        print(f"  Resolved artist names for {updated} tracks")


# ---------------------------------------------------------------------------
# Import: Clocks + ClockItems
# ---------------------------------------------------------------------------

def import_clocks(m1_path, dry_run=False):
    print("\n=== Importing Clocks ===")
    clock_rows = read_table(m1_path, "Clocks")
    item_rows  = read_table(m1_path, "ClockItems")

    # Index items by clock ID
    items_by_clock = {}
    for item in item_rows:
        cid = _int(item.get("Clock", 0))
        items_by_clock.setdefault(cid, []).append(item)

    imported = 0
    id_map   = {}   # m1_clock_id → our UUID

    for crow in clock_rows:
        m1_id = _int(crow.get("ID", 0))
        name  = _str(crow.get("Name", ""))
        if not name:
            continue

        our_id = _uuid()
        id_map[m1_id] = our_id

        # Sort clock items by position index
        raw_items = sorted(
            items_by_clock.get(m1_id, []),
            key=lambda r: _int(r.get("Ndx", 0))
        )

        slots = []
        for item in raw_items:
            slot_type_code = _int(item.get("Typ", 1))
            # Typ: 1=music, 2=spot/avail, 3=liner/sweeper, 4=link, 0=void
            slot_type = {0: "void", 1: "music", 2: "spot", 3: "liner", 4: "link"}.get(
                slot_type_code, "music"
            )

            slot = {
                "type":               slot_type,
                "category":           _str(item.get("Category", "")),
                "title":              _str(item.get("Title", "")),
                "notes":              _str(item.get("Notes", "")),
                "cluster_name":       _str(item.get("ClusterName", "")) or None,
                "in_cluster":         _bool(item.get("InCluster", False)),
                "color":              _m1_color(item.get("Color")),
                "cluster_color":      _m1_color(item.get("ClusterColor")),

                # Timing
                "nominal_length_s":     _int(item.get("NominalLength", 0)) // 1000 or None,
                "max_length_s":         _int(item.get("MaximumLength", 0)) // 1000 or None,
                "min_length_s":         _int(item.get("MinimumLength", 0)) // 1000 or None,
                "nominal_start_time_s": _int(item.get("NominalStartTime", 0)) // 1000 or None,
                "min_start_time_s":     _int(item.get("MinStartTime", 0)) // 1000 or None,
                "max_start_time_s":     _int(item.get("MaxStartTime", 0)) // 1000 or None,
                "fixed_start_time":     _bool(item.get("FixedStartTime", False)),

                # Timing behaviour
                "leave_gap":           _bool(item.get("LeaveGap", False)),
                "clip_overrun":        _bool(item.get("ClipOverrun", False)),
                "report_nominal_time": _bool(item.get("ReportNominalTime", False)),
                "fill_completely":     _bool(item.get("FillCompletely", False)),
                "fill_to_match":       _bool(item.get("FillToMatch", False)),
                "fill_to_minimum":     _bool(item.get("FillToMinimum", False)),
                "fit_to_time":         _bool(item.get("FitToTime", False)),

                # Fill
                "avail_type":    _int(item.get("AvailType", 0)),
                "max_units":     _int(item.get("MaxUnits", 0)),
                "fill_priority": _int(item.get("FillPriority", 5)),

                # Attribute filters (0/-1 = no constraint)
                "gender":  _int(item.get("SGender", 0)) or None,
                "tempo":   _int(item.get("STempo", 0)) or None,
                "texture": _int(item.get("STexture", 0)) or None,
                "mood":    _int(item.get("SMood", 0)) or None,

                # Sound codes — SSC is a 32-bit bitmask
                "sound_codes": _ssc_to_list(_int(item.get("SSC", 0))),
                "sc_and":      _bool(item.get("SCAnd", False)),

                # Other
                "require_native":   _bool(item.get("SNative", False)),
                "dbl_shot_artists": _bool(item.get("DblShotArtists", False)),
                "announcer":        _int(item.get("SAnnouncer", 0)) or None,
                "hr_restricted":    _bool(item.get("HrRestricted", False)),
                "allowed_hours":    _hours_string(item, "Hours") if _bool(item.get("HrRestricted", False)) else None,
                "link_type":        _int(item.get("LinkTyp", 0)),
                "insert_if_empty":  _bool(item.get("InsertIfEmpty", False)),
            }
            slots.append(slot)

        clock = {
            "id":           our_id,
            "m1_id":        m1_id,
            "created_at":   _now(),
            "updated_at":   _now(),
            "name":         name,
            "slots":        slots,

            # Separation
            "artist_separation_songs": 9,  # M1 stores this in ms on artist record

            # Time budget
            "nominal_time_s":   3600,
            "hard_min_time_s":  _int(crow.get("HardMinTime", 0)) // 1000 or None,
            "hard_max_time_s":  _int(crow.get("HardMaxTime", 0)) // 1000 or None,

            # Cross-day
            "check_prev_day_song":   _bool(crow.get("PrevDaySong", False)),
            "check_prev_day_artist": _bool(crow.get("PrevDayArtist", False)),

            # Double shots
            "allow_double_shots":           _bool(crow.get("AllowDblShots", False)),
            "double_shot_separation_songs": _int(crow.get("DblShotSep", 0)),

            "no_repeats":         _bool(crow.get("NoRepeats", True)),
            "fixed_time_enabled": _bool(crow.get("FixedTimeEnabled", False)),
            "absolute_time":      _bool(crow.get("AbsoluteTime", False)),

            # Attribute run limits — M1 stores max run in GenderRun/TempoRun etc.
            "max_gender_run":  _int(crow.get("GenderRun0", -1)),
            "max_tempo_run":   _int(crow.get("TempoRun0", -1)),
            "max_texture_run": _int(crow.get("TextureRun0", -1)),
            "max_mood_run":    _int(crow.get("MoodRun0", -1)),
        }

        if not dry_run:
            write_json(CLOCKS_DIR, clock)
        imported += 1

    print(f"  Imported {imported} clocks")
    return id_map   # m1_clock_id → our UUID


def _ssc_to_list(bitmask):
    """Convert a 30-bit sound code bitmask to a list of active code numbers (1-indexed)."""
    if not bitmask:
        return []
    return [i + 1 for i in range(30) if (bitmask >> i) & 1]


# ---------------------------------------------------------------------------
# Import: Days → day_templates
# ---------------------------------------------------------------------------

def import_days(m1_path, clock_id_map, dry_run=False):
    print("\n=== Importing Day Templates (Days) ===")
    rows     = read_table(m1_path, "Days")
    imported = 0

    for row in rows:
        m1_id = _int(row.get("ID", 0))
        name  = _str(row.get("Name", ""))
        if not name:
            continue

        # Build hour → clock_id map
        hours = {}
        for h in range(25):  # Music1 has Hr00-Hr24
            col    = f"Hr{h:02d}"
            m1_cid = _int(row.get(col, 0))
            our_cid = clock_id_map.get(m1_cid)
            hours[str(h % 24)] = our_cid  # wrap Hr24 to 0

        tmpl = {
            "id":               _uuid(),
            "m1_id":            m1_id,
            "added_at":         _now(),
            "name":             name,
            "hours_in_day":     _int(row.get("HoursInDay", 24)),
            "time_change_hour": _int(row.get("TimeChangeHour", 0)),
            "recycle_from_hour": _int(row.get("RecycleFromHour", 0)),
            "hours":            hours,
        }

        if not dry_run:
            write_json(DAY_TEMPLATES_DIR, tmpl)
        imported += 1

    print(f"  Imported {imported} day templates")


# ---------------------------------------------------------------------------
# Import: Vars → dayparts
# ---------------------------------------------------------------------------

def import_dayparts(m1_path, dry_run=False):
    print("\n=== Importing Dayparts (from Vars) ===")
    rows = read_table(m1_path, "Vars")

    vars_map = {}
    for row in rows:
        key = _str(row.get("ParamName", ""))
        val = _str(row.get("Setting", ""))
        if key:
            vars_map[key] = val

    imported = 0
    for i in range(10):
        name = vars_map.get(f"DPName{i}", "").strip()
        if not name:
            continue

        color_int = _int(vars_map.get(f"DPColor{i}", "0"))
        if color_int:
            r =  color_int        & 0xFF
            g = (color_int >>  8) & 0xFF
            b = (color_int >> 16) & 0xFF
            color = f"#{r:02X}{g:02X}{b:02X}"
        else:
            color = None

        dp = {
            "id":         _uuid(),
            "added_at":   _now(),
            "name":       name,
            "start_hour": 0,   # Music1 doesn't store start/end hours in Vars
            "end_hour":   0,   # — user will need to set these manually
            "color":      color,
        }

        if not dry_run:
            write_json(DAYPARTS_DIR, dp)
        imported += 1

    print(f"  Imported {imported} dayparts")


# ---------------------------------------------------------------------------
# Import: SongPlays → seed track play counts and last_played_at
# ---------------------------------------------------------------------------

def _parse_m1_datetime(val):
    """Parse Music1 datetime string (M/D/YY or M/D/YYYY H:MM:SS) → ISO string or None."""
    if not val or str(val).strip() in ("", "0", "12/30/99 00:00:00"):
        return None
    s = str(val).strip()
    for fmt in ("%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat() + "Z"
        except ValueError:
            continue
    return None


def patch_song_plays(m1_path, dry_run=False):
    """
    Read SongPlays and update matching track JSON files with:
      play_count      ← TotalPlays
      plays_this_list ← PlaysThisList
      last_played_at  ← LastPlayed (converted from M1 datetime string)
      date_added      ← DateAdded
    Matches on m1_id stored in the track file.
    """
    print("\n=== Patching SongPlays → track play counts ===")
    rows = read_table(m1_path, "SongPlays")

    # Build m1_song_id → stats map
    stats = {}
    for row in rows:
        m1_id      = _int(row.get("Song", 0))
        total      = _int(row.get("TotalPlays", 0))
        this_list  = _int(row.get("PlaysThisList", 0))
        last_play  = _parse_m1_datetime(row.get("LastPlayed"))
        date_added = _parse_m1_datetime(row.get("DateAdded"))
        if m1_id:
            stats[m1_id] = {
                "play_count":      total,
                "plays_this_list": this_list,
                "last_played_at":  last_play,
                "date_added":      date_added,
            }

    if dry_run:
        print(f"  Would patch {len(stats)} tracks with play stats")
        return

    updated = 0
    for fname in os.listdir(TRACKS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(TRACKS_DIR, fname)
        with open(path) as f:
            track = json.load(f)
        m1_id = track.get("m1_id")
        if m1_id and m1_id in stats:
            track.update(stats[m1_id])
            with open(path, "w") as f:
                json.dump(track, f, indent=2)
            updated += 1

    print(f"  Updated {updated} tracks with play history from SongPlays")


# ---------------------------------------------------------------------------
# Import: CatItems → seed per-category rotation rank on tracks
# ---------------------------------------------------------------------------

def patch_cat_items(m1_path, dry_run=False):
    """
    Read CatItems and add rotation_rank dict to each track:
      track["rotation_ranks"][category_id] = {"rank": N, "play_num": N, "play_credits": N}
    Enables force_rank_rotation to start from the correct position.
    """
    print("\n=== Patching CatItems → rotation ranks ===")
    rows = read_table(m1_path, "CatItems")

    # Build m1_song_id → { m1_cat_id: {rank, play_num, play_credits} }
    cat_items = {}
    for row in rows:
        m1_song = _int(row.get("Song", 0))
        m1_cat  = _int(row.get("Category", 0))
        if m1_song and m1_cat:
            cat_items.setdefault(m1_song, {})[str(m1_cat)] = {
                "rank":         _int(row.get("Rank", 0)),
                "play_num":     _int(row.get("PlayNum", 0)),
                "play_credits": _int(row.get("PlayCredits", 0)),
            }

    if dry_run:
        print(f"  Would patch rotation ranks for {len(cat_items)} songs")
        return

    updated = 0
    for fname in os.listdir(TRACKS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(TRACKS_DIR, fname)
        with open(path) as f:
            track = json.load(f)
        m1_id = track.get("m1_id")
        if m1_id and m1_id in cat_items:
            track["rotation_ranks"] = cat_items[m1_id]
            with open(path, "w") as f:
                json.dump(track, f, indent=2)
            updated += 1

    print(f"  Added rotation_ranks to {updated} tracks")


# ---------------------------------------------------------------------------
# Import: Notes → attach song annotations to tracks
# ---------------------------------------------------------------------------

def patch_notes(m1_path, dry_run=False):
    """
    Read Notes table and add a notes_m1 list to each track:
      [{"rank": 1, "text": "ENERGETIC", "start_date": null, "end_date": null}]
    """
    print("\n=== Patching Notes → song annotations ===")
    rows = read_table(m1_path, "Notes")

    # Build m1_song_id → list of note dicts
    notes_map = {}
    for row in rows:
        m1_song = _int(row.get("Song", 0))
        txt     = _str(row.get("Txt", ""))
        if m1_song and txt:
            note = {
                "rank":       _int(row.get("Rank", 1)),
                "text":       txt,
                "start_date": _parse_m1_datetime(row.get("StartDate")) if _int(row.get("StartDate", 0)) else None,
                "end_date":   _parse_m1_datetime(row.get("EndDate"))   if _int(row.get("EndDate",   0)) else None,
            }
            notes_map.setdefault(m1_song, []).append(note)

    # Sort each song's notes by rank
    for m1_id in notes_map:
        notes_map[m1_id].sort(key=lambda n: n["rank"])

    if dry_run:
        print(f"  Would attach notes to {len(notes_map)} songs")
        return

    updated = 0
    for fname in os.listdir(TRACKS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(TRACKS_DIR, fname)
        with open(path) as f:
            track = json.load(f)
        m1_id = track.get("m1_id")
        if m1_id and m1_id in notes_map:
            track["notes_m1"] = notes_map[m1_id]
            with open(path, "w") as f:
                json.dump(track, f, indent=2)
            updated += 1

    print(f"  Attached notes to {updated} tracks")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

ALL_STEPS = {"songs", "artists", "categories", "clocks", "days", "dayparts",
             "song_plays", "cat_items", "notes"}


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Full Music1 .m1 importer — tracks, artists, categories, clocks, day templates"
    )
    parser.add_argument("m1_file", help="Path to .m1 database file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report without writing files")
    parser.add_argument(
        "--only", nargs="*",
        choices=sorted(ALL_STEPS),
        help="Import only specific tables (default: all)"
    )
    args = parser.parse_args()

    if not os.path.isfile(args.m1_file):
        print(f"ERROR: File not found: {args.m1_file}")
        sys.exit(1)

    only = set(args.only) if args.only else ALL_STEPS

    ensure_dirs()

    tables = list_tables(args.m1_file)
    print(f"Platform: {'Windows (pyodbc)' if ON_WINDOWS else 'Linux (mdbtools)'}")
    print(f"File:     {args.m1_file}")
    print(f"Tables:   {tables}")

    artist_id_map = {}
    cat_id_map    = {}
    clock_id_map  = {}

    if "artists" in only:
        artist_id_map = import_artists(args.m1_file, dry_run=args.dry_run)

    if "categories" in only:
        cat_id_map = import_categories(args.m1_file, dry_run=args.dry_run)

    if "songs" in only:
        import_songs(args.m1_file, artist_id_map, cat_id_map, dry_run=args.dry_run)
        if not args.dry_run and "artists" in only:
            resolve_song_artists(artist_id_map, args.m1_file, dry_run=args.dry_run)

    # Patch steps — require tracks to already exist in TRACKS_DIR
    if "song_plays" in only:
        patch_song_plays(args.m1_file, dry_run=args.dry_run)

    if "cat_items" in only:
        patch_cat_items(args.m1_file, dry_run=args.dry_run)

    if "notes" in only:
        patch_notes(args.m1_file, dry_run=args.dry_run)

    if "clocks" in only:
        clock_id_map = import_clocks(args.m1_file, dry_run=args.dry_run)

    if "days" in only:
        import_days(args.m1_file, clock_id_map, dry_run=args.dry_run)

    if "dayparts" in only:
        import_dayparts(args.m1_file, dry_run=args.dry_run)

    print("\nDone." + (" (DRY RUN — no files written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
