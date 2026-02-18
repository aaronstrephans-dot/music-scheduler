"""
Tests for:
  - engine.validator.validate_schedule (unit)
  - POST /api/schedule/<id>/validate   (integration)
"""
import json
import os

import pytest

import app as app_module
from app import app
from engine.rules import DEFAULT_RULES, merge_rules
from engine.validator import validate_schedule


# ---------------------------------------------------------------------------
# Unit tests for engine.validator
# ---------------------------------------------------------------------------

def _slot(pos, title, artist, category="Current", duration=210):
    return {
        "position":         pos,
        "title":            title,
        "artist":           artist,
        "category":         category,
        "duration_seconds": duration,
    }


def test_valid_schedule_no_violations():
    tracks = [
        _slot(1, "Song A", "Artist 1"),
        _slot(2, "Song B", "Artist 2"),
        _slot(3, "Song C", "Artist 3"),
    ]
    result = validate_schedule(tracks, DEFAULT_RULES)
    assert result["valid"] is True
    assert result["violations"] == []
    assert result["stats"]["total_slots"] == 3
    assert result["stats"]["unique_artists"] == 3


def test_detects_artist_separation_violation():
    rules  = merge_rules({"artist_separation_songs": 3})
    tracks = [
        _slot(1, "Song A", "The Artist"),
        _slot(2, "Song B", "Other"),
        _slot(3, "Song C", "The Artist"),   # gap=2, rule=3 → violation
    ]
    result = validate_schedule(tracks, rules)
    assert result["valid"] is True          # artist violations are warnings
    assert any(v["type"] == "artist_separation" for v in result["violations"])
    assert result["stats"]["warnings"] == 1


def test_detects_title_separation_violation():
    tracks = [
        _slot(1, "Same Song", "Artist A"),
        _slot(2, "Different", "Artist B"),
        _slot(3, "Same Song", "Artist A"),  # title repeat → error
    ]
    result = validate_schedule(tracks, DEFAULT_RULES)
    assert result["valid"] is False
    assert any(v["type"] == "title_separation" for v in result["violations"])
    assert result["stats"]["errors"] >= 1


def test_detects_missing_artist():
    tracks = [{"position": 1, "title": "Song", "category": "Current"}]
    result = validate_schedule(tracks)
    assert result["valid"] is False
    assert any(v["type"] == "missing_artist" for v in result["violations"])


def test_detects_missing_title():
    tracks = [{"position": 1, "artist": "Artist", "category": "Current"}]
    result = validate_schedule(tracks)
    assert result["valid"] is False
    assert any(v["type"] == "missing_title" for v in result["violations"])


def test_stats_category_breakdown():
    tracks = [
        _slot(1, "A", "X", category="Current"),
        _slot(2, "B", "Y", category="Current"),
        _slot(3, "C", "Z", category="Gold"),
    ]
    stats = validate_schedule(tracks)["stats"]
    assert stats["category_breakdown"]["Current"] == 2
    assert stats["category_breakdown"]["Gold"]    == 1


def test_stats_duration():
    tracks = [_slot(i, f"S{i}", f"A{i}", duration=180) for i in range(3)]
    stats  = validate_schedule(tracks)["stats"]
    assert stats["total_duration_seconds"] == 540
    assert stats["total_duration_hms"]     == "00:09:00"


def test_empty_schedule_is_valid():
    result = validate_schedule([])
    assert result["valid"]  is True
    assert result["stats"]["total_slots"] == 0


# ---------------------------------------------------------------------------
# Integration tests for POST /api/schedule/<id>/validate
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_dirs(monkeypatch, tmp_path):
    for attr, subdir in [
        ("SCHEDULES_DIR", "schedules"),
        ("TRACKS_DIR",    "tracks"),
        ("CLOCKS_DIR",    "clocks"),
    ]:
        d = str(tmp_path / subdir)
        os.makedirs(d)
        monkeypatch.setattr(app_module, attr, d)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _gen_manual(client, tracks):
    return client.post(
        "/api/schedule/generate",
        data=json.dumps({"name": "Test", "tracks": tracks}),
        content_type="application/json",
    ).get_json()


def test_validate_clean_manual_schedule(client):
    schedule = _gen_manual(client, [
        {"position": 1, "title": "Song A", "artist": "Artist 1",
         "category": "Current", "duration_seconds": 210},
        {"position": 2, "title": "Song B", "artist": "Artist 2",
         "category": "Current", "duration_seconds": 210},
    ])
    resp = client.post(f"/api/schedule/{schedule['id']}/validate",
                       content_type="application/json")
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["valid"] is True
    assert "stats" in result


def test_validate_flags_repeat_title(client):
    schedule = _gen_manual(client, [
        {"position": 1, "title": "Same Song", "artist": "Artist A",
         "category": "Current", "duration_seconds": 210},
        {"position": 2, "title": "Same Song", "artist": "Artist A",
         "category": "Current", "duration_seconds": 210},
    ])
    resp   = client.post(f"/api/schedule/{schedule['id']}/validate",
                          content_type="application/json")
    result = resp.get_json()
    assert result["valid"] is False
    assert any(v["type"] == "title_separation" for v in result["violations"])


def test_validate_with_rule_override(client):
    """Passing stricter rules in the request body should be respected."""
    schedule = _gen_manual(client, [
        {"position": 1, "title": "Song A", "artist": "The Artist",
         "category": "Current", "duration_seconds": 210},
        {"position": 2, "title": "Song B", "artist": "Other",
         "category": "Current", "duration_seconds": 210},
        {"position": 3, "title": "Song C", "artist": "The Artist",
         "category": "Current", "duration_seconds": 210},
    ])
    # Default sep=9, so gap=2 would be a violation; override to sep=1 (no violation)
    resp = client.post(
        f"/api/schedule/{schedule['id']}/validate",
        data=json.dumps({"rules": {"artist_separation_songs": 1}}),
        content_type="application/json",
    )
    result = resp.get_json()
    assert not any(v["type"] == "artist_separation" for v in result["violations"])


def test_validate_not_found(client):
    resp = client.post("/api/schedule/nonexistent/validate",
                       content_type="application/json")
    assert resp.status_code == 404
