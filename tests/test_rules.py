"""
Tests for:
  GET  /api/rules   — retrieve global rotation rules
  PUT  /api/rules   — update global rotation rules
  Integration: generate_schedule honours global rules
"""
import json
import os

import pytest

import app as app_module
from app import app
from engine.rules import DEFAULT_RULES


@pytest.fixture(autouse=True)
def isolated_rules_file(monkeypatch, tmp_path):
    tmp_file = str(tmp_path / "rules.json")
    monkeypatch.setattr(app_module, "RULES_FILE", tmp_file)
    yield tmp_file


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


# ---------------------------------------------------------------------------
# GET /api/rules
# ---------------------------------------------------------------------------

def test_get_rules_returns_defaults_when_no_file(client):
    resp  = client.get("/api/rules")
    assert resp.status_code == 200
    rules = resp.get_json()
    assert rules["artist_separation_songs"] == DEFAULT_RULES["artist_separation_songs"]
    assert rules["title_separation_hours"]  == DEFAULT_RULES["title_separation_hours"]
    assert "categories"                     in rules


# ---------------------------------------------------------------------------
# PUT /api/rules
# ---------------------------------------------------------------------------

def test_put_rules_persists(client):
    resp = client.put(
        "/api/rules",
        data=json.dumps({"artist_separation_songs": 5}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["artist_separation_songs"] == 5

    # Confirm it survives a subsequent GET
    fetched = client.get("/api/rules").get_json()
    assert fetched["artist_separation_songs"] == 5


def test_put_rules_partial_override_keeps_defaults(client):
    client.put(
        "/api/rules",
        data=json.dumps({"artist_separation_songs": 4}),
        content_type="application/json",
    )
    fetched = client.get("/api/rules").get_json()
    # Changed key
    assert fetched["artist_separation_songs"] == 4
    # Untouched key stays at default
    assert fetched["title_separation_hours"] == DEFAULT_RULES["title_separation_hours"]


def test_put_rules_empty_body_restores_defaults(client):
    # First set a custom value
    client.put("/api/rules", data=json.dumps({"artist_separation_songs": 3}),
               content_type="application/json")
    # Now send empty body
    client.put("/api/rules", data=json.dumps({}), content_type="application/json")
    fetched = client.get("/api/rules").get_json()
    assert fetched["artist_separation_songs"] == DEFAULT_RULES["artist_separation_songs"]


# ---------------------------------------------------------------------------
# Integration: generate_schedule uses global rules
# ---------------------------------------------------------------------------

def _make_tracks(client, count=6):
    for i in range(count):
        client.post(
            "/api/tracks",
            data=json.dumps({
                "title":            f"Song {i}",
                "artist":           f"Artist {i}",
                "category":         "Current",
                "duration_seconds": 210,
            }),
            content_type="application/json",
        )


def _make_clock(client, slots=4):
    return client.post(
        "/api/clocks",
        data=json.dumps({
            "name":  "Test Hour",
            "slots": [
                {"position": i + 1, "category": "Current", "duration_seconds": 210, "notes": ""}
                for i in range(slots)
            ],
        }),
        content_type="application/json",
    ).get_json()


def test_global_rules_embedded_in_generated_schedule(client):
    _make_tracks(client)
    client.put("/api/rules",
               data=json.dumps({"artist_separation_songs": 3}),
               content_type="application/json")
    clock    = _make_clock(client)
    schedule = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": clock["id"]}),
        content_type="application/json",
    ).get_json()
    assert schedule["rules"]["artist_separation_songs"] == 3


def test_per_request_rules_override_global(client):
    _make_tracks(client)
    client.put("/api/rules",
               data=json.dumps({"artist_separation_songs": 3}),
               content_type="application/json")
    clock    = _make_clock(client)
    schedule = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": clock["id"],
                         "rules":    {"artist_separation_songs": 7}}),
        content_type="application/json",
    ).get_json()
    assert schedule["rules"]["artist_separation_songs"] == 7


# ---------------------------------------------------------------------------
# Stats on generated schedule
# ---------------------------------------------------------------------------

def test_generated_schedule_includes_stats(client):
    _make_tracks(client, count=6)
    clock    = _make_clock(client, slots=4)
    schedule = client.post(
        "/api/schedule/generate",
        data=json.dumps({"clock_id": clock["id"]}),
        content_type="application/json",
    ).get_json()
    stats = schedule["stats"]
    # Clock cycles to fill ≥60 min, so more than just 4 slots
    assert stats["total_tracks"]           > 4
    assert stats["total_duration_seconds"] >= 3600
    assert "total_duration_hms"            in stats
    assert "category_breakdown"            in stats
    assert "unique_artists"                in stats
