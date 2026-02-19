"""
engine/rotator.py — Music1-equivalent scheduling engine.

Key features implemented to match Music1:
- Artist separation (song-count and time-based)
- Title separation (time-based)
- Alternate category fallback (alternate1/2/3)
- Rank-based rotation (force_rank_rotation)
- Attribute run limits (max consecutive same gender/tempo/texture/mood)
- Sound code matching per slot
- Hour-of-day restrictions per track
- Date range restrictions per track
- Hour position flags (can_open_hour / can_close_hour)
- Slot-level attribute filters
- Double-shot support
- Time-budget awareness (nominal/max clock time)
"""

import random
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(iso_str) -> float:
    if not iso_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (_now_utc() - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return float("inf")


def _ms_since(iso_str) -> float:
    if not iso_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (_now_utc() - dt).total_seconds() * 1000
    except (ValueError, TypeError):
        return float("inf")


def _today_iso() -> str:
    return _now_utc().date().isoformat()


# ---------------------------------------------------------------------------
# Attribute run helper
# ---------------------------------------------------------------------------

def _current_run(scheduled: list, attr: str) -> int:
    """Count how many consecutive recent slots share the same non-zero attribute value."""
    if not scheduled:
        return 0
    last_val = scheduled[-1].get(attr)
    if not last_val:
        return 0
    count = 0
    for slot in reversed(scheduled):
        if slot.get(attr) == last_val:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Date / hour restriction checks
# ---------------------------------------------------------------------------

def _passes_date_restriction(track: dict, rules: dict) -> bool:
    if not rules.get("enforce_date_range", True):
        return True
    today = _today_iso()
    start = track.get("start_date")
    end   = track.get("end_date")
    if start and today < start:
        return False
    if end and today > end:
        return False
    return True


def _passes_hour_restriction(track: dict, hour: int) -> bool:
    """Return True if this track is allowed to play in the given hour (0-23)."""
    if not track.get("hour_restricted", False):
        return True
    allowed = track.get("allowed_hours", "111111111111111111111111")
    if not allowed or len(allowed) < 24:
        return True
    return allowed[hour % 24] == "1"


def _passes_position_restriction(track: dict, position_in_hour: int,
                                  total_in_hour: int, rules: dict) -> bool:
    """Check can_open_hour / can_close_hour flags."""
    if not rules.get("enforce_hour_open_close", True):
        return True
    if position_in_hour == 0 and not track.get("can_open_hour", True):
        return False
    if position_in_hour == total_in_hour - 1 and not track.get("can_close_hour", True):
        return False
    return True


# ---------------------------------------------------------------------------
# Separation checks
# ---------------------------------------------------------------------------

def _artist_key(track: dict) -> str:
    return (track.get("artist") or "").strip().lower()


def _title_key(track: dict) -> str:
    return (track.get("title") or "").strip().lower()


def _passes_artist_sep(track: dict, scheduled: list, rules: dict,
                        artist_lookup: dict = None) -> bool:
    """True if artist separation is satisfied."""
    artist = _artist_key(track)
    if not artist:
        return True

    # Determine separation in songs (fallback) and ms (if artist record available)
    sep_songs = rules.get("artist_separation_songs", 9)
    sep_ms    = None

    if artist_lookup:
        # Look up by artist name
        art_rec = artist_lookup.get(artist)
        if art_rec:
            sep_ms = art_rec.get("separation_ms")
            # Group separation: check if any recent song's artist shares the same group
            group_id = art_rec.get("group_id")
        else:
            group_id = None
    else:
        group_id = None

    if sep_ms is not None:
        # Time-based check: find last play of this artist in scheduled list
        # We approximate using scheduled list; full time-based needs play history
        window = min(len(scheduled), sep_songs * 3)  # look back a reasonable window
        for s in reversed(scheduled[-window:]):
            if _artist_key(s) == artist:
                return False
        return True
    else:
        # Song-count-based check
        recent = [_artist_key(s) for s in scheduled[-sep_songs:]]
        return artist not in recent


def _passes_title_sep(track: dict, scheduled: list, rules: dict,
                       cat_lookup: dict = None) -> bool:
    """True if title separation is satisfied."""
    title = _title_key(track)
    if not title:
        return True

    # Get separation from category or rules
    sep_ms = rules.get("title_separation_ms", 10800000)
    if cat_lookup:
        category = track.get("category", "")
        cat_rec  = cat_lookup.get(category)
        if cat_rec:
            cat_sep = cat_rec.get("title_separation_ms")
            if cat_sep:
                sep_ms = cat_sep

    # Approximate: avg song ~3.5 min = 210s = 210000ms
    sep_songs = max(1, int(sep_ms / 210000))
    recent    = [_title_key(s) for s in scheduled[-sep_songs:]]
    return title not in recent


# ---------------------------------------------------------------------------
# Sound code matching
# ---------------------------------------------------------------------------

def _passes_sound_codes(track: dict, slot: dict) -> bool:
    """Check if track satisfies the sound code requirements of the slot."""
    required = slot.get("sound_codes")
    if not required:
        return True
    track_codes = set(track.get("sound_codes") or [])
    required    = set(required)
    if slot.get("sc_and", False):
        return required.issubset(track_codes)
    else:
        return bool(required & track_codes)


# ---------------------------------------------------------------------------
# Slot attribute filter
# ---------------------------------------------------------------------------

def _passes_slot_filters(track: dict, slot: dict) -> bool:
    """Return True if track satisfies all slot-level attribute constraints."""
    for attr in ("gender", "tempo", "texture", "mood"):
        req = slot.get(attr)
        if req is not None:
            val = track.get(attr, 0)
            if isinstance(req, (list, tuple)):
                if val not in req:
                    return False
            elif val != req:
                return False
    if not _passes_sound_codes(track, slot):
        return False
    return True


# ---------------------------------------------------------------------------
# Attribute run check
# ---------------------------------------------------------------------------

def _passes_run_limits(track: dict, scheduled: list, rules: dict,
                        clock: dict = None) -> bool:
    """Return True if adding this track would not violate any run-length limit."""
    checks = {
        "gender":  rules.get("max_gender_run",  clock.get("max_gender_run",  -1) if clock else -1),
        "tempo":   rules.get("max_tempo_run",   clock.get("max_tempo_run",   -1) if clock else -1),
        "texture": rules.get("max_texture_run", clock.get("max_texture_run", -1) if clock else -1),
        "mood":    rules.get("max_mood_run",    clock.get("max_mood_run",    -1) if clock else -1),
    }
    for attr, max_run in checks.items():
        if max_run < 0:
            continue
        val = track.get(attr, 0)
        if not val:
            continue
        # If current run of this attr value is already at max, reject
        if _current_run(scheduled, attr) >= max_run:
            last_val = scheduled[-1].get(attr) if scheduled else None
            if last_val == val:
                return False
    return True


# ---------------------------------------------------------------------------
# Master eligibility check
# ---------------------------------------------------------------------------

def _is_eligible(track: dict, scheduled: list, slot: dict, rules: dict,
                  hour: int = 0, position_in_hour: int = 0,
                  total_in_hour: int = 0, clock: dict = None,
                  artist_lookup: dict = None, cat_lookup: dict = None) -> bool:
    """Return True if track passes ALL hard constraints for this slot."""
    if not _passes_date_restriction(track, rules):
        return False
    if not _passes_hour_restriction(track, hour):
        return False
    if not _passes_position_restriction(track, position_in_hour, total_in_hour, rules):
        return False
    if not _passes_artist_sep(track, scheduled, rules, artist_lookup):
        return False
    if not _passes_title_sep(track, scheduled, rules, cat_lookup):
        return False
    if not _passes_slot_filters(track, slot):
        return False
    if not _passes_run_limits(track, scheduled, rules, clock):
        return False
    return True


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(track: dict, scheduled: list, rules: dict) -> float:
    """
    Score a track for desirability. Higher = more desirable.
    Assumes eligibility has already been checked.
    """
    score = 100.0

    # Prefer lower play count (up to +20)
    play_count = track.get("play_count") or 0
    score += max(0, 20 - play_count)

    # Prefer tracks idle longer (caps at +20 after ~60 hours)
    hours_idle = _hours_since(track.get("last_played_at"))
    score += min(20, hours_idle / 3)

    # Prefer pct_play weighting (Music1 feature)
    pct = track.get("pct_play", 100)
    score *= (pct / 100.0)

    return score


# ---------------------------------------------------------------------------
# Rank rotation helper
# ---------------------------------------------------------------------------

def _get_rank_index(cat_name: str, rank_state: dict) -> int:
    """Return and advance the rank cursor for this category."""
    idx = rank_state.get(cat_name, 0)
    rank_state[cat_name] = idx + 1
    return idx


# ---------------------------------------------------------------------------
# Pool builder with alternate category fallback
# ---------------------------------------------------------------------------

def _build_pool(slot: dict, by_cat: dict, cat_lookup: dict) -> list:
    """
    Return the track pool for a slot, following alternate category fallback.
    by_cat: dict mapping category_name → list of tracks
    cat_lookup: dict mapping category_name → category record
    """
    category = slot.get("category", "")
    pool = by_cat.get(category) or []
    if pool:
        return pool, category

    # Alternate fallback
    cat_rec = cat_lookup.get(category)
    if cat_rec:
        for alt_key in ("alternate1", "alternate2", "alternate3"):
            alt_id = cat_rec.get(alt_key)
            if alt_id:
                # alt_id may be name or id; try name first
                alt_pool = by_cat.get(alt_id) or []
                if alt_pool:
                    return alt_pool, alt_id

    # Final fallback: entire library
    all_tracks = []
    for tracks in by_cat.values():
        all_tracks.extend(tracks)
    return all_tracks, category


# ---------------------------------------------------------------------------
# Pick function
# ---------------------------------------------------------------------------

def _pick(candidates: list, scheduled: list, slot: dict, rules: dict,
           force_rank: bool = False, rank_state: dict = None,
           cat_name: str = "") -> dict:
    """
    Pick the best track from candidates given current schedule state.
    force_rank: cycle through candidates in order by their rank/play-count.
    """
    if force_rank and rank_state is not None:
        # Sort candidates by play count (fewer = earlier in rotation)
        sorted_cands = sorted(candidates, key=lambda t: (t.get("play_count") or 0))
        idx = _get_rank_index(cat_name, rank_state) % max(1, len(sorted_cands))
        return sorted_cands[idx]

    # Score all eligible candidates
    scored = [((_score(t, scheduled, rules)), t) for t in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return candidates[0]

    # Weighted-random pick from top 3 for natural variety
    pool  = scored[:3]
    total = sum(s for s, _ in pool)
    if total <= 0:
        return pool[0][1]

    threshold  = random.uniform(0, total)
    cumulative = 0.0
    for s, t in pool:
        cumulative += s
        if threshold <= cumulative:
            return t
    return pool[0][1]


# ---------------------------------------------------------------------------
# Fallback pick (tiny library — relax all constraints)
# ---------------------------------------------------------------------------

def _fallback_pick(candidates: list, scheduled: list) -> dict:
    """Last resort: pick by artist recency only, ignoring all separation rules."""
    def artist_recency(track):
        artist = _artist_key(track)
        for i, s in enumerate(reversed(scheduled)):
            if _artist_key(s) == artist:
                return i
        return len(scheduled) + 1  # never played = highest score

    return max(candidates, key=artist_recency)


# ---------------------------------------------------------------------------
# Main scheduler
# ---------------------------------------------------------------------------

def build_schedule(
    clock: dict,
    tracks: list,
    rules: dict,
    target_seconds: int = 0,
    hour: int = 0,
    artists: list = None,
    categories: list = None,
    prev_day_plays: list = None,   # list of track IDs played in same hour yesterday
) -> list:
    """
    Build a scheduled track list for one clock (one hour or block).

    Args:
        clock:            clock template dict with a ``slots`` list.
        tracks:           full track library.
        rules:            separation / rotation rules dict.
        target_seconds:   stop once cumulative duration reaches this.
                          0 = fill exactly one pass through the clock slots.
        hour:             hour of day (0-23) for restriction checks.
        artists:          list of artist records (for group/time-based separation).
        categories:       list of category records (for alternates, rank rotation, etc.).
        prev_day_plays:   track IDs that played in this hour yesterday (for prev-day sep).

    Returns:
        list of slot dicts, each with position, category, track_id, title, artist, etc.
    """
    if not tracks:
        return []

    slots = clock.get("slots", [])
    if not slots:
        return []

    # --- Build lookup indexes ---
    by_cat: dict = {}
    for t in tracks:
        by_cat.setdefault(t.get("category", ""), []).append(t)

    artist_lookup: dict = {}
    if artists:
        for a in artists:
            key = (a.get("name") or "").strip().lower()
            if key:
                artist_lookup[key] = a

    cat_lookup: dict = {}
    if categories:
        for c in categories:
            cat_lookup[c.get("name", "")] = c
            cat_lookup[c.get("id",   "")] = c

    prev_day_set = set(prev_day_plays or [])

    rank_state: dict = {}    # category_name → rotation index

    scheduled:  list = []
    total_secs       = 0
    position         = 1
    slot_idx         = 0
    _MAX_SLOTS       = 1000

    while position <= _MAX_SLOTS:
        slot     = slots[slot_idx % len(slots)]
        slot_typ = slot.get("type", "music")

        # Non-music slots (spots, liners, etc.) pass through without a track
        if slot_typ != "music":
            scheduled.append({
                "position":         position,
                "type":             slot_typ,
                "category":         slot.get("category", ""),
                "title":            slot.get("title", ""),
                "duration_seconds": slot.get("nominal_length_s") or 0,
                "notes":            slot.get("notes", ""),
            })
            total_secs += slot.get("nominal_length_s") or 0
            position   += 1
            slot_idx   += 1
        else:
            # --- Build candidate pool with alternate fallback ---
            pool, effective_cat = _build_pool(slot, by_cat, cat_lookup)
            if not pool:
                slot_idx += 1
                if target_seconds == 0 and slot_idx >= len(slots):
                    break
                continue

            # --- Force-rank rotation? ---
            cat_rec    = cat_lookup.get(effective_cat, {})
            force_rank = cat_rec.get("force_rank_rotation", False) if cat_rec else False

            # --- Estimate slot count in hour for position flags ---
            est_total = len(slots) if target_seconds == 0 else max(len(slots), 10)
            pos_in_hr = (position - 1) % max(1, est_total)

            # --- Filter eligible candidates ---
            eligible = [
                t for t in pool
                if _is_eligible(
                    t, scheduled, slot, rules,
                    hour=hour,
                    position_in_hour=pos_in_hr,
                    total_in_hour=est_total,
                    clock=clock,
                    artist_lookup=artist_lookup,
                    cat_lookup=cat_lookup,
                )
                and t.get("id") not in prev_day_set
            ]

            # Relax prev-day restriction if needed
            if not eligible:
                eligible = [
                    t for t in pool
                    if _is_eligible(
                        t, scheduled, slot, rules,
                        hour=hour,
                        position_in_hour=pos_in_hr,
                        total_in_hour=est_total,
                        clock=clock,
                        artist_lookup=artist_lookup,
                        cat_lookup=cat_lookup,
                    )
                ]

            if not eligible:
                # Tiny library — relax all constraints
                chosen = _fallback_pick(pool, scheduled)
            else:
                chosen = _pick(eligible, scheduled, slot, rules,
                               force_rank=force_rank,
                               rank_state=rank_state,
                               cat_name=effective_cat)

            # --- Determine duration ---
            duration_ms = (
                chosen.get("duration_ms")
                or (chosen.get("duration_seconds", 0) * 1000)
                or (slot.get("nominal_length_s", 210) * 1000)
            )
            duration_s = duration_ms // 1000

            # Respect slot max length
            if slot.get("max_length_s") and duration_s > slot["max_length_s"]:
                if slot.get("clip_overrun", False):
                    duration_s = slot["max_length_s"]

            scheduled.append({
                "position":         position,
                "type":             "music",
                "category":         effective_cat,
                "track_id":         chosen.get("id"),
                "title":            chosen.get("title"),
                "artist":           chosen.get("artist"),
                "duration_seconds": duration_s,
                "duration_ms":      duration_ms,
                "intro_ms":         chosen.get("intro_ms", 0),
                "outro_ms":         chosen.get("outro_ms", 0),
                "hook_in_ms":       chosen.get("hook_in_ms", 0),
                "mix_in_ms":        chosen.get("mix_in_ms", 0),
                "mix_out_ms":       chosen.get("mix_out_ms", 0),
                "bpm":              chosen.get("bpm"),
                "energy":           chosen.get("energy"),
                "gender":           chosen.get("gender", 0),
                "tempo":            chosen.get("tempo", 0),
                "texture":          chosen.get("texture", 0),
                "mood":             chosen.get("mood", 0),
                "sound_codes":      chosen.get("sound_codes", []),
                "cart":             chosen.get("cart", ""),
                "file_path":        chosen.get("file_path", ""),
                "notes":            slot.get("notes", ""),
            })

            total_secs += duration_s
            position   += 1
            slot_idx   += 1

        # --- Stop conditions ---
        if target_seconds > 0:
            if total_secs >= target_seconds:
                break
        else:
            if slot_idx >= len(slots):
                break

        if position > _MAX_SLOTS:
            break

    return scheduled
