import random
from datetime import datetime, timezone


def _hours_since(iso_str) -> float:
    """Hours elapsed since an ISO-8601 timestamp. Returns inf for None/invalid."""
    if not iso_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return float("inf")


def _score(track: dict, scheduled: list, rules: dict):
    """
    Score a candidate track for the next slot.

    Returns None if the track is hard-excluded (title or artist too recent).
    Higher score = more desirable pick.
    """
    artist = (track.get("artist") or "").lower()
    title  = (track.get("title")  or "").lower()

    # Hard exclusion: same title too recently (approximate from hours → songs)
    title_sep_songs  = max(1, int(rules.get("title_separation_hours", 3) * 60 / 3.5))
    recent_titles    = [(t.get("title") or "").lower() for t in scheduled[-title_sep_songs:]]
    if title in recent_titles:
        return None

    # Hard exclusion: same artist too recently
    artist_sep     = rules.get("artist_separation_songs", 9)
    recent_artists = [(t.get("artist") or "").lower() for t in scheduled[-artist_sep:]]
    if artist in recent_artists:
        return None

    score = 100.0

    # Prefer tracks with a lower play count (up to +20)
    play_count = track.get("play_count") or 0
    score += max(0, 20 - play_count)

    # Prefer tracks idle for longer (caps at +20 after ~60 hours)
    hours = _hours_since(track.get("last_played_at"))
    score += min(20, hours / 3)

    return score


def _artist_recency_score(track: dict, scheduled: list) -> float:
    """
    Fallback score when all tracks are hard-excluded (tiny library).
    Returns how many positions ago the artist last appeared — higher means longer ago.
    Never-appeared artists score highest (len + 1).
    """
    artist   = (track.get("artist") or "").lower()
    last_pos = -1
    for i, s in enumerate(scheduled):
        if (s.get("artist") or "").lower() == artist:
            last_pos = i
    return float(len(scheduled) - last_pos)  # range: 1 (just played) to len+1 (never)


def _pick(candidates: list, scheduled: list, rules: dict) -> dict:
    """Score every candidate and return the best pick, with fallback for tiny libraries."""
    scored = []
    for t in candidates:
        s = _score(t, scheduled, rules)
        if s is not None:
            scored.append((s, t))

    if scored:
        # Weighted-random pick from top 3 for natural variety
        scored.sort(key=lambda x: x[0], reverse=True)
        pool  = scored[:3]
        total = sum(s for s, _ in pool)
        pick  = random.uniform(0, total) if total > 0 else 0.0

        chosen     = pool[0][1]
        cumulative = 0.0
        for s, t in pool:
            cumulative += s
            if pick <= cumulative:
                chosen = t
                break
        return chosen

    # Tiny-library fallback: all candidates hard-excluded.
    # Relax exclusions and pick deterministically by artist recency
    # so we still alternate artists as well as possible.
    fallback = sorted(
        [(_artist_recency_score(t, scheduled), t) for t in candidates],
        key=lambda x: x[0],
        reverse=True,
    )
    return fallback[0][1]


def build_schedule(
    clock: dict,
    tracks: list,
    rules: dict,
    target_seconds: int = 0,
) -> list:
    """
    Build a scheduled track list by cycling the clock template until
    ``target_seconds`` of content is accumulated.

    Args:
        clock:          clock template dict with a ``slots`` list.
        tracks:         full track library.
        rules:          separation / rotation rules.
        target_seconds: stop once cumulative duration reaches this value.
                        0 means "fill exactly one pass through the clock slots".

    Each returned slot dict contains:
        position, category, track_id, title, artist,
        duration_seconds, bpm, energy, mood, notes.
    """
    if not tracks:
        return []

    slots = clock.get("slots", [])
    if not slots:
        return []

    # Index tracks by category for fast lookup; fall back to full library
    by_cat: dict = {}
    for t in tracks:
        by_cat.setdefault(t.get("category", ""), []).append(t)

    scheduled: list = []
    total_secs      = 0
    position        = 1
    slot_idx        = 0
    _MAX_SLOTS      = 1000          # hard safety cap

    while position <= _MAX_SLOTS:
        slot     = slots[slot_idx % len(slots)]
        category = slot.get("category", "")
        pool     = by_cat.get(category) or tracks

        chosen   = _pick(pool, scheduled, rules)
        duration = chosen.get("duration_seconds") or slot.get("duration_seconds") or 210

        scheduled.append({
            "position":         position,
            "category":         category,
            "track_id":         chosen.get("id"),
            "title":            chosen.get("title"),
            "artist":           chosen.get("artist"),
            "duration_seconds": duration,
            "bpm":              chosen.get("bpm"),
            "energy":           chosen.get("energy"),
            "mood":             chosen.get("mood"),
            "notes":            slot.get("notes", ""),
        })

        total_secs += duration
        position   += 1
        slot_idx   += 1

        if target_seconds > 0:
            if total_secs >= target_seconds:
                break
        else:
            # No target: fill exactly one pass through the clock slots
            if slot_idx >= len(slots):
                break

    return scheduled
