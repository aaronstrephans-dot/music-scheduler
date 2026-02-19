"""
engine/models.py — Canonical field definitions and defaults for all data models,
reverse-engineered from the Music1 (.m1) database schema.
"""

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Track defaults  (mirrors Music1 Songs table)
# ---------------------------------------------------------------------------

TRACK_DEFAULTS = {
    # --- Core (required by API) ---
    "title":             "",
    "artist":            "",
    "category":          "",

    # --- Playback timing (milliseconds, like Music1) ---
    "duration_ms":       0,        # total length
    "intro_ms":          0,        # spoken intro / cold start
    "outro_ms":          0,        # tail after vocals end
    "hook_in_ms":        0,        # hook start
    "hook_out_ms":       0,        # hook end
    "mix_in_ms":         0,        # recommended mix-in point
    "mix_out_ms":        0,        # recommended mix-out point

    # Convenience alias kept for backwards compat
    "duration_seconds":  None,     # if set, overrides duration_ms on import

    # --- Musical attributes (0 = not set; 1-5 scale unless noted) ---
    "gender":    0,   # 0=unset 1=male 2=female 3=group 4=instrumental 5=mixed
    "tempo":     0,   # 1=slow … 5=fast
    "tempo_min": 0,
    "tempo_max": 0,
    "texture":   0,   # 1=open … 5=busy
    "texture_min": 0,
    "texture_max": 0,
    "mood":      0,   # 1=joyful 2=inspirational 3=reflective 4=contemplative 5=somber
    "key1":      0,   # musical key (0=unset, 1=C … 12=B)
    "key2":      0,   # secondary/compatible key
    "bpm":       None,

    # --- Sound codes (list of active 1-indexed code numbers, max 30) ---
    # e.g. [1, 5, 12] means SC1, SC5, SC12 are set
    "sound_codes": [],

    # --- Energy / mood (legacy free-form float kept for compat) ---
    "energy": None,

    # --- Hour / day restrictions ---
    "hour_restricted": False,
    # 24-char string "1" = allowed, "0" = blocked, one per hour 0-23
    "allowed_hours":   "111111111111111111111111",
    # 7-char string Mon-Sun
    "allowed_days":    "1111111",
    "start_hour":      0,    # 0 = no restriction
    "end_hour":        0,

    # --- Date range (ISO date strings or None) ---
    "start_date": None,
    "end_date":   None,
    "hit_date":   None,

    # --- Hour position ---
    "can_open_hour":  True,   # allowed as first song in an hour
    "can_close_hour": True,   # allowed as last song in an hour

    # --- Secondary artist ---
    "artist2_id":   None,   # FK to artist record
    "alt_artists":  "",     # free-text alternative artist names

    # --- Automation system ---
    "cart":       "",   # cart number in playout system
    "file_path":  "",   # file path in playout system
    "auto_params": "",  # automation extra params
    "id_in_player": "",

    # --- Music metadata ---
    "album":          "",
    "genre":          "",
    "composer":       "",
    "arranger":       "",
    "publisher":      "",
    "record_label":   "",
    "catalog_num":    "",
    "origin":         "",
    "prog_type":      "",
    "prod_source":    "",
    "music_usage":    "",

    # --- Licensing / compliance ---
    "isrc_code":       "",
    "work_code":       "",
    "recording_code":  "",
    "native_content":  False,
    "mcps":            False,
    "prior_approval":  False,

    # --- Custom user fields (free text) ---
    "user1": "",
    "user2": "",
    "user3": "",
    "user4": "",

    # --- Scheduling behaviour ---
    "announcer":       0,    # required announcer (0 = any)
    "link_type":       0,    # 0=none 1=hard-link-next 2=hard-link-prev
    "link_align":      0,
    "pct_play":        100,  # percentage weight within category (vs peers)
    "chart_position":  0,

    # --- Play tracking ---
    "play_count":      0,
    "last_played_at":  None,
    "added_at":        None,

    # --- Active status ---
    # False = track is excluded from scheduling (e.g. inactive seasonal content)
    "active":          True,

    # --- Song stacking ---
    # stack_key: group name for rotation stacking.
    #   All tracks sharing a key cycle through each other in order before repeating,
    #   and are kept separated by stack_key_separation_songs.
    #   Use cases:
    #     - Many songs by one artist: stack_key = "artist:phil-collins"
    #     - Multiple versions of a title: stack_key = "we-three-kings"
    "stack_key":       "",
    # stack_order: explicit position within the stack (0 = auto-ordered by last_played_at)
    "stack_order":     0,
}


def make_track(data: dict) -> dict:
    """Return a new track dict merging defaults with caller data."""
    import uuid
    track = {**TRACK_DEFAULTS, "id": str(uuid.uuid4()), "added_at": _now()}
    track.update({k: v for k, v in data.items() if k != "id"})
    # Backfill duration_ms from duration_seconds if needed
    if not track["duration_ms"] and track.get("duration_seconds"):
        track["duration_ms"] = int(track["duration_seconds"]) * 1000
    return track


# ---------------------------------------------------------------------------
# Artist defaults  (mirrors Music1 Artists table)
# ---------------------------------------------------------------------------

ARTIST_DEFAULTS = {
    "name":           "",
    "name_key":       "",    # uppercase stripped key for collision detection
    "alpha_key":      "",    # sort key (e.g. "CASH JOHNNY" for "Johnny Cash")
    "canon_key":      "",    # canonical name for group separation
    "rec_type":       0,     # 0=solo 1=duo 2=group
    "separation_ms":  5400000,  # 90 min default (Music1 stores ms)
    "group_id":       None,  # artists in same group share separation
    "gender":         0,
    "allow_double":   False,
    "auto_sep":       True,
}


def make_artist(data: dict) -> dict:
    import uuid
    artist = {**ARTIST_DEFAULTS, "id": str(uuid.uuid4()), "added_at": _now()}
    artist.update({k: v for k, v in data.items() if k != "id"})
    if not artist["name_key"] and artist["name"]:
        artist["name_key"] = artist["name"].upper()
    return artist


# ---------------------------------------------------------------------------
# Category defaults  (mirrors Music1 Categories table)
# ---------------------------------------------------------------------------

CATEGORY_DEFAULTS = {
    "name":                   "",
    "type":                   1,       # 1=rotation 2=spot 3=liner
    "color":                  None,    # hex string e.g. "#FFD700"
    "priority":               0,       # lower number = higher priority
    "grouping":               0,

    # Separation (milliseconds)
    "title_separation_ms":    7200000,  # 2 hours
    "prev_day_sep_ms":        0,        # same-hour prev-day separation

    # Alternate / fallback categories (IDs)
    "alternate1":             None,
    "alternate2":             None,
    "alternate3":             None,

    # Rotation behaviour
    "play_by_pct":            False,
    "is_packet":              False,
    "show_packets":           True,
    "schedulable":            True,
    "force_rank_rotation":    False,   # cycle by rank instead of random
    "recycle":                True,    # restart rotation after all songs played
    "min_rotation":           35,      # minimum songs before repeating
    "search_depth":           1,       # how many alternates deep to search

    # Restrictions
    "enforce_artist_sep":          True,
    "exclude_frequent_hours":      False,
    "exclude_same_hour_prev_day":  False,
    "allow_unscheduled":           True,
    "flip_restricted_play":        False,

    # Auto-calculated flags
    "auto_set_title_sep":     True,
    "auto_set_prev_day_sep":  False,
    "auto_set_search_depth":  True,
    "auto_set_min_rotation":  True,

    # Stacking: minimum songs between tracks that share the same stack_key.
    # 0 = use the global rules value (stack_key_separation_songs).
    "stack_key_separation_songs": 0,

    # Scheduling mode
    "sched_mode":             1,       # 1=normal 2=packet

    # Stats (maintained by scheduler)
    "num_songs":              0,
    "avg_length_ms":          0,
    "total_plays":            0,
}


def make_category(data: dict) -> dict:
    import uuid
    cat = {**CATEGORY_DEFAULTS, "id": str(uuid.uuid4()), "added_at": _now()}
    cat.update({k: v for k, v in data.items() if k != "id"})
    return cat


# ---------------------------------------------------------------------------
# Daypart defaults  (mirrors Music1 Vars DPName/DPColor)
# ---------------------------------------------------------------------------

DAYPART_DEFAULTS = {
    "name":       "",
    "start_hour": 0,   # inclusive
    "end_hour":   0,   # exclusive (6 = ends at 06:00 = 5:59)
    "color":      None,
}

DEFAULT_DAYPARTS = [
    {"name": "Early Morning",    "start_hour": 0,  "end_hour": 6,  "color": "#8421FF"},
    {"name": "Morning Drive",    "start_hour": 6,  "end_hour": 10, "color": "#FFFF00"},
    {"name": "Mid-morning",      "start_hour": 10, "end_hour": 12, "color": "#00FF00"},
    {"name": "Mid-day",          "start_hour": 12, "end_hour": 15, "color": "#4080FF"},
    {"name": "Mid-afternoon",    "start_hour": 15, "end_hour": 16, "color": "#FF0000"},
    {"name": "Afternoon Drive",  "start_hour": 16, "end_hour": 19, "color": "#00FFFF"},
    {"name": "Evening",          "start_hour": 19, "end_hour": 22, "color": "#FF80FF"},
    {"name": "Overnight",        "start_hour": 22, "end_hour": 24, "color": "#808080"},
]


def make_daypart(data: dict) -> dict:
    import uuid
    dp = {**DAYPART_DEFAULTS, "id": str(uuid.uuid4()), "added_at": _now()}
    dp.update({k: v for k, v in data.items() if k != "id"})
    return dp


# ---------------------------------------------------------------------------
# Day template defaults  (mirrors Music1 Days table)
# ---------------------------------------------------------------------------

DAY_TEMPLATE_DEFAULTS = {
    "name":             "",
    "hours_in_day":     24,
    "time_change_hour": 0,
    "recycle_from_hour": 0,
    # Map hour (string "0"-"23") to clock_id or None
    "hours": {str(h): None for h in range(24)},
}


def make_day_template(data: dict) -> dict:
    import uuid
    tmpl = {**DAY_TEMPLATE_DEFAULTS, "id": str(uuid.uuid4()), "added_at": _now()}
    # Deep-merge hours
    incoming_hours = data.pop("hours", {})
    tmpl.update({k: v for k, v in data.items() if k != "id"})
    tmpl["hours"] = {**DAY_TEMPLATE_DEFAULTS["hours"], **{str(k): v for k, v in incoming_hours.items()}}
    return tmpl


# ---------------------------------------------------------------------------
# Clock defaults  (mirrors Music1 Clocks table)
# ---------------------------------------------------------------------------

CLOCK_DEFAULTS = {
    "name":  "",
    "slots": [],

    # Separation
    "artist_separation_songs": 9,   # fallback song-count separation

    # Time budget (seconds; None = unconstrained)
    "nominal_time_s":   3600,
    "hard_min_time_s":  None,
    "hard_max_time_s":  None,

    # Cross-day checks
    "check_prev_day_song":   False,
    "check_prev_day_artist": False,

    # Double shots
    "allow_double_shots":         False,
    "double_shot_separation_songs": 0,

    "no_repeats":         True,
    "fixed_time_enabled": False,
    "absolute_time":      False,

    # Attribute flow rules (max consecutive songs with same attribute value)
    # -1 = unlimited
    "max_gender_run":  -1,
    "max_tempo_run":   -1,
    "max_texture_run": -1,
    "max_mood_run":    -1,
}


def make_clock(data: dict) -> dict:
    import uuid
    clock = {**CLOCK_DEFAULTS, "id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now()}
    clock.update({k: v for k, v in data.items() if k != "id"})
    return clock


# ---------------------------------------------------------------------------
# Clock slot (ClockItem) defaults  (mirrors Music1 ClockItems table)
# ---------------------------------------------------------------------------

SLOT_DEFAULTS = {
    "category":    "",
    "title":       "",    # display label for this slot
    "type":        "music",  # music | spot | liner | link | sweeper | void

    # Timing (seconds; None = unconstrained / use track's actual length)
    "nominal_length_s":     None,
    "max_length_s":         None,
    "min_length_s":         None,
    "nominal_start_time_s": None,  # offset from top of hour
    "min_start_time_s":     None,
    "max_start_time_s":     None,
    "fixed_start_time":     False,

    # Timing behaviour
    "leave_gap":          False,
    "clip_overrun":       False,
    "report_nominal_time": False,
    "fill_completely":    False,
    "fill_to_match":      False,
    "fill_to_minimum":    False,
    "fit_to_time":        False,

    # Fill control
    "avail_type":   0,
    "max_units":    0,
    "fill_priority": 5,

    # Attribute filters for this slot (None = any; value = required)
    "gender":      None,
    "tempo":       None,
    "texture":     None,
    "mood":        None,
    "sound_codes": None,   # list of required sound-code numbers, or None
    "sc_and":      False,  # True = all codes required; False = any

    # Other slot filters
    "require_native":    False,
    "announcer":         None,
    "dbl_shot_artists":  False,

    # Cluster display
    "cluster_name":  None,
    "cluster_color": None,
    "in_cluster":    False,

    # Hour restrictions
    "hour_restricted": False,
    "allowed_hours":   None,   # same 24-char string format as tracks

    # Link
    "link_type": 0,
    "link_to":   None,

    # Misc
    "insert_if_empty": False,
    "notes":           "",
    "color":           None,

    # --- Lognote (automation command) ---
    # Used when type = "lognote".  The command string is passed through verbatim
    # to the playout automation system (e.g. ",,COM,DALIVE,\"20:00 STOPSET\",,0").
    "lognote_command": "",

    # --- Conditional slot ---
    # If set, this slot is only included when the scheduling context matches.
    # condition_daypart: name of the daypart (e.g. "Morning Drive") — None = always
    # condition_start_date / condition_end_date: ISO date strings — None = no limit
    "condition_daypart":    None,
    "condition_start_date": None,
    "condition_end_date":   None,
}


def make_slot(data: dict) -> dict:
    slot = {**SLOT_DEFAULTS}
    slot.update(data)
    return slot
