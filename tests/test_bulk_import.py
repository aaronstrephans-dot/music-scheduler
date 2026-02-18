import json
import os

import pytest

import app as app_module
from app import app

_VALID_TRACK = {
    "title":            "Song",
    "artist":           "Artist",
    "category":         "Current",
    "duration_seconds": 210,
    "bpm":              120,
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


def _import(client, tracks, **kwargs):
    body = {"tracks": tracks, **kwargs}
    return client.post("/api/tracks/import", data=json.dumps(body),
                       content_type="application/json")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_import_single_track(client):
    resp = _import(client, [_VALID_TRACK])
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["imported"] == 1
    assert body["errors"]   == 0
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["play_count"] == 0


def test_import_multiple_tracks(client):
    tracks = [
        {**_VALID_TRACK, "title": f"Song {i}", "artist": f"Artist {i}"}
        for i in range(10)
    ]
    resp = _import(client, tracks)
    assert resp.status_code == 201
    assert resp.get_json()["imported"] == 10


def test_import_tracks_are_findable(client):
    _import(client, [{**_VALID_TRACK, "title": "Imported Track"}])
    body = client.get("/api/tracks?search=Imported").get_json()
    assert body["total"] == 1


def test_import_plain_array_body(client):
    """Also accept a bare JSON array (not wrapped in {tracks: [...]})."""
    tracks = [{**_VALID_TRACK, "title": "Plain Array Track"}]
    resp   = client.post("/api/tracks/import",
                         data=json.dumps(tracks),
                         content_type="application/json")
    assert resp.status_code == 201
    assert resp.get_json()["imported"] == 1


# ---------------------------------------------------------------------------
# Partial failures
# ---------------------------------------------------------------------------

def test_import_partial_errors(client):
    tracks = [
        _VALID_TRACK,                          # valid
        {"title": "Missing Artist and Cat"},   # missing artist + category
        {**_VALID_TRACK, "title": "Also valid"},
    ]
    resp = _import(client, tracks)
    assert resp.status_code == 201          # partial success
    body = resp.get_json()
    assert body["imported"] == 2
    assert body["errors"]   == 1
    assert body["error_details"][0]["index"] == 1


def test_import_all_invalid_returns_400(client):
    tracks = [
        {"title": "No artist"},
        {"artist": "No title"},
    ]
    resp = _import(client, tracks)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["imported"] == 0
    assert body["errors"]   == 2


def test_import_empty_list(client):
    resp = _import(client, [])
    assert resp.status_code == 400
    assert resp.get_json()["imported"] == 0


# ---------------------------------------------------------------------------
# IDs and defaults
# ---------------------------------------------------------------------------

def test_import_assigns_uuid(client):
    resp   = _import(client, [_VALID_TRACK])
    track  = resp.get_json()["tracks"][0]
    assert "id"       in track
    assert len(track["id"]) == 36         # UUID4 format


def test_import_ignores_supplied_id(client):
    """Callers cannot dictate the assigned ID."""
    resp  = _import(client, [{**_VALID_TRACK, "id": "custom-id"}])
    track = resp.get_json()["tracks"][0]
    assert track["id"] != "custom-id"
