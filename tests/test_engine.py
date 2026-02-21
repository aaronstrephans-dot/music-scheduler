from engine.rotator import build_schedule, _build_query_pool, _score
from engine.rules import DEFAULT_RULES, merge_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(id, title, artist, category="Current", bpm=120, energy=7,
           play_count=0, last_played=None):
    return {
        "id":             id,
        "title":          title,
        "artist":         artist,
        "category":       category,
        "bpm":            bpm,
        "energy":         energy,
        "duration_seconds": 210,
        "play_count":     play_count,
        "last_played_at": last_played,
    }


def _clock(categories):
    return {
        "name":  "Test Clock",
        "slots": [
            {"position": i + 1, "category": cat, "duration_seconds": 210, "notes": ""}
            for i, cat in enumerate(categories)
        ],
    }


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

def test_basic_schedule_fills_all_slots():
    tracks = [_track(f"t{i}", f"Song {i}", f"Artist {i}") for i in range(5)]
    result = build_schedule(_clock(["Current", "Current", "Current"]), tracks, DEFAULT_RULES)
    assert len(result) == 3
    assert all("track_id" in s for s in result)
    assert all(s["category"] == "Current" for s in result)


def test_result_fields_present():
    tracks = [_track("t1", "Song", "Artist")]
    result = build_schedule(_clock(["Current"]), tracks, DEFAULT_RULES)
    slot   = result[0]
    for field in ("position", "category", "track_id", "title", "artist",
                  "duration_seconds", "bpm", "energy", "mood", "notes"):
        assert field in slot, f"missing field: {field}"


def test_category_fallback_uses_full_library():
    """When no tracks match the slot category, fall back to the full library."""
    tracks = [_track(f"t{i}", f"Song {i}", f"Artist {i}", category="Gold") for i in range(3)]
    result = build_schedule(_clock(["Current"]), tracks, DEFAULT_RULES)
    assert len(result) == 1  # slot filled from fallback


def test_empty_library_returns_empty():
    result = build_schedule(_clock(["Current", "Current"]), [], DEFAULT_RULES)
    assert result == []


# ---------------------------------------------------------------------------
# Artist separation
# ---------------------------------------------------------------------------

def test_artist_not_repeated_in_separation_window():
    """Hard artist-separation: same artist must not appear within the separation window."""
    # 4 tracks (2 per artist), 4 slots, sep=1 — each track used exactly once,
    # no title repeats, so hard exclusions are sufficient to guarantee alternation.
    tracks = [
        _track("a1", "Song A1", "Artist A"),
        _track("a2", "Song A2", "Artist A"),
        _track("b1", "Song B1", "Artist B"),
        _track("b2", "Song B2", "Artist B"),
    ]
    rules  = merge_rules({"artist_separation_songs": 1})
    result = build_schedule(_clock(["Current"] * 4), tracks, rules)
    assert len(result) == 4
    for i in range(len(result) - 1):
        assert result[i]["artist"] != result[i + 1]["artist"]


def test_fallback_alternates_artists_on_tiny_library():
    """When all tracks are title-excluded the fallback should still alternate artists."""
    tracks = [
        _track("a1", "Song A1", "Artist A"),
        _track("a2", "Song A2", "Artist A"),
        _track("b1", "Song B1", "Artist B"),
        _track("b2", "Song B2", "Artist B"),
    ]
    # 6 slots forces title repetition after slot 4 — fallback kicks in
    result = build_schedule(_clock(["Current"] * 6), tracks, DEFAULT_RULES)
    assert len(result) == 6
    # The fallback should alternate artists; no two consecutive slots same artist
    for i in range(len(result) - 1):
        assert result[i]["artist"] != result[i + 1]["artist"]


# ---------------------------------------------------------------------------
# Play-count / recency preference
# ---------------------------------------------------------------------------

def test_prefers_unplayed_over_frequently_played():
    """A never-played track should score higher than a frequently-played stale one."""
    fresh = _track("fresh", "Fresh Track", "New Artist", play_count=0)
    stale = _track("stale", "Old Track",   "Old Artist", play_count=50,
                   last_played="2020-01-01T00:00:00Z")
    assert _score(fresh, [], DEFAULT_RULES) > _score(stale, [], DEFAULT_RULES)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def test_merge_rules_overrides_specific_keys():
    rules = merge_rules({"artist_separation_songs": 5})
    assert rules["artist_separation_songs"] == 5
    # Untouched keys keep their defaults
    assert rules["title_separation_hours"] == DEFAULT_RULES["title_separation_hours"]


def test_merge_rules_preserves_all_defaults_when_empty():
    rules = merge_rules({})
    assert rules == DEFAULT_RULES


def test_custom_rules_respected_in_schedule():
    """With artist_separation_songs=1 only one track per artist should repeat rarely."""
    tracks = [
        _track("t1", "Song 1", "Solo Artist"),
        _track("t2", "Song 2", "Solo Artist"),
    ]
    rules  = merge_rules({"artist_separation_songs": 1})
    result = build_schedule(_clock(["Current", "Current"]), tracks, rules)
    # With only one artist in the library we can't fully avoid repetition,
    # but the engine should still produce a result (not crash)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# fill_mode = "query"  (cross-category song search)
# ---------------------------------------------------------------------------

def _query_slot(query: dict) -> dict:
    return {"fill_mode": "query", "category": "", "query": query}


def test_query_slot_searches_across_categories():
    """A query slot should pull from all listed categories, not just one."""
    tracks = [
        {**_track("a1", "Alpha", "Artist A", category="Gold"),    "tempo": 3},
        {**_track("b1", "Beta",  "Artist B", category="Current"), "tempo": 3},
        {**_track("c1", "Gamma", "Artist C", category="Gold"),    "tempo": 1},
    ]
    clock = {
        "name":  "Query Clock",
        "slots": [_query_slot({"categories": ["Gold", "Current"], "tempo_min": 3})],
    }
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    # Only tracks with tempo >= 3 qualify — "Gamma" (tempo=1) must NOT appear
    assert result[0]["title"] in ("Alpha", "Beta")


def test_query_slot_empty_categories_searches_all():
    """An empty categories list in a query should search the whole library."""
    tracks = [
        {**_track("x1", "X1", "Art1", category="Rock"),   "tempo": 4},
        {**_track("x2", "X2", "Art2", category="Jazz"),   "tempo": 4},
        {**_track("x3", "X3", "Art3", category="Pop"),    "tempo": 1},
    ]
    clock = {
        "name":  "All-Lib Query",
        "slots": [_query_slot({"tempo_min": 4})],
    }
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    assert result[0]["title"] in ("X1", "X2")


def test_query_slot_gender_filter():
    """Query gender filter should exclude non-matching tracks."""
    tracks = [
        {**_track("m1", "Male Song",   "Art1"), "gender": 1},
        {**_track("f1", "Female Song", "Art2"), "gender": 2},
    ]
    clock = {"name": "Gender Query", "slots": [_query_slot({"gender": 2})]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    assert result[0]["title"] == "Female Song"


def test_build_query_pool_tempo_range():
    """Unit-test _build_query_pool directly for tempo range filtering."""
    tracks = [
        {**_track("s1", "Slow", "A1"), "tempo": 1},
        {**_track("m1", "Med",  "A2"), "tempo": 3},
        {**_track("f1", "Fast", "A3"), "tempo": 5},
    ]
    by_cat = {"Cat": tracks}
    pool   = _build_query_pool({"categories": ["Cat"], "tempo_min": 2, "tempo_max": 4}, by_cat)
    assert len(pool) == 1
    assert pool[0]["title"] == "Med"


def test_build_query_pool_duration_filter():
    """Duration bounds should filter by track length in seconds."""
    tracks = [
        {**_track("s1", "Short", "A1"), "duration_seconds": 120},
        {**_track("m1", "Long",  "A2"), "duration_seconds": 360},
    ]
    by_cat = {"Cat": tracks}
    pool   = _build_query_pool(
        {"categories": ["Cat"], "min_duration_s": 200, "max_duration_s": 400}, by_cat
    )
    assert len(pool) == 1
    assert pool[0]["title"] == "Long"


# ---------------------------------------------------------------------------
# fill_mode = "chain"  (ordered if/then fallback)
# ---------------------------------------------------------------------------

def _chain_slot(chain: list, **extra) -> dict:
    return {"fill_mode": "chain", "category": "", "chain": chain, **extra}


def test_chain_uses_first_viable_item():
    """Chain should pick from the first item whose pool has eligible tracks."""
    tracks = [
        _track("g1", "Gold Song",    "Artist G", category="Gold"),
        _track("r1", "Recurrent 1",  "Artist R", category="Recurrent"),
    ]
    chain = [
        {"type": "category", "category": "Current"},    # empty — skip
        {"type": "category", "category": "Gold"},       # has tracks — use this
        {"type": "category", "category": "Recurrent"},  # never reached
    ]
    clock  = {"name": "Chain Clock", "slots": [_chain_slot(chain)]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    assert result[0]["title"] == "Gold Song"


def test_chain_falls_through_to_later_item():
    """Chain advances past empty pools until finding tracks."""
    tracks = [_track("r1", "Recurrent", "Art R", category="Recurrent")]
    chain  = [
        {"type": "category", "category": "Current"},   # empty
        {"type": "category", "category": "Gold"},      # empty
        {"type": "category", "category": "Recurrent"}, # has tracks
    ]
    clock  = {"name": "Fallthrough", "slots": [_chain_slot(chain)]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    assert result[0]["title"] == "Recurrent"


def test_chain_void_skips_slot():
    """A 'void' item in a chain should cause the slot to be skipped entirely."""
    tracks = [_track("g1", "Gold", "Art G", category="Gold")]
    chain  = [
        {"type": "void"},                           # explicit skip
        {"type": "category", "category": "Gold"},  # never reached
    ]
    clock  = {"name": "Void Chain", "slots": [_chain_slot(chain)]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert result == []


def test_chain_all_empty_skips_slot():
    """If all chain items have empty pools the slot is silently skipped."""
    tracks = [_track("g1", "Gold", "Art G", category="Gold")]
    chain  = [
        {"type": "category", "category": "NonExistent"},
        {"type": "category", "category": "AlsoMissing"},
    ]
    clock  = {"name": "All Empty", "slots": [_chain_slot(chain)]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert result == []


def test_chain_condition_gates_item():
    """A chain item with a daypart condition should be skipped if context doesn't match."""
    tracks = [
        _track("m1", "Morning Song",  "Art A", category="Morning"),
        _track("d1", "Default Song",  "Art B", category="Default"),
    ]
    chain = [
        {
            "type":      "category",
            "category":  "Morning",
            "condition": {"daypart": "Morning Drive"},
        },
        {"type": "category", "category": "Default"},
    ]
    clock = {"name": "Conditional Chain", "slots": [_chain_slot(chain)]}

    # Scheduled during Afternoon Drive — Morning Drive condition fails, falls to Default
    result = build_schedule(
        clock, tracks, DEFAULT_RULES, daypart_name="Afternoon Drive"
    )
    assert len(result) == 1
    assert result[0]["title"] == "Default Song"

    # Scheduled during Morning Drive — condition matches, uses Morning
    result = build_schedule(
        clock, tracks, DEFAULT_RULES, daypart_name="Morning Drive"
    )
    assert len(result) == 1
    assert result[0]["title"] == "Morning Song"


def test_chain_with_query_item():
    """A chain item of type 'query' should search by attribute filter."""
    tracks = [
        {**_track("s1", "Slow Song", "Art1", category="Rock"), "tempo": 1},
        {**_track("f1", "Fast Song", "Art2", category="Rock"), "tempo": 5},
    ]
    chain = [
        {
            "type":  "query",
            "label": "Fast Rock",
            "query": {"categories": ["Rock"], "tempo_min": 4},
        },
    ]
    clock  = {"name": "Query Chain", "slots": [_chain_slot(chain)]}
    result = build_schedule(clock, tracks, DEFAULT_RULES)
    assert len(result) == 1
    assert result[0]["title"] == "Fast Song"
