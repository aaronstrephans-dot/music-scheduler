"""
engine/validator.py — Schedule validator with Music1-equivalent checks.
"""
from collections import Counter
from datetime import datetime, timezone

from engine.rules import DEFAULT_RULES


def _now_utc():
    return datetime.now(timezone.utc)


def _today_iso():
    return _now_utc().date().isoformat()


def _hms(seconds: int) -> str:
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def validate_schedule(tracks: list, rules: dict = None,
                      categories: list = None) -> dict:
    """
    Validate a scheduled track list against separation rules.

    Args:
        tracks:     list of slot dicts from a schedule's "tracks" field.
        rules:      separation rules dict; falls back to DEFAULT_RULES if None.
        categories: list of category records (for category-level separation overrides).

    Returns:
        {
          "valid":      bool,
          "violations": [...],
          "stats":      {...},
        }
    """
    if rules is None:
        rules = DEFAULT_RULES

    # Build category lookup
    cat_lookup = {}
    for c in (categories or []):
        cat_lookup[c.get("name", "")] = c
        cat_lookup[c.get("id",   "")] = c

    violations: list = []
    artist_sep        = rules.get("artist_separation_songs", 9)
    title_sep_songs   = max(1, int(rules.get("title_separation_ms", 10800000) / 210000))
    today             = _today_iso()

    music_tracks = [t for t in tracks if t.get("type", "music") == "music"]

    for i, slot in enumerate(music_tracks):
        pos    = slot.get("position", i + 1)
        artist = (slot.get("artist") or "").strip().lower()
        title  = (slot.get("title")  or "").strip().lower()

        # --- Missing data ---
        if not artist:
            violations.append({
                "position": pos,
                "type":     "missing_artist",
                "severity": "error",
                "message":  f"Slot {pos} has no artist",
            })
        if not title:
            violations.append({
                "position": pos,
                "type":     "missing_title",
                "severity": "error",
                "message":  f"Slot {pos} has no title",
            })
        if not artist or not title:
            continue

        # --- Artist separation ---
        start = max(0, i - artist_sep)
        for j in range(start, i):
            prev = music_tracks[j]
            if (prev.get("artist") or "").strip().lower() == artist:
                gap = i - j
                violations.append({
                    "position": pos,
                    "type":     "artist_separation",
                    "severity": "warning",
                    "message":  (
                        f"'{slot.get('artist')}' at slot {pos} also at slot "
                        f"{prev.get('position', j + 1)} "
                        f"(gap: {gap} songs, rule: ≥{artist_sep})"
                    ),
                })
                break

        # --- Title separation ---
        start = max(0, i - title_sep_songs)
        for j in range(start, i):
            prev = music_tracks[j]
            if (prev.get("title") or "").strip().lower() == title:
                gap = i - j
                violations.append({
                    "position": pos,
                    "type":     "title_separation",
                    "severity": "error",
                    "message":  (
                        f"'{slot.get('title')}' at slot {pos} also at slot "
                        f"{prev.get('position', j + 1)} "
                        f"(gap: {gap} songs)"
                    ),
                })
                break

        # --- Date range check ---
        if rules.get("enforce_date_range", True):
            start_date = slot.get("start_date")
            end_date   = slot.get("end_date")
            if start_date and today < start_date:
                violations.append({
                    "position": pos,
                    "type":     "date_not_started",
                    "severity": "warning",
                    "message":  f"'{slot.get('title')}' at slot {pos}: start_date {start_date} is in the future",
                })
            if end_date and today > end_date:
                violations.append({
                    "position": pos,
                    "type":     "date_expired",
                    "severity": "warning",
                    "message":  f"'{slot.get('title')}' at slot {pos}: end_date {end_date} has passed",
                })

        # --- Attribute run limits ---
        for attr, rule_key in (
            ("gender",  "max_gender_run"),
            ("tempo",   "max_tempo_run"),
            ("texture", "max_texture_run"),
            ("mood",    "max_mood_run"),
        ):
            max_run = rules.get(rule_key, -1)
            if max_run < 0:
                continue
            val = slot.get(attr, 0)
            if not val:
                continue
            run = 0
            for j in range(i - 1, -1, -1):
                if music_tracks[j].get(attr, 0) == val:
                    run += 1
                else:
                    break
            if run >= max_run:
                violations.append({
                    "position": pos,
                    "type":     f"{attr}_run_exceeded",
                    "severity": "warning",
                    "message":  (
                        f"'{slot.get('title')}' at slot {pos}: "
                        f"{attr}={val} run of {run + 1} exceeds max {max_run}"
                    ),
                })

    # --- Stats ---
    artists    = Counter(
        (t.get("artist") or "").strip() for t in music_tracks if (t.get("artist") or "").strip()
    )
    categories_ct = Counter(t.get("category") or "Unknown" for t in music_tracks)
    total_secs    = sum((t.get("duration_seconds") or 0) for t in tracks)

    errors   = sum(1 for v in violations if v["severity"] == "error")
    warnings = sum(1 for v in violations if v["severity"] == "warning")

    stats = {
        "total_slots":            len(tracks),
        "music_slots":            len(music_tracks),
        "unique_artists":         len(artists),
        "top_artists":            dict(artists.most_common(5)),
        "category_breakdown":     dict(categories_ct),
        "total_duration_seconds": total_secs,
        "total_duration_hms":     _hms(total_secs),
        "errors":                 errors,
        "warnings":               warnings,
    }

    return {
        "valid":      errors == 0,
        "violations": violations,
        "stats":      stats,
    }
