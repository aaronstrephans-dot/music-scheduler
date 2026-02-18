"""
Schedule validator — checks a generated track list against separation rules
and returns a structured report with violations and stats.
"""
from collections import Counter

from engine.rules import DEFAULT_RULES


def validate_schedule(tracks: list, rules: dict = None) -> dict:
    """
    Validate a scheduled track list against separation rules.

    Args:
        tracks: list of slot dicts from a schedule's "tracks" field.
        rules:  separation rules dict; falls back to DEFAULT_RULES if None.

    Returns:
        {
          "valid":      bool,          # True when zero errors (warnings don't block)
          "violations": [...],         # list of violation dicts
          "stats":      {...},         # summary stats about the schedule
        }
    """
    if rules is None:
        rules = DEFAULT_RULES

    violations: list = []
    artist_sep       = rules.get("artist_separation_songs", 9)
    title_sep_songs  = max(1, int(rules.get("title_separation_hours", 3) * 60 / 3.5))

    for i, slot in enumerate(tracks):
        pos    = slot.get("position", i + 1)
        artist = (slot.get("artist") or "").strip().lower()
        title  = (slot.get("title")  or "").strip().lower()

        # --- Missing-data checks ---
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
            prev_artist = (tracks[j].get("artist") or "").strip().lower()
            if prev_artist == artist:
                gap = i - j
                violations.append({
                    "position":      pos,
                    "type":          "artist_separation",
                    "severity":      "warning",
                    "message": (
                        f"'{slot.get('artist')}' at slot {pos} also at slot "
                        f"{tracks[j].get('position', j + 1)} "
                        f"(gap: {gap} songs, rule: ≥{artist_sep})"
                    ),
                })
                break

        # --- Title separation ---
        start = max(0, i - title_sep_songs)
        for j in range(start, i):
            prev_title = (tracks[j].get("title") or "").strip().lower()
            if prev_title == title:
                gap = i - j
                violations.append({
                    "position":      pos,
                    "type":          "title_separation",
                    "severity":      "error",
                    "message": (
                        f"'{slot.get('title')}' at slot {pos} also at slot "
                        f"{tracks[j].get('position', j + 1)} "
                        f"(gap: {gap} songs)"
                    ),
                })
                break

    # --- Stats ---
    artists    = Counter(
        (t.get("artist") or "").strip() for t in tracks if (t.get("artist") or "").strip()
    )
    categories = Counter(t.get("category") or "Unknown" for t in tracks)
    total_secs = sum((t.get("duration_seconds") or 0) for t in tracks)

    errors   = sum(1 for v in violations if v["severity"] == "error")
    warnings = sum(1 for v in violations if v["severity"] == "warning")

    stats = {
        "total_slots":            len(tracks),
        "unique_artists":         len(artists),
        "top_artists":            dict(artists.most_common(5)),
        "category_breakdown":     dict(categories),
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


def _hms(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
