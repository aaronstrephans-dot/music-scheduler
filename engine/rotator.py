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

Song stacking:
- stack_key on tracks groups songs for rotation fairness and separation.
  Use case A — many songs by one artist ("artist:phil-collins"):
    The scheduler cycles through all stacked songs in FIFO order
    (oldest last-played first), so every song in the stack plays before
    any repeats rather than the same few titles dominating.
  Use case B — multiple versions of a title ("we-three-kings"):
    The stack_key_separation_songs rule keeps versions apart in the
    schedule, just as artist separation keeps artists apart.
- active=False on a track excludes it from scheduling entirely (e.g.
  seasonal content that should not air outside its date range).

Clock versatility additions:
- lognote slot type: passes an automation command string through to the
  schedule output without selecting a music track.
- Conditional slots: condition_daypart / condition_start_date /
  condition_end_date let a slot be active only in certain contexts.
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

def _passes_date_restriction(track: dict, rules: dict, sched_date: str = None) -> bool:
    """Use sched_date (YYYY-MM-DD) for checks when generating a specific day; else today."""
    if not rules.get("enforce_date_range", True):
        return True
    ref_date = (sched_date or _today_iso()).strip()
    if not ref_date:
        ref_date = _today_iso()
    start = track.get("start_date")
    end   = track.get("end_date")
    if start and ref_date < start:
        return False
    if end and ref_date > end:
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


def _stack_key(track: dict) -> str:
    return (track.get("stack_key") or "").strip().lower()


def _passes_artist_sep(track: dict, scheduled: list, rules: dict,
                        artist_lookup: dict = None) -> bool:
    """True if artist separation is satisfied, including group separation."""
    artist = _artist_key(track)
    if not artist:
        return True

    # Determine separation in songs (fallback) and ms (if artist record available)
    sep_songs = rules.get("artist_separation_songs", 9)
    sep_ms    = None
    group_id  = None

    if artist_lookup:
        art_rec = artist_lookup.get(artist)
        if art_rec:
            sep_ms   = art_rec.get("separation_ms")
            group_id = art_rec.get("group_id")

    if sep_ms is not None:
        # Time-based check approximated by look-back window
        window = min(len(scheduled), sep_songs * 3)
        for s in reversed(scheduled[-window:]):
            if _artist_key(s) == artist:
                return False
        # Group separation: if this artist belongs to a group, check group members too
        if group_id and artist_lookup:
            for s in reversed(scheduled[-window:]):
                s_artist = _artist_key(s)
                s_rec    = artist_lookup.get(s_artist)
                if s_rec and s_rec.get("group_id") == group_id:
                    return False
        return True
    else:
        # Song-count-based check
        recent = [_artist_key(s) for s in scheduled[-sep_songs:]]
        if artist in recent:
            return False
        # Group separation
        if group_id and artist_lookup:
            for s in scheduled[-sep_songs:]:
                s_artist = _artist_key(s)
                s_rec    = artist_lookup.get(s_artist)
                if s_rec and s_rec.get("group_id") == group_id and s_artist != artist:
                    return False
        return True


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


def _passes_stack_key_sep(track: dict, scheduled: list, rules: dict,
                           cat_lookup: dict = None, effective_cat: str = "") -> bool:
    """True if stack-key separation is satisfied.

    Keeps songs with the same stack_key apart by at least
    stack_key_separation_songs positions in the schedule.
    The category record can tighten or loosen this per-category.
    """
    sk = _stack_key(track)
    if not sk:
        return True

    sep = rules.get("stack_key_separation_songs", 3)
    if cat_lookup and effective_cat:
        cat_rec = cat_lookup.get(effective_cat)
        if cat_rec:
            cat_sep = cat_rec.get("stack_key_separation_songs", 0)
            if cat_sep > 0:
                sep = cat_sep

    if sep <= 0:
        return True

    recent = [_stack_key(s) for s in scheduled[-sep:]]
    return sk not in recent


# ---------------------------------------------------------------------------
# Album separation check
# ---------------------------------------------------------------------------

def _album_key(track: dict) -> str:
    return (track.get("album") or "").strip().lower()


def _passes_album_sep(track: dict, scheduled: list, rules: dict) -> bool:
    """True if album separation is satisfied (0 = disabled)."""
    album = _album_key(track)
    if not album:
        return True
    sep = rules.get("album_separation_songs", 0)
    if sep <= 0:
        return True
    recent = [_album_key(s) for s in scheduled[-sep:]]
    return album not in recent


# ---------------------------------------------------------------------------
# Energy / BPM step limit checks
# ---------------------------------------------------------------------------

def _passes_step_limits(track: dict, scheduled: list, rules: dict) -> bool:
    """True if energy and BPM don't jump further than allowed from the previous song."""
    if not scheduled:
        return True
    prev = scheduled[-1]

    energy_step = rules.get("energy_step_limit", 0)
    if energy_step and energy_step > 0:
        prev_e = prev.get("energy") or 0
        this_e = track.get("energy") or 0
        if prev_e and this_e and abs(this_e - prev_e) > energy_step:
            return False

    bpm_step = rules.get("bpm_step_limit", 0)
    if bpm_step and bpm_step > 0:
        prev_b = prev.get("bpm") or 0
        this_b = track.get("bpm") or 0
        if prev_b and this_b and abs(this_b - prev_b) > bpm_step:
            return False

    return True


# ---------------------------------------------------------------------------
# Conditional (If/Then) rule evaluation
# ---------------------------------------------------------------------------

_DAYPART_MAP = {
    0: "overnight",    1: "overnight",    2: "overnight",
    3: "overnight",    4: "overnight",
    5: "early_morning",
    6: "morning_drive", 7: "morning_drive", 8: "morning_drive", 9: "morning_drive",
    10: "midmorning",  11: "midmorning",
    12: "midday",      13: "midday",      14: "midday",
    15: "afternoon",   16: "afternoon",   17: "afternoon",
    18: "evening",     19: "evening",     20: "evening",
    21: "late_night",  22: "late_night",
    23: "overnight",
}


def _cr_compare(actual, op: str, value) -> bool:
    """Evaluate: actual <op> value.  Returns False if types are incompatible."""
    if actual is None:
        return False
    try:
        if op == "eq":      return str(actual) == str(value)
        if op == "neq":     return str(actual) != str(value)
        if op == "lt":      return float(actual) < float(value)
        if op == "lte":     return float(actual) <= float(value)
        if op == "gt":      return float(actual) > float(value)
        if op == "gte":     return float(actual) >= float(value)
        if op == "between":
            lo, hi = float(value[0]), float(value[1])
            return lo <= float(actual) <= hi
        if op == "in":      return str(actual) in [str(v) for v in (value or [])]
        if op == "not_in":  return str(actual) not in [str(v) for v in (value or [])]
    except (TypeError, ValueError, IndexError):
        pass
    return False


def _cr_resolve_field(field: str, track: dict, scheduled: list, hour: int):
    """Resolve a condition field name to its current value."""
    if field == "hour":
        return hour
    if field == "daypart":
        return _DAYPART_MAP.get(hour, "overnight")
    if field.startswith("prev_"):
        attr = field[5:]
        return scheduled[-1].get(attr) if scheduled else None
    if field.startswith("run_"):
        attr = field[4:]
        return _current_run(scheduled, attr)
    return track.get(field)


def _eval_cr_conditions(conditions: list, logic: str,
                         track: dict, scheduled: list, hour: int) -> bool:
    """Return True if all (AND) or any (OR) conditions match."""
    if not conditions:
        return False
    results = [
        _cr_compare(
            _cr_resolve_field(c.get("field", ""), track, scheduled, hour),
            c.get("op", "eq"),
            c.get("value"),
        )
        for c in conditions
    ]
    return all(results) if logic != "OR" else any(results)


# Action types that map directly to an existing rule key (override its value)
_ACTION_RULE_MAP = {
    "artist_separation_songs":    "artist_separation_songs",
    "stack_key_separation_songs": "stack_key_separation_songs",
    "max_run_gender":             "max_gender_run",
    "max_run_tempo":              "max_tempo_run",
    "max_run_energy":             "max_energy_run",
    "max_run_mood":               "max_mood_run",
    "max_run_texture":            "max_texture_run",
}

# Attribute requirement actions: candidate track's attribute must satisfy the comparison
_REQUIRE_GTE = {"require_energy_gte": "energy", "require_tempo_gte": "tempo",  "require_bpm_gte": "bpm"}
_REQUIRE_LTE = {"require_energy_lte": "energy", "require_tempo_lte": "tempo",  "require_bpm_lte": "bpm"}
_REQUIRE_EQ  = {"require_gender":     "gender"}
_REQUIRE_NEQ = {"require_gender_neq": "gender"}


def _passes_conditional_rules(track: dict, scheduled: list,
                               rules: dict, hour: int) -> tuple:
    """Evaluate all if/then rules against the candidate track and scheduling context.

    Returns (passes: bool, overrides: dict).
      passes=False  → exclude this track entirely
      overrides     → rule-value overrides to apply for this candidate's eligibility checks
    """
    cond_rules = rules.get("conditional_rules") or []
    overrides: dict = {}

    for cr in cond_rules:
        if not cr.get("enabled", True):
            continue
        conditions      = cr.get("conditions") or []
        condition_logic = cr.get("condition_logic", "AND")
        if not _eval_cr_conditions(conditions, condition_logic, track, scheduled, hour):
            continue

        action = cr.get("action") or {}
        atype  = action.get("type", "")
        aval   = action.get("value")

        if atype == "exclude":
            return False, {}

        # title_separation_hours needs conversion to ms
        if atype == "title_separation_hours":
            try:
                overrides["title_separation_ms"] = int(float(aval) * 3600000)
            except (TypeError, ValueError):
                pass
            continue

        # Direct rule key override
        if atype in _ACTION_RULE_MAP:
            try:
                overrides[_ACTION_RULE_MAP[atype]] = float(aval)
            except (TypeError, ValueError):
                pass
            continue

        # Attribute ≥ requirement
        if atype in _REQUIRE_GTE:
            attr = _REQUIRE_GTE[atype]
            try:
                if (track.get(attr) or 0) < float(aval):
                    return False, {}
            except (TypeError, ValueError):
                pass
            continue

        # Attribute ≤ requirement
        if atype in _REQUIRE_LTE:
            attr = _REQUIRE_LTE[atype]
            try:
                if (track.get(attr) or 0) > float(aval):
                    return False, {}
            except (TypeError, ValueError):
                pass
            continue

        # Attribute = requirement
        if atype in _REQUIRE_EQ:
            attr = _REQUIRE_EQ[atype]
            try:
                if str(track.get(attr) or "") != str(aval):
                    return False, {}
            except (TypeError, ValueError):
                pass
            continue

        # Attribute ≠ requirement
        if atype in _REQUIRE_NEQ:
            attr = _REQUIRE_NEQ[atype]
            try:
                if str(track.get(attr) or "") == str(aval):
                    return False, {}
            except (TypeError, ValueError):
                pass
            continue

    return True, overrides


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
    # Announcer requirement: if slot specifies an announcer, track must match (0 = any)
    slot_ann = slot.get("announcer")
    if slot_ann:
        track_ann = track.get("announcer", 0)
        if track_ann and track_ann != slot_ann:
            return False
    # Track-level announcer requirement: if track requires a specific announcer
    track_ann = track.get("announcer", 0)
    if track_ann:
        slot_ann = slot.get("announcer")
        if slot_ann is not None and slot_ann != 0 and slot_ann != track_ann:
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
        "energy":  rules.get("max_energy_run",  clock.get("max_energy_run",  -1) if clock else -1),
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
                  artist_lookup: dict = None, cat_lookup: dict = None,
                  effective_cat: str = "", sched_date: str = None) -> bool:
    """Return True if track passes ALL hard constraints for this slot."""
    if not track.get("active", True):
        return False
    if not _passes_date_restriction(track, rules, sched_date):
        return False
    if not _passes_hour_restriction(track, hour):
        return False
    if not _passes_position_restriction(track, position_in_hour, total_in_hour, rules):
        return False
    if not _passes_slot_filters(track, slot):
        return False

    # Evaluate conditional (If/Then) rules; get exclude decision + any rule overrides
    passes, overrides = _passes_conditional_rules(track, scheduled, rules, hour)
    if not passes:
        return False
    effective_rules = {**rules, **overrides} if overrides else rules

    if not _passes_artist_sep(track, scheduled, effective_rules, artist_lookup):
        return False
    if not _passes_title_sep(track, scheduled, effective_rules, cat_lookup):
        return False
    if not _passes_stack_key_sep(track, scheduled, effective_rules, cat_lookup, effective_cat):
        return False
    if not _passes_album_sep(track, scheduled, effective_rules):
        return False
    if not _passes_step_limits(track, scheduled, effective_rules):
        return False
    if not _passes_run_limits(track, scheduled, effective_rules, clock):
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

def _build_pool(slot: dict, by_cat: dict, cat_lookup: dict) -> tuple:
    """
    Return the track pool for a slot, following alternate category fallback.
    Returns (pool, effective_cat). Uses first non-empty pool: primary, then alternate1/2/3.
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
                alt_pool = by_cat.get(alt_id) or []
                if alt_pool:
                    return alt_pool, alt_id

    return [], category


def _build_pool_try_order(slot: dict, by_cat: dict, cat_lookup: dict) -> list:
    """
    Return a list of (pool, category_name) in try order: primary first, then
    alternate1, alternate2, alternate3. Only includes (pool, cat) where pool is non-empty.
    Caller should try each in order and use the first that yields eligible tracks.
    """
    category = slot.get("category", "")
    out = []
    primary_pool = by_cat.get(category) or []
    if primary_pool:
        out.append((primary_pool, category))

    cat_rec = cat_lookup.get(category)
    if cat_rec:
        for alt_key in ("alternate1", "alternate2", "alternate3"):
            alt_id = cat_rec.get(alt_key)
            if alt_id:
                alt_pool = by_cat.get(alt_id) or []
                if alt_pool:
                    out.append((alt_pool, alt_id))

    return out


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
# Stack rotation helper
# ---------------------------------------------------------------------------

def _apply_stack_rotation(candidates: list, stack_ptrs: dict,
                           stack_pool: dict) -> list:
    """
    For each stack_key represented in candidates, keep only the track that
    is current in the FIFO rotation for that stack (or the next one that
    appears in candidates, wrapping around).  Non-stacked tracks pass through
    unchanged.

    This ensures that when you have 50 Phil Collins songs or 15 versions of
    "We Three Kings", the scheduler cycles through ALL of them in order
    rather than randomly picking the same few titles repeatedly.
    """
    non_stacked = [t for t in candidates if not _stack_key(t)]

    stacked_picks = []
    seen_stacks   = set()
    id_set        = {t.get("id") for t in candidates}

    for sk, stk_tracks in stack_pool.items():
        if sk in seen_stacks:
            continue
        # Check whether any track from this stack is actually a candidate
        if not any(t.get("id") in id_set for t in stk_tracks):
            continue
        seen_stacks.add(sk)
        ptr = stack_ptrs.get(sk, 0)
        n   = len(stk_tracks)
        for i in range(n):
            candidate = stk_tracks[(ptr + i) % n]
            if candidate.get("id") in id_set:
                stacked_picks.append(candidate)
                break
        # If no eligible stack track found for this key, nothing is added —
        # non-stacked candidates will still fill the slot.

    return non_stacked + stacked_picks


# ---------------------------------------------------------------------------
# Query-pool builder  (for fill_mode = "query")
# ---------------------------------------------------------------------------

def _build_query_pool(query: dict, by_cat: dict) -> list:
    """
    Build a candidate track pool from a cross-category query filter.

    ``query`` keys (all optional):
        categories    — list of category names to search (empty = all)
        tempo_min/max — tempo range (1–5 scale)
        gender        — exact gender value
        mood          — exact mood value
        texture_min/max — texture range
        sound_codes   — list of required sound-code numbers
        sc_and        — True = all codes required; False = any
        min/max_duration_s — duration bounds in seconds
    """
    categories = query.get("categories") or []
    if categories:
        pool = []
        for cat in categories:
            pool.extend(by_cat.get(cat, []))
    else:
        pool = [t for tracks in by_cat.values() for t in tracks]

    tempo_min    = query.get("tempo_min")
    tempo_max    = query.get("tempo_max")
    gender       = query.get("gender")
    mood         = query.get("mood")
    texture_min  = query.get("texture_min")
    texture_max  = query.get("texture_max")
    min_dur      = query.get("min_duration_s")
    max_dur      = query.get("max_duration_s")
    sound_codes  = query.get("sound_codes") or []
    sc_and       = query.get("sc_and", False)

    filtered = []
    for t in pool:
        tempo   = t.get("tempo",   0) or 0
        texture = t.get("texture", 0) or 0

        if tempo_min   is not None and tempo   < tempo_min:    continue
        if tempo_max   is not None and tempo   > tempo_max:    continue
        if gender      is not None and (t.get("gender", 0) or 0) != gender:  continue
        if mood        is not None and (t.get("mood",   0) or 0) != mood:    continue
        if texture_min is not None and texture < texture_min:  continue
        if texture_max is not None and texture > texture_max:  continue

        dur_s = (
            (t.get("duration_ms") or 0) // 1000
            or t.get("duration_seconds") or 0
        )
        if min_dur is not None and dur_s < min_dur: continue
        if max_dur is not None and dur_s > max_dur: continue

        if sound_codes:
            track_codes = set(t.get("sound_codes") or [])
            required    = set(sound_codes)
            if sc_and:
                if not required.issubset(track_codes): continue
            else:
                if not (required & track_codes):        continue

        filtered.append(t)
    return filtered


# ---------------------------------------------------------------------------
# Chain item condition check  (for fill_mode = "chain")
# ---------------------------------------------------------------------------

def _chain_condition_met(item: dict, sched_date: str, daypart_name: str) -> bool:
    """Return False if a chain item has a condition that the current context doesn't match."""
    cond = item.get("condition")
    if not cond:
        return True

    cond_dp = cond.get("daypart")
    if cond_dp and daypart_name and cond_dp.strip().lower() != daypart_name.strip().lower():
        return False

    cond_start = cond.get("start_date")
    if cond_start and sched_date and sched_date < cond_start:
        return False

    cond_end = cond.get("end_date")
    if cond_end and sched_date and sched_date > cond_end:
        return False

    return True


# ---------------------------------------------------------------------------
# Conditional slot helper
# ---------------------------------------------------------------------------

def _slot_condition_met(slot: dict, sched_date: str, daypart_name: str) -> bool:
    """Return False if this slot has a condition that the current context doesn't satisfy."""
    cond_dp = slot.get("condition_daypart")
    if cond_dp and daypart_name and cond_dp.strip().lower() != daypart_name.strip().lower():
        return False

    cond_start = slot.get("condition_start_date")
    if cond_start and sched_date and sched_date < cond_start:
        return False

    cond_end = slot.get("condition_end_date")
    if cond_end and sched_date and sched_date > cond_end:
        return False

    return True


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
    sched_date: str = None,        # ISO date string for slot conditions (default: today)
    daypart_name: str = None,      # current daypart name for conditional slots
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
        sched_date:       ISO date for conditional slot date-range checks (default: today).
        daypart_name:     Daypart name for conditional slot daypart checks.

    Returns:
        list of slot dicts, each with position, category, track_id, title, artist, etc.
    """
    if not tracks:
        return []

    slots = clock.get("slots", [])
    if not slots:
        return []

    if not sched_date:
        sched_date = _today_iso()

    # --- Filter inactive tracks up front ---
    tracks = [t for t in tracks if t.get("active", True)]

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

    # --- Build stack rotation state ---
    # For each stack_key, sort tracks into FIFO order:
    #   1. explicit stack_order (if set)
    #   2. last_played_at ascending (most-rested first)
    # The pointer advances each time a track from that stack is scheduled,
    # ensuring every song in a stack plays before any repeats.
    stack_pool: dict = {}   # stack_key → ordered list of tracks
    for t in tracks:
        sk = _stack_key(t)
        if sk:
            stack_pool.setdefault(sk, []).append(t)
    for sk in stack_pool:
        stack_pool[sk].sort(key=lambda t: (
            t.get("stack_order") or 0,
            t.get("last_played_at") or "",
        ))
    stack_ptrs: dict = {sk: 0 for sk in stack_pool}

    rank_state: dict = {}    # category_name → rotation index

    scheduled:  list = []
    total_secs       = 0
    position         = 1
    slot_idx         = 0
    _MAX_SLOTS       = 1000

    while position <= _MAX_SLOTS:
        slot     = slots[slot_idx % len(slots)]
        slot_typ = slot.get("type", "music")

        # --- Conditional slot: skip if the scheduling context doesn't match ---
        if not _slot_condition_met(slot, sched_date, daypart_name):
            slot_idx += 1
            if target_seconds == 0 and slot_idx >= len(slots):
                break
            continue

        # Non-music slots (spots, liners, lognotes, etc.) pass through without a track
        if slot_typ != "music":
            entry = {
                "position":         position,
                "type":             slot_typ,
                "category":         slot.get("category", ""),
                "title":            slot.get("title", ""),
                "duration_seconds": slot.get("nominal_length_s") or 0,
                "notes":            slot.get("notes", ""),
            }
            # Lognote: include the automation command string
            if slot_typ == "lognote":
                entry["lognote_command"] = slot.get("lognote_command", "")
            scheduled.append(entry)
            total_secs += slot.get("nominal_length_s") or 0
            position   += 1
            slot_idx   += 1
        else:
            # --- Estimate slot count in hour for position flags (shared by all modes) ---
            est_total = len(slots) if target_seconds == 0 else max(len(slots), 10)
            pos_in_hr = (position - 1) % max(1, est_total)

            fill_mode = slot.get("fill_mode", "category")

            # ---------------------------------------------------------------
            # fill_mode = "chain"
            # Try each chain item in order; use the first that yields eligible
            # tracks.  A "void" item type means: explicitly skip this slot.
            # ---------------------------------------------------------------
            if fill_mode == "chain":
                chain   = slot.get("chain") or []
                chosen  = None
                effective_cat = slot.get("category", "")

                for item in chain:
                    # Check the item-level condition gate
                    if not _chain_condition_met(item, sched_date, daypart_name):
                        continue

                    item_type = item.get("type", "category")

                    if item_type == "void":
                        break  # explicit skip — leave chosen = None

                    if item_type == "category":
                        item_pool = by_cat.get(item.get("category", "")) or []
                        item_cat  = item.get("category", "")
                    elif item_type == "query":
                        item_pool = _build_query_pool(item.get("query") or {}, by_cat)
                        item_cat  = item.get("label", "")
                    else:
                        continue

                    if not item_pool:
                        continue  # nothing in this pool — try next chain item

                    # Check eligibility within this item's pool
                    item_elig = [
                        t for t in item_pool
                        if _is_eligible(
                            t, scheduled, slot, rules,
                            hour=hour,
                            position_in_hour=pos_in_hr,
                            total_in_hour=est_total,
                            clock=clock,
                            artist_lookup=artist_lookup,
                            cat_lookup=cat_lookup,
                            effective_cat=item_cat,
                            sched_date=sched_date,
                        )
                        and t.get("id") not in prev_day_set
                    ]
                    # Relax prev-day restriction if needed
                    if not item_elig:
                        item_elig = [
                            t for t in item_pool
                            if _is_eligible(
                                t, scheduled, slot, rules,
                                hour=hour,
                                position_in_hour=pos_in_hr,
                                total_in_hour=est_total,
                                clock=clock,
                                artist_lookup=artist_lookup,
                                cat_lookup=cat_lookup,
                                effective_cat=item_cat,
                                sched_date=sched_date,
                            )
                        ]

                    if not item_elig:
                        continue  # no eligible tracks in this item — try next

                    # Found a viable chain item — pick from it
                    effective_cat = item_cat
                    if stack_pool:
                        item_elig = _apply_stack_rotation(item_elig, stack_ptrs, stack_pool)
                    cat_rec    = cat_lookup.get(effective_cat, {})
                    force_rank = cat_rec.get("force_rank_rotation", False) if cat_rec else False
                    chosen = _pick(item_elig, scheduled, slot, rules,
                                   force_rank=force_rank,
                                   rank_state=rank_state,
                                   cat_name=effective_cat)
                    break

                if chosen is None:
                    # All chain items exhausted (or void hit) — skip this slot
                    slot_idx += 1
                    if target_seconds == 0 and slot_idx >= len(slots):
                        break
                    continue

            # ---------------------------------------------------------------
            # fill_mode = "query"  (cross-category search with attribute filters)
            # ---------------------------------------------------------------
            elif fill_mode == "query":
                pool          = _build_query_pool(slot.get("query") or {}, by_cat)
                effective_cat = slot.get("category", "")

                if not pool:
                    slot_idx += 1
                    if target_seconds == 0 and slot_idx >= len(slots):
                        break
                    continue

                cat_rec    = cat_lookup.get(effective_cat, {})
                force_rank = cat_rec.get("force_rank_rotation", False) if cat_rec else False

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
                        effective_cat=effective_cat,
                        sched_date=sched_date,
                    )
                    and t.get("id") not in prev_day_set
                ]
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
                            effective_cat=effective_cat,
                            sched_date=sched_date,
                        )
                    ]

                if stack_pool and eligible:
                    eligible = _apply_stack_rotation(eligible, stack_ptrs, stack_pool)

                if not eligible:
                    fallback_pool = pool
                    if stack_pool:
                        rotated = _apply_stack_rotation(pool, stack_ptrs, stack_pool)
                        if rotated:
                            fallback_pool = rotated
                    chosen = _fallback_pick(fallback_pool, scheduled)
                else:
                    chosen = _pick(eligible, scheduled, slot, rules,
                                   force_rank=force_rank,
                                   rank_state=rank_state,
                                   cat_name=effective_cat)

            # ---------------------------------------------------------------
            # fill_mode = "category"  (default — prefer primary, then alternates)
            # ---------------------------------------------------------------
            else:
                # Try primary category first, then alternate1, alternate2, alternate3.
                # Use the first pool that yields at least one eligible track.
                try_order = _build_pool_try_order(slot, by_cat, cat_lookup)
                if not try_order:
                    slot_idx += 1
                    if target_seconds == 0 and slot_idx >= len(slots):
                        break
                    continue

                chosen = None
                effective_cat = None
                pool = None

                for pool, effective_cat in try_order:
                    cat_rec = cat_lookup.get(effective_cat, {})
                    force_rank = cat_rec.get("force_rank_rotation", False) if cat_rec else False

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
                            effective_cat=effective_cat,
                            sched_date=sched_date,
                        )
                        and t.get("id") not in prev_day_set
                    ]
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
                                effective_cat=effective_cat,
                                sched_date=sched_date,
                            )
                        ]

                    if stack_pool and eligible:
                        eligible = _apply_stack_rotation(eligible, stack_ptrs, stack_pool)

                    if eligible:
                        chosen = _pick(eligible, scheduled, slot, rules,
                                      force_rank=force_rank,
                                      rank_state=rank_state,
                                      cat_name=effective_cat)
                        break

                if chosen is None:
                    # No eligible in any pool — fallback pick from first pool
                    pool, effective_cat = try_order[0]
                    fallback_pool = pool
                    if stack_pool:
                        rotated = _apply_stack_rotation(pool, stack_ptrs, stack_pool)
                        if rotated:
                            fallback_pool = rotated
                    chosen = _fallback_pick(fallback_pool, scheduled)

            # Advance the stack pointer when a stacked track is chosen
            sk = _stack_key(chosen)
            if sk in stack_ptrs:
                stack_ptrs[sk] = (stack_ptrs[sk] + 1) % max(1, len(stack_pool[sk]))

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
                "id":               chosen.get("id"),
                "track_id":         chosen.get("id"),
                "title":            chosen.get("title"),
                "artist":           chosen.get("artist"),
                "album":            chosen.get("album", ""),
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
                "isrc_code":        chosen.get("isrc_code", ""),
                "record_label":     chosen.get("record_label", ""),
                "publisher":        chosen.get("publisher", ""),
                "composer":         chosen.get("composer", ""),
                "genre":            chosen.get("genre", ""),
                "announcer":        chosen.get("announcer", 0),
                "play_count":       chosen.get("play_count", 0),
                "last_played_at":   chosen.get("last_played_at"),
                "stack_key":        chosen.get("stack_key", ""),
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
