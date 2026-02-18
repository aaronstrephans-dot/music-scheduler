import json
import os

import pytest

import app as app_module
from app import app

_PAYLOAD = {
    "title":            "Blinding Lights",
    "artist":           "The Weeknd",
    "album":            "After Hours",
    "year":             2019,
    "duration_seconds": 200,
    "bpm":              171,
    "energy":           8,
    "mood":             "energetic",
    "genre":            "synth-pop",
    "category":         "Current",
}


@pytest.fixture(autouse=True)
def isolated_tracks_dir(monkeypatch, tmp_path):
    tmp_dir = str(tmp_path / "tracks")
    os.makedirs(tmp_dir)
    monkeypatch.setattr(app_module, "TRACKS_DIR", tmp_dir)
    yield tmp_dir


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _create(client, overrides=None):
    payload = {**_PAYLOAD, **(overrides or {})}
    return client.post("/api/tracks", data=json.dumps(payload),
                       content_type="application/json").get_json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_track(client):
    resp = client.post("/api/tracks", data=json.dumps(_PAYLOAD), content_type="application/json")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["title"]          == "Blinding Lights"
    assert data["artist"]         == "The Weeknd"
    assert data["category"]       == "Current"
    assert "id"                   in data
    assert data["play_count"]     == 0
    assert data["last_played_at"] is None


def test_create_track_missing_title(client):
    resp = client.post("/api/tracks",
                       data=json.dumps({"artist": "X", "category": "Current"}),
                       content_type="application/json")
    assert resp.status_code == 400
    assert "title" in resp.get_json()["error"]


def test_create_track_missing_artist(client):
    resp = client.post("/api/tracks",
                       data=json.dumps({"title": "X", "category": "Current"}),
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_track_missing_category(client):
    resp = client.post("/api/tracks",
                       data=json.dumps({"title": "X", "artist": "Y"}),
                       content_type="application/json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Read — list (paginated)
# ---------------------------------------------------------------------------

def test_list_tracks_empty(client):
    resp = client.get("/api/tracks")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"]  == 0
    assert body["tracks"] == []


def test_list_tracks(client):
    for name in ("Song A", "Song B", "Song C"):
        _create(client, {"title": name})
    body = client.get("/api/tracks").get_json()
    assert body["total"]       == 3
    assert len(body["tracks"]) == 3


def test_list_tracks_filter_by_category(client):
    _create(client)                                    # Current
    _create(client, {"title": "Gold Song", "category": "Gold"})

    current = client.get("/api/tracks?category=Current").get_json()
    assert current["total"] == 1
    assert current["tracks"][0]["category"] == "Current"

    gold = client.get("/api/tracks?category=Gold").get_json()
    assert gold["total"] == 1
    assert gold["tracks"][0]["category"] == "Gold"


def test_list_tracks_search_by_title(client):
    _create(client, {"title": "Dancing Queen"})
    _create(client, {"title": "Bohemian Rhapsody"})
    body = client.get("/api/tracks?search=dancing").get_json()
    assert body["total"] == 1
    assert body["tracks"][0]["title"] == "Dancing Queen"


def test_list_tracks_search_by_artist(client):
    _create(client, {"artist": "ABBA"})
    _create(client, {"artist": "Queen"})
    body = client.get("/api/tracks?search=abba").get_json()
    assert body["total"] == 1
    assert body["tracks"][0]["artist"] == "ABBA"


def test_list_tracks_pagination(client):
    for i in range(5):
        _create(client, {"title": f"Track {i}"})
    body = client.get("/api/tracks?limit=2&offset=1").get_json()
    assert body["total"]       == 5   # total before paging
    assert len(body["tracks"]) == 2


def test_list_tracks_sort_by_play_count(client):
    _create(client, {"title": "Played Often"})
    _create(client, {"title": "Never Played"})
    # bump one track's play count
    first_id = client.get("/api/tracks").get_json()["tracks"][0]["id"]
    client.post(f"/api/tracks/{first_id}/play", content_type="application/json")
    client.post(f"/api/tracks/{first_id}/play", content_type="application/json")

    body = client.get("/api/tracks?sort=play_count&order=desc").get_json()
    assert body["tracks"][0]["play_count"] >= body["tracks"][1]["play_count"]


# ---------------------------------------------------------------------------
# Read — single
# ---------------------------------------------------------------------------

def test_get_track(client):
    created = _create(client)
    resp    = client.get(f"/api/tracks/{created['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Blinding Lights"


def test_get_track_not_found(client):
    assert client.get("/api/tracks/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_track(client):
    created = _create(client)
    resp    = client.put(
        f"/api/tracks/{created['id']}",
        data=json.dumps({"energy": 9, "play_count": 3}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["energy"]     == 9
    assert data["play_count"] == 3
    assert data["title"]      == "Blinding Lights"   # unchanged


def test_update_track_not_found(client):
    resp = client.put("/api/tracks/bad-id", data=json.dumps({"energy": 5}),
                      content_type="application/json")
    assert resp.status_code == 404


def test_update_track_cannot_change_id(client):
    created     = _create(client)
    original_id = created["id"]
    updated     = client.put(
        f"/api/tracks/{original_id}",
        data=json.dumps({"id": "hacked-id"}),
        content_type="application/json",
    ).get_json()
    assert updated["id"] == original_id


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_track(client):
    created = _create(client)
    resp    = client.delete(f"/api/tracks/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/tracks/{created['id']}").status_code == 404


def test_delete_track_not_found(client):
    assert client.delete("/api/tracks/nonexistent").status_code == 404
