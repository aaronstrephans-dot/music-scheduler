"""
engine/rules.py — Global scheduling rules with Music1-equivalent defaults.
"""

DEFAULT_RULES = {
    # --- Artist separation ---
    "artist_separation_songs": 9,       # min songs between same artist
    "artist_separation_ms":    5400000, # min ms between same artist (90 min); used when artist record exists

    # --- Title separation ---
    "title_separation_hours": 3,        # min hours between same title
    "title_separation_ms":    10800000, # same, in milliseconds

    # --- Attribute run limits (max consecutive songs with same value; -1 = unlimited) ---
    "max_gender_run":  -1,
    "max_tempo_run":   3,
    "max_texture_run": -1,
    "max_mood_run":    -1,

    # --- Cross-day separation ---
    "check_prev_day_song":   False,   # avoid same song in same hour next day
    "check_prev_day_artist": False,

    # --- Categories (legacy simple list; used when no categories data model present) ---
    "categories": [
        {"name": "Current",   "rotation_hours": 2,  "weight": 40},
        {"name": "Recurrent", "rotation_hours": 4,  "weight": 30},
        {"name": "Gold",      "rotation_hours": 6,  "weight": 30},
    ],

    # --- Default category separations (ms) ---
    "default_title_separation_ms":    7200000,   # 2 hours
    "default_prev_day_separation_ms": 0,

    # --- Double shots ---
    "allow_double_shots":           False,
    "double_shot_separation_songs": 0,

    # --- Hour position ---
    "enforce_hour_open_close": True,   # respect can_open_hour / can_close_hour flags

    # --- Date restrictions ---
    "enforce_date_range": True,   # skip tracks where today is outside start_date/end_date

    # --- Song stacking ---
    # Minimum songs between any two tracks that share the same stack_key.
    # Individual categories can override this with their own stack_key_separation_songs.
    "stack_key_separation_songs": 3,
}


def merge_rules(overrides: dict) -> dict:
    """Return DEFAULT_RULES with caller-supplied overrides applied (shallow merge)."""
    rules = {**DEFAULT_RULES}
    rules.update(overrides)
    return rules
