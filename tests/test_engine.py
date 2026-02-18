from engine.rotator import build_schedule
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
    """A never-played track should win the single slot more often than a stale one."""
    tracks = [
        _track("fresh", "Fresh Track", "New Artist", play_count=0),
        _track("stale", "Old Track",   "Old Artist", play_count=50,
               last_played="2020-01-01T00:00:00Z"),
    ]
    clock = _clock(["Current"])
    wins  = {"fresh": 0, "stale": 0}
    for _ in range(30):
        result = build_schedule(clock, tracks, DEFAULT_RULES)
        wins[result[0]["track_id"]] += 1
    assert wins["fresh"] > wins["stale"]


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
